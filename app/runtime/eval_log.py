import json
import time
from pathlib import Path
from typing import Any

from app.core.config import load_config
from app.runtime.bus import STATE

LOG_PATH = Path("/logs/eval_events.jsonl")


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".")
    return str(v)


def summarize_dets(det_pack: Any) -> str:
    from collections import Counter

    if not isinstance(det_pack, dict):
        return "-"

    counts = Counter()
    for d in (det_pack.get("detections") or []):
        if not isinstance(d, dict):
            continue
        name = d.get("name") or d.get("class") or d.get("label") or "?"
        counts[str(name)] += 1

    return ",".join(f"{name}[{cnt}]" for name, cnt in counts.most_common()) if counts else "-"


def _write_jsonl(obj: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[eval] jsonl write error: {e!r}", flush=True)


def emit_eval_log(
    event: str,
    *,
    frame_id=None,
    video_sec=None,
    yolo_fps=None,
    yolo_latency_ms=None,
    vlm_ttft_ms=None,
    vlm_latency_ms=None,
    payload="-",
) -> None:
    try:
        cfg = load_config() or {}
        ecfg = (cfg.get("evaluation", {}) or {})
        if not bool(ecfg.get("log_enabled", False)):
            return

        started_at = getattr(STATE, "eval_started_at", None)
        now = time.time()
        app_ms = int((now - float(started_at)) * 1000) if started_at else -1

        line = (
            f"app_ms={_fmt(app_ms)}\t"
            f"video_sec={_fmt(video_sec)}\t"
            f"frame_id={_fmt(frame_id)}\t"
            f"yolo_fps={_fmt(yolo_fps)}\t"
            f"yolo_latency_ms={_fmt(yolo_latency_ms)}\t"
            f"vlm_ttft_ms={_fmt(vlm_ttft_ms)}\t"
            f"vlm_latency_ms={_fmt(vlm_latency_ms)}\t"
            f"event={event}\t"
            f"payload={payload}"
        )
        print("[eval]", line, flush=True)

        obj = {
            "ts": now,
            "app_ms": app_ms,
            "video_sec": video_sec,
            "frame_id": frame_id,
            "yolo_fps": yolo_fps,
            "yolo_latency_ms": yolo_latency_ms,
            "vlm_ttft_ms": vlm_ttft_ms,
            "vlm_latency_ms": vlm_latency_ms,
            "event": event,
            "payload": payload,
        }
        _write_jsonl(obj)

    except Exception as e:
        print(f"[eval] logger error: {e!r}", flush=True)
