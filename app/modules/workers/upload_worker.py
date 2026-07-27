import json
import shutil
import threading
import time
from decimal import Decimal
from pathlib import Path

from app.core.config import load_config


def _safe_read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def _update_manifest_upload_state(event_dir: Path, upload_state: str):
    manifest_path = event_dir / "bundle_manifest.json"
    manifest = _safe_read_json(manifest_path) or {}
    manifest.setdefault("status", {})
    manifest["status"]["upload_state"] = upload_state
    _write_json(manifest_path, manifest)


def _event_title(event_type: str) -> str:
    return {
        "road_depression": "路面陥没の疑い",
        "fallen_object": "落下物の疑い",
        "road_work": "道路工事イベント",
        "traffic_jam": "渋滞検知",
        "accident": "事故の疑い",
        "blind_spot": "死角注意",
        "pedestrian_attention": "歩行者注意",
        "intersection_complexity": "交差点複雑度高",
    }.get(str(event_type or ""), str(event_type or "event"))


def _event_severity(event_type: str) -> str:
    return {
        "road_depression": "high",
        "fallen_object": "high",
        "accident": "high",
        "road_work": "medium",
        "traffic_jam": "medium",
        "blind_spot": "medium",
        "pedestrian_attention": "medium",
        "intersection_complexity": "low",
    }.get(str(event_type or ""), "low")


def _to_ddb_value(v):
    if isinstance(v, bool) or v is None or isinstance(v, str) or isinstance(v, int):
        return v
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, list):
        return [_to_ddb_value(x) for x in v]
    if isinstance(v, tuple):
        return [_to_ddb_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _to_ddb_value(val) for k, val in v.items()}
    return v


