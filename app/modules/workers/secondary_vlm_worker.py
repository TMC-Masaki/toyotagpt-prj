import copy
import json
import shutil
import time
import threading
from pathlib import Path
from queue import Empty

import cv2
import numpy as np

from app.core.config import load_config
from app.modules.pipeline import inference_pipeline as ip
from app.runtime.bus import STATE, SECONDARY_INFER_Q
from app.runtime.eval_log import emit_eval_log


SECONDARY_PROMPT = """目的：
一次推論イベントの妥当性を確認し、根拠と要約を日本語で返す。

最重要ルール：
- 画像根拠を最優先する
- 根拠が弱い場合は weak
- 根拠が無い場合は invalid
- 出力形式以外の文は書かない

出力形式：
validity: <valid | weak | invalid>
matched_event: <event key or none>
evidence: <画像根拠を1〜2文で書く>
summary: <状況要約を1〜2文で書く>

判定観点：
- road_depression: 路面の穴、陥没、舗装異常
- fallen_object: 路上障害物、散乱物、落下物
- road_work: コーン、ポール、工事規制、作業帯
- traffic_jam: 車列の滞留、低速で詰まった連続車両
- accident: 衝突、破損、不自然停止車両
- blind_spot: 死角、遮蔽、見通し不良
- pedestrian_attention: 歩行者、自転車、飛び出し注意
- intersection_complexity: 交差点、合流、分岐、右左折の複雑性
"""


def _safe_read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _write_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _summarize_yolo(yolo_obj) -> str:
    if isinstance(yolo_obj, list):
        counts = {}
        for x in yolo_obj:
            k = str(x)
            counts[k] = counts.get(k, 0) + 1
        if counts:
            return ",".join(f"{k}[{v}]" for k, v in counts.items())
    if isinstance(yolo_obj, dict):
        try:
            return json.dumps(yolo_obj, ensure_ascii=False)
        except Exception:
            return str(yolo_obj)
    return str(yolo_obj or "")


def _summarize_can(can_obj) -> str:
    if not isinstance(can_obj, dict):
        return str(can_obj or "")
    parts = []
    if can_obj.get("speed_kmh") is not None:
        parts.append(f"speed={can_obj.get('speed_kmh')} km/h")
    if can_obj.get("shift") is not None:
        parts.append(f"shift={can_obj.get('shift')}")
    if can_obj.get("steering_rate") is not None:
        parts.append(f"steering_rate={can_obj.get('steering_rate')}")
    pedal = can_obj.get("pedal")
    if isinstance(pedal, dict):
        parts.append(f"pedal={pedal}")
    return ", ".join(parts)


def _make_contact_sheet(image_paths: list[str], out_path: Path):
    imgs = []
    for p in image_paths:
        try:
            img = cv2.imread(str(p))
            if img is not None:
                imgs.append(img)
        except Exception:
            pass

    if not imgs:
        return None

    target_h = 256
    resized = []
    for img in imgs:
        h, w = img.shape[:2]
        nw = max(1, int(w * (target_h / max(h, 1))))
        resized.append(cv2.resize(img, (nw, target_h)))

    max_w = max(x.shape[1] for x in resized)
    padded = []
    for img in resized:
        h, w = img.shape[:2]
        if w < max_w:
            pad = np.zeros((h, max_w - w, 3), dtype=np.uint8)
            img = np.concatenate([img, pad], axis=1)
        padded.append(img)

    sheet = np.concatenate(padded, axis=1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(out_path), sheet)
    if not ok:
        return None
    return out_path


def _parse_secondary_output(text: str) -> dict:
    raw = str(text or "").strip()
    parsed = {
        "raw_text": raw,
        "normalized_text": raw,
        "validity": None,
        "matched_event": None,
        "evidence": None,
        "summary": None,
    }
    if not raw:
        return parsed

    lines = [x.strip() for x in raw.replace("\r", "\n").split("\n") if x.strip()]
    joined = " ".join(lines)

    def _pick(prefix: str):
        low = joined.lower()
        p = prefix.lower() + ":"
        idx = low.find(p)
        if idx < 0:
            return None
        rest = joined[idx + len(p):].strip()
        cut_points = []
        for nxt in ["validity:", "matched_event:", "evidence:", "summary:"]:
            if nxt == p:
                continue
            j = rest.lower().find(nxt)
            if j >= 0:
                cut_points.append(j)
        if cut_points:
            rest = rest[:min(cut_points)].strip()
        return rest or None

    parsed["validity"] = _pick("validity")
    parsed["matched_event"] = _pick("matched_event")
    parsed["evidence"] = _pick("evidence")
    parsed["summary"] = _pick("summary")
    return parsed


def _gnss_upload_ok(gnss_obj) -> bool:
    if not isinstance(gnss_obj, dict):
        return False
    return (
        gnss_obj.get("status") == "OK"
        and gnss_obj.get("lat") is not None
        and gnss_obj.get("lon") is not None
    )


def _approval_from_results(primary_event: str, parsed_secondary: dict, gnss_obj=None) -> tuple[str, str | None]:
    validity = str((parsed_secondary or {}).get("validity") or "").strip().lower()
    matched_event = str((parsed_secondary or {}).get("matched_event") or "").strip()

    if validity != "valid":
        return "rejected", f"secondary_validity_{validity or 'missing'}"

    if not matched_event or matched_event == "none":
        return "rejected", "secondary_no_match"

    if matched_event != str(primary_event or ""):
        return "rejected", "secondary_mismatch_primary"

    return "approved", None

def _update_manifest_and_upload_status(event_dir: Path, approval_state: str, reason: str | None):
    manifest_path = event_dir / "bundle_manifest.json"
    upload_path = event_dir / "upload_status.json"
    gnss_path = event_dir / "gnss_snapshot.json"

    manifest = _safe_read_json(manifest_path) or {}
    manifest.setdefault("status", {})
    manifest["status"]["bundle_state"] = "secondary_done"
    manifest["status"]["secondary_done"] = True
    manifest["status"]["approval_state"] = approval_state
    manifest["status"]["upload_state"] = "pending" if approval_state == "approved" else "rejected"
    manifest.setdefault("has_assets", {})
    manifest["has_assets"]["secondary_result"] = True
    manifest["secondary_reason"] = reason
    _write_json(manifest_path, manifest)

    gnss = _safe_read_json(gnss_path) or {}
    approved_at = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()) if approval_state == "approved" else None

    upload = _safe_read_json(upload_path) or {}
    upload["event_id"] = upload.get("event_id") or manifest.get("event_id") or event_dir.name
    upload["upload_state"] = "pending" if approval_state == "approved" else "rejected"
    upload["approval_state"] = approval_state
    upload["approval_reason"] = reason
    upload["approved_at"] = approved_at
    upload["last_error"] = None if approval_state == "approved" else reason
    upload["gnss_status"] = gnss.get("status")
    upload["gnss_lat"] = gnss.get("lat")
    upload["gnss_lon"] = gnss.get("lon")
    upload["location_available"] = (gnss.get("lat") is not None and gnss.get("lon") is not None)
    upload.setdefault("uploaded_at", None)
    upload.setdefault("retry_count", 0)
    upload.setdefault("s3_prefix", None)
    upload.setdefault("ddb_written", False)
    _write_json(upload_path, upload)

def _write_bundle_complete(event_dir: Path):
    files = []
    for p in sorted(event_dir.rglob("*")):
        if p.is_file():
            files.append(str(p.relative_to(event_dir)))
    _write_json(
        event_dir / "bundle_complete.json",
        {
            "event_id": event_dir.name,
            "bundle_complete": True,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
            "files": files,
        },
    )


def _move_to_state_dir(event_dir: Path, state_name: str) -> Path:
    pending_root = event_dir.parent
    base_root = pending_root.parent
    target_root = base_root / state_name
    target_root.mkdir(parents=True, exist_ok=True)
    target_dir = target_root / event_dir.name

    if target_dir.exists():
        shutil.rmtree(target_dir)

    shutil.move(str(event_dir), str(target_dir))
    return target_dir