class UploadWorker(threading.Thread):
    daemon = True

    def __init__(self, cam_id: int = 0):
        super().__init__()
        self.cam_id = cam_id
        self._stop_evt = threading.Event()

    def stop(self):
        self._stop_evt.set()

    def _event_roots(self):
        cfg = load_config() or {}
        save_root = str(((cfg.get("output") or {}).get("save_dir")) or "/logs/events")
        root = Path(save_root)
        approved = root / "approved"
        uploaded = root / "uploaded"
        failed = root / "failed"
        approved.mkdir(parents=True, exist_ok=True)
        uploaded.mkdir(parents=True, exist_ok=True)
        failed.mkdir(parents=True, exist_ok=True)
        return root, approved, uploaded, failed

    def _upload_cfg(self):
        cfg = load_config() or {}
        up = cfg.get("upload") or {}
        return {
            "enabled": bool(up.get("enabled", False)),
            "mode": str(up.get("mode") or "local"),
            "poll_interval_sec": float(up.get("poll_interval_sec") or 2.0),
            "max_retries": int(up.get("max_retries") or 3),
            "retry_backoff_sec": int(up.get("retry_backoff_sec") or 30),
            "s3_bucket": str(up.get("s3_bucket") or ""),
            "s3_prefix_base": str(up.get("s3_prefix_base") or "events"),
            "dynamodb_table": str(up.get("dynamodb_table") or ""),
            "aws_region": str(up.get("aws_region") or "ap-northeast-1"),
        }

    def _move_dir(self, src_dir: Path, dst_root: Path) -> Path:
        dst_root.mkdir(parents=True, exist_ok=True)
        target_dir = dst_root / src_dir.name
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.move(str(src_dir), str(target_dir))
        return target_dir

    def _mark_uploaded(self, event_dir: Path, upload: dict, uploaded_root: Path, event_id: str):
        upload["event_id"] = event_id
        upload["upload_state"] = "uploaded"
        upload["uploaded_at"] = _now_iso()
        upload["last_error"] = None
        upload["s3_prefix"] = upload.get("s3_prefix") or event_id
        upload["ddb_written"] = True
        upload["next_retry_at"] = None
        _write_json(event_dir / "upload_status.json", upload)
        _update_manifest_upload_state(event_dir, "uploaded")
        moved = self._move_dir(event_dir, uploaded_root)
        print(f"[upload_worker] uploaded event_id={event_id} target={moved}", flush=True)

    def _schedule_retry_or_fail(self, event_dir: Path, upload: dict, failed_root: Path, event_id: str, err: Exception, max_retries: int, retry_backoff_sec: int):
        retry_count = int(upload.get("retry_count") or 0) + 1
        upload["event_id"] = event_id
        upload["retry_count"] = retry_count
        upload["last_error"] = repr(err)
        upload["next_retry_at"] = int(time.time()) + int(retry_backoff_sec)

        if retry_count >= max_retries:
            upload["upload_state"] = "failed"
            _write_json(event_dir / "upload_status.json", upload)
            _update_manifest_upload_state(event_dir, "failed")
            moved = self._move_dir(event_dir, failed_root)
            print(
                f"[upload_worker] failed event_id={event_id} retry_count={retry_count} "
                f"target={moved} error={err!r}",
                flush=True,
            )
            return

        upload["upload_state"] = "pending"
        _write_json(event_dir / "upload_status.json", upload)
        _update_manifest_upload_state(event_dir, "pending")
        print(
            f"[upload_worker] retry scheduled event_id={event_id} retry_count={retry_count} "
            f"next_retry_at={upload['next_retry_at']} error={err!r}",
            flush=True,
        )

    def _should_wait_retry(self, upload: dict) -> bool:
        next_retry_at = upload.get("next_retry_at")
        if next_retry_at in (None, "", 0):
            return False
        try:
            return int(time.time()) < int(next_retry_at)
        except Exception:
            return False

    def _build_s3_prefix(self, upcfg: dict, event_id: str) -> str:
        base = str(upcfg.get("s3_prefix_base") or "events").strip("/")
        return f"{base}/{event_id}"

    def _process_local_bundle(self, event_dir: Path, uploaded_root: Path, failed_root: Path, upcfg: dict):
        upload_path = event_dir / "upload_status.json"
        upload = _safe_read_json(upload_path) or {}
        event_id = str(upload.get("event_id") or event_dir.name)

        try:
            upload["s3_prefix"] = self._build_s3_prefix(upcfg, event_id)
            self._mark_uploaded(event_dir, upload, uploaded_root, event_id)
        except Exception as e:
            self._schedule_retry_or_fail(
                event_dir=event_dir,
                upload=upload,
                failed_root=failed_root,
                event_id=event_id,
                err=e,
                max_retries=upcfg["max_retries"],
                retry_backoff_sec=upcfg["retry_backoff_sec"],
            )

    def _process_aws_bundle(self, event_dir: Path, uploaded_root: Path, failed_root: Path, upcfg: dict):
        upload_path = event_dir / "upload_status.json"
        manifest_path = event_dir / "bundle_manifest.json"
        upload = _safe_read_json(upload_path) or {}
        manifest = _safe_read_json(manifest_path) or {}
        event_id = str(upload.get("event_id") or manifest.get("event_id") or event_dir.name)

        try:
            import boto3

            region = upcfg["aws_region"]
            bucket = str(upcfg["s3_bucket"] or "").strip()
            table_name = str(upcfg["dynamodb_table"] or "").strip()
            if not bucket:
                raise RuntimeError("upload.s3_bucket is empty")
            if not table_name:
                raise RuntimeError("upload.dynamodb_table is empty")

            s3_prefix = self._build_s3_prefix(upcfg, event_id)
            s3 = boto3.client("s3", region_name=region)
            ddb = boto3.resource("dynamodb", region_name=region)
            table = ddb.Table(table_name)

            for p in sorted(event_dir.rglob("*")):
                if not p.is_file():
                    continue
                key = f"{s3_prefix}/{p.relative_to(event_dir)}"
                s3.upload_file(str(p), bucket, key)

            primary = _safe_read_json(event_dir / "primary_result.json") or {}
            secondary = _safe_read_json(event_dir / "secondary_result.json") or {}
            can_snapshot = _safe_read_json(event_dir / "can_snapshot.json") or {}
            gnss_snapshot = _safe_read_json(event_dir / "gnss_snapshot.json") or {}

            event_type = str(manifest.get("primary_event") or primary.get("output", {}).get("event_type") or "event")
            title = _event_title(event_type)
            severity = _event_severity(event_type)

            primary_summary = str((primary.get("output") or {}).get("normalized_text") or event_type)
            secondary_summary = str((secondary.get("output") or {}).get("summary") or "")
            evidence = str((secondary.get("output") or {}).get("evidence") or "")

            clip_s3_key = f"{s3_prefix}/clip_pre20s.mp4"
            thumbnail_s3_key = f"{s3_prefix}/frames/primary_input.jpg"

            pedal = dict(can_snapshot.get("pedal") or {})
            item = {
                "event-id": event_id,
                "event_id": event_id,
                "event_type": event_type,
                "title": title,
                "severity": severity,
                "occurred_at": manifest.get("created_at"),
                "created_at": manifest.get("created_at"),
                "session_id": manifest.get("session_id"),
                "trip_id": manifest.get("session_id"),
                "device_id": manifest.get("device_id"),
                "vehicle_id": manifest.get("device_id"),
                "user_id": "unknown",
                "cam_id": int(manifest.get("cam_id") or 0),
                "approval_state": ((manifest.get("status") or {}).get("approval_state")),
                "upload_state": "uploaded",
                "s3_prefix": s3_prefix,

                "location": {
                    "lat": gnss_snapshot.get("lat"),
                    "lng": gnss_snapshot.get("lon"),
                    "region": "unknown",
                    "status": gnss_snapshot.get("status"),
                },
                "gnss_status": gnss_snapshot.get("status"),
                "gnss_lat": gnss_snapshot.get("lat"),
                "gnss_lon": gnss_snapshot.get("lon"),
                "location_available": (
                    gnss_snapshot.get("lat") is not None and gnss_snapshot.get("lon") is not None
                ),

                "vision": {
                    "primary_summary": primary_summary,
                    "secondary_summary": secondary_summary,
                    "evidence": evidence,
                    "clip_s3_key": clip_s3_key,
                    "thumbnail_s3_key": thumbnail_s3_key,
                },

                "can": {
                    "snapshot": {
                        "speed_kmh": can_snapshot.get("speed_kmh"),
                        "shift": can_snapshot.get("shift"),
                        "accel_pedal_pct": pedal.get("accel"),
                        "brake_pedal_pct": pedal.get("brake"),
                        "steering_angle_deg": None,
                        "steering_rate_deg_s": can_snapshot.get("steering_rate"),
                        "yaw_rate_deg_s": None,
                        "turn_signal": "unknown",
                    },
                    "window_summary": {
                        "max_speed_kmh": None,
                        "min_speed_kmh": None,
                        "max_brake_pedal_pct": None,
                        "max_steering_rate_deg_s": None,
                        "sudden_brake": None,
                        "sudden_steering": None,
                    },
                },

                "clip_s3_key": clip_s3_key,
                "thumbnail_s3_key": thumbnail_s3_key,
            }
            item = _to_ddb_value(item)
            table.put_item(Item=item)

            upload["s3_prefix"] = s3_prefix
            upload["ddb_written"] = True
            self._mark_uploaded(event_dir, upload, uploaded_root, event_id)

        except Exception as e:
            self._schedule_retry_or_fail(
                event_dir=event_dir,
                upload=upload,
                failed_root=failed_root,
                event_id=event_id,
                err=e,
                max_retries=upcfg["max_retries"],
                retry_backoff_sec=upcfg["retry_backoff_sec"],
            )

    def run(self):
        print(f"[upload_worker] run_enter cam_id={self.cam_id}", flush=True)

        while not self._stop_evt.is_set():
            try:
                upcfg = self._upload_cfg()
                if not upcfg["enabled"]:
                    time.sleep(1.0)
                    continue

                mode = upcfg["mode"]
                poll_interval = upcfg["poll_interval_sec"]
                _, approved_root, uploaded_root, failed_root = self._event_roots()

                for event_dir in sorted(approved_root.iterdir()):
                    if self._stop_evt.is_set():
                        break
                    if not event_dir.is_dir():
                        continue

                    upload_path = event_dir / "upload_status.json"
                    upload = _safe_read_json(upload_path) or {}
                    approval_state = str(upload.get("approval_state") or "")
                    upload_state = str(upload.get("upload_state") or "")

                    if approval_state != "approved":
                        continue
                    if upload_state != "pending":
                        continue
                    if self._should_wait_retry(upload):
                        continue

                    if mode == "local":
                        self._process_local_bundle(event_dir, uploaded_root, failed_root, upcfg)
                    elif mode == "aws":
                        self._process_aws_bundle(event_dir, uploaded_root, failed_root, upcfg)
                    else:
                        print(f"[upload_worker] unsupported mode={mode} event_dir={event_dir}", flush=True)

                time.sleep(poll_interval)

            except Exception as e:
                print(f"[upload_worker] loop error: {e!r}", flush=True)
                time.sleep(1.0)