class SecondaryVlmWorker(threading.Thread):
    daemon = True

    def __init__(self, cam_id: int = 0):
        super().__init__()
        self.cam_id = cam_id
        self._stop_evt = threading.Event()

    def stop(self):
        self._stop_evt.set()

    def run(self):
        print(f"[secondary_vlm_worker] run_enter cam_id={self.cam_id}", flush=True)
        with STATE.lock:
            STATE.latest_secondary_status[self.cam_id] = "idle"
            STATE.latest_secondary_result[self.cam_id] = None
            STATE.latest_secondary_error[self.cam_id] = None

        while not self._stop_evt.is_set():
            try:
                job = SECONDARY_INFER_Q.get(timeout=0.2)
            except Empty:
                continue
            except Exception:
                time.sleep(0.1)
                continue

            if not isinstance(job, dict):
                continue

            event_dir = Path(str(job.get("event_dir") or ""))
            try:
                with STATE.lock:
                    STATE.latest_secondary_status[self.cam_id] = "running"
                    STATE.latest_secondary_error[self.cam_id] = None

                metadata = _safe_read_json(event_dir / "metadata.json") or {}
                manifest = _safe_read_json(event_dir / "bundle_manifest.json") or {}
                primary_obj = _safe_read_json(event_dir / "primary_result.json") or {}
                primary_text = _safe_read_text(event_dir / "primary_result.txt").strip()
                yolo_obj = _safe_read_json(event_dir / "yolo_result.json")
                can_obj = _safe_read_json(event_dir / "can_snapshot.json")
                gnss_obj = _safe_read_json(event_dir / "gnss_snapshot.json") or {}

                primary_event = (
                    ((primary_obj.get("output") or {}).get("event_type"))
                    or str(job.get("event_type") or "")
                )
                primary_event_types = (
                    ((primary_obj.get("output") or {}).get("event_types"))
                    or list(job.get("event_types") or [])
                )

                primary_frame_path = job.get("primary_frame_path")
                frame = None
                secondary_input_image = None

                if primary_frame_path:
                    frame = cv2.imread(str(primary_frame_path))
                    if frame is not None:
                        secondary_input_image = str(primary_frame_path)

                if frame is None:
                    sampled_paths = list(job.get("sampled_frame_paths") or [])
                    sheet_path = _make_contact_sheet(sampled_paths, event_dir / "secondary_input.jpg")
                    if sheet_path is None:
                        raise RuntimeError("secondary input frame load failed")
                    frame = cv2.imread(str(sheet_path))
                    secondary_input_image = str(sheet_path)

                if frame is None:
                    raise RuntimeError("secondary frame load failed")

                yolo_summary = _summarize_yolo(yolo_obj)
                can_summary = _summarize_can(can_obj)

                secondary_input = {
                    "event_id": job.get("event_id"),
                    "source_primary_frame_path": primary_frame_path,
                    "source_secondary_input_image": secondary_input_image,
                    "source_clip_path": job.get("clip_path"),
                    "input_summary": {
                        "primary_event": primary_event,
                        "primary_event_candidates": list(primary_event_types or []),
                        "primary_text": primary_text,
                        "can_speed_kmh": (can_obj or {}).get("speed_kmh") if isinstance(can_obj, dict) else None,
                        "shift": (can_obj or {}).get("shift") if isinstance(can_obj, dict) else None,
                        "yolo_labels": yolo_summary,
                        "gnss": {
                            "status": gnss_obj.get("status"),
                            "lat": gnss_obj.get("lat"),
                            "lon": gnss_obj.get("lon"),
                            "fix_type": gnss_obj.get("fix_type"),
                            "mode": gnss_obj.get("mode"),
                        },
                    },
                    "prompt_version": "secondary_v1",
                }
                _write_json(event_dir / "secondary_input.json", secondary_input)

                secondary_prompt = (
                    f"{SECONDARY_PROMPT}\n\n"
                    f"Detected event keys: {','.join(primary_event_types or [])}\n"
                    f"Primary inference output: {primary_text}\n"
                    f"YOLO summary: {yolo_summary}\n"
                    f"Vehicle state: {can_summary}\n"
                    f"GNSS summary: status={gnss_obj.get('status')}, lat={gnss_obj.get('lat')}, lon={gnss_obj.get('lon')}, mode={gnss_obj.get('mode')}\n"
                    f"Event metadata: event_type={job.get('event_type')}, event_dir={event_dir}\n"
                )

                cfg = copy.deepcopy(load_config())
                cfg.setdefault("vlm", {})
                cfg["vlm"]["prompt"] = secondary_prompt
                cfg["vlm"]["max_new_tokens"] = 100

                t0 = time.time()
                result = ip._run_vlm(frame, cfg)
                latency_ms = int((time.time() - t0) * 1000)

                if not isinstance(result, dict):
                    result = {"text": str(result)}

                out_text = str(result.get("text") or "").strip()
                parsed = _parse_secondary_output(out_text)

                secondary_result = {
                    "event_id": job.get("event_id"),
                    "event_type": job.get("event_type"),
                    "event_types": list(job.get("event_types") or []),
                    "latency_ms": latency_ms,
                    "model": {
                        "engine": (cfg.get("vlm") or {}).get("engine"),
                        "model_name": (cfg.get("vlm") or {}).get("model_name"),
                    },
                    "output": parsed,
                    "raw": result,
                    "metadata": metadata,
                    "manifest": manifest,
                }

                (event_dir / "secondary_result.txt").write_text(out_text, encoding="utf-8")
                _write_json(event_dir / "secondary_result.json", secondary_result)

                approval_state, reason = _approval_from_results(primary_event, parsed, gnss_obj)
                _update_manifest_and_upload_status(event_dir, approval_state, reason)
                _write_bundle_complete(event_dir)

                target_state_dir = "approved" if approval_state == "approved" else "rejected"
                moved_dir = _move_to_state_dir(event_dir, target_state_dir)

                pack = {
                    "event_id": job.get("event_id"),
                    "event_type": job.get("event_type"),
                    "event_types": list(job.get("event_types") or []),
                    "event_dir": str(moved_dir),
                    "text": out_text,
                    "latency_ms": latency_ms,
                    "approval_state": approval_state,
                    "approval_reason": reason,
                    "ts": time.time(),
                }

                with STATE.lock:
                    STATE.latest_secondary_result[self.cam_id] = pack
                    STATE.latest_secondary_status[self.cam_id] = "done"
                    STATE.latest_secondary_error[self.cam_id] = None

                print(
                    f"[secondary_vlm_worker] done event_type={job.get('event_type')} "
                    f"event_dir={moved_dir} latency_ms={latency_ms} approval={approval_state} reason={reason}",
                    flush=True,
                )

                emit_eval_log(
                    event="SECONDARY_RESULT",
                    payload=str(moved_dir),
                )

            except Exception as e:
                with STATE.lock:
                    STATE.latest_secondary_status[self.cam_id] = "error"
                    STATE.latest_secondary_error[self.cam_id] = repr(e)
                print(f"[secondary_vlm_worker] error: {e!r}", flush=True)
