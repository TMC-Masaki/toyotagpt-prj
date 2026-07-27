from __future__ import annotations

import json
import os
import time
import uuid
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import cv2

from app.runtime.event_buffer import BufferedFrame, EventRingBuffer


def _safe_json(v: Any) -> Any:
    try:
        json.dumps(v, ensure_ascii=False)
        return v
    except Exception:
        return str(v)


def _now_iso_local() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def _event_id(event_type: str, cam_id: int, device_id: str) -> str:
    ts = time.strftime("%Y%m%dT%H%M%SJST", time.localtime())
    shortid = uuid.uuid4().hex[:6]
    safe_device = str(device_id or "device").replace(" ", "_")
    safe_event = str(event_type or "event").replace(" ", "_")
    return f"{ts}_{safe_device}_cam{int(cam_id)}_{safe_event}_{shortid}"


def _write_text(path: Path, text: str) -> None:
    path.write_text(str(text or ""), encoding="utf-8")


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(
        json.dumps(_safe_json(obj), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _save_clip_mp4(path: Path, frames: List[BufferedFrame], fps: float = 10.0) -> None:
    if not frames:
        return

    first = EventRingBuffer.decode_jpeg(frames[0])
    h, w = first.shape[:2]

    raw_path = path.with_name(path.stem + "_raw.mp4")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(str(raw_path), fourcc, float(fps), (w, h))
    if not vw.isOpened():
        raise RuntimeError(f"VideoWriter open failed: {raw_path}")

    try:
        vw.write(first)
        for item in frames[1:]:
            img = EventRingBuffer.decode_jpeg(item)
            ih, iw = img.shape[:2]
            if (iw, ih) != (w, h):
                img = cv2.resize(img, (w, h))
            vw.write(img)
    finally:
        vw.release()

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(raw_path),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-an",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    if proc.returncode != 0:
        try:
            if raw_path.exists():
                raw_path.replace(path)
        finally:
            raise RuntimeError(
                "ffmpeg transcode failed: "
                f"returncode={proc.returncode} stderr={proc.stderr[-1200:]}"
            )

    try:
        raw_path.unlink(missing_ok=True)
    except Exception:
        pass


def _save_primary_input(dir_path: Path, primary_input: Dict[str, Any]) -> str | None:
    dir_path.mkdir(parents=True, exist_ok=True)

    frame = (primary_input or {}).get("frame_bgr")
    if frame is None:
        return None

    out_path = dir_path / "primary_input.jpg"
    ok = cv2.imwrite(str(out_path), frame)
    if not ok:
        raise RuntimeError(f"cv2.imwrite failed: {out_path}")
    return str(out_path)


def _normalize_gnss_snapshot(gnss_snapshot: Dict[str, Any] | None, event_id: str, trigger_ts: float) -> Dict[str, Any]:
    src = dict(gnss_snapshot or {})
    return {
        "event_id": event_id,
        "ts": src.get("ts", trigger_ts),
        "status": src.get("status", "UNKNOWN"),
        "lat": src.get("lat"),
        "lon": src.get("lon"),
        "alt_m": src.get("alt_m"),
        "speed_mps": src.get("speed_mps"),
        "heading_deg": src.get("heading_deg"),
        "fix_type": src.get("fix_type"),
        "hdop": src.get("hdop"),
        "mode": src.get("mode"),
        "connected": src.get("connected"),
        "raw": src,
    }


def save_event_bundle(
    *,
    save_root: str,
    event_type: str,
    event_types: List[str],
    cam_id: int,
    trigger_ts: float,
    primary_text: str,
    primary_input: Dict[str, Any],
    yolo_detect: Any,
    can_snapshot: Dict[str, Any],
    gnss_snapshot: Dict[str, Any] | None,
    buffer: EventRingBuffer,
    session_id: str | None = None,
    device_id: str | None = None,
) -> Dict[str, Any]:
    root = Path(save_root).expanduser()
    pending_root = root / "pending"
    approved_root = root / "approved"
    uploaded_root = root / "uploaded"
    rejected_root = root / "rejected"
    failed_root = root / "failed"
    sessions_root = root / "sessions"

    for p in [pending_root, approved_root, uploaded_root, rejected_root, failed_root, sessions_root]:
        p.mkdir(parents=True, exist_ok=True)

    device_id = str(device_id or os.getenv("VLM_DEVICE_ID") or "jetson01")
    if not session_id:
        session_id = time.strftime("session_%Y%m%dT%H%M%SJST", time.localtime())

    eid = _event_id(event_type or "event", cam_id=int(cam_id), device_id=device_id)
    event_dir = pending_root / eid
    frames_dir = event_dir / "frames"
    event_dir.mkdir(parents=True, exist_ok=True)

    primary_input = dict(primary_input or {})
    primary_frame_path = _save_primary_input(frames_dir, primary_input)

    clip_frames = buffer.snapshot_last(20.0) if buffer is not None else []
    clip_path = event_dir / "clip_pre20s.mp4"
    if clip_frames:
        _save_clip_mp4(clip_path, clip_frames, fps=10.0)

    gnss_obj = _normalize_gnss_snapshot(gnss_snapshot, eid, float(trigger_ts))

    primary_result = {
        "event_id": eid,
        "frame_id": primary_input.get("frame_id"),
        "ts": primary_input.get("ts"),
        "pos_sec": primary_input.get("pos_sec"),
        "latency_ms": primary_input.get("latency_ms"),
        "prompt_version": primary_input.get("prompt_version", "primary_unknown"),
        "model": {
            "engine": primary_input.get("engine"),
            "model_name": primary_input.get("model_name"),
            "infer_width": primary_input.get("infer_width"),
            "max_new_tokens": primary_input.get("max_new_tokens"),
        },
        "output": {
            "raw_text": primary_input.get("raw_text", primary_text or ""),
            "normalized_text": primary_text or primary_input.get("primary_text") or "",
            "event_type": event_type,
            "event_types": list(event_types or []),
        },
    }

    manifest = {
        "schema_version": "1.0.0",
        "event_id": eid,
        "session_id": session_id,
        "device_id": device_id,
        "cam_id": int(cam_id),
        "created_at": _now_iso_local(),
        "primary_event": event_type,
        "primary_event_candidates": list(event_types or []),
        "status": {
            "bundle_state": "primary_done",
            "primary_done": True,
            "secondary_done": False,
            "approval_state": "pending",
            "upload_state": "pending",
        },
        "has_assets": {
            "primary_frame": bool(primary_frame_path),
            "clip_pre20s": bool(clip_frames),
            "can_snapshot": True,
            "gnss_snapshot": True,
            "yolo_result": True,
            "secondary_result": False,
        },
    }

    upload_status = {
        "event_id": eid,
        "upload_state": "pending",
        "approval_state": "pending",
        "approval_reason": None,
        "approved_at": None,
        "uploaded_at": None,
        "retry_count": 0,
        "last_error": None,
        "s3_prefix": None,
        "ddb_written": False,
        "gnss_status": gnss_obj.get("status"),
        "gnss_lat": gnss_obj.get("lat"),
        "gnss_lon": gnss_obj.get("lon"),
        "location_available": (gnss_obj.get("lat") is not None and gnss_obj.get("lon") is not None),
    }

    _write_text(event_dir / "primary_result.txt", primary_text or "")
    _write_json(event_dir / "primary_result.json", primary_result)
    _write_json(event_dir / "yolo_result.json", yolo_detect or [])
    _write_json(event_dir / "can_snapshot.json", can_snapshot or {})
    _write_json(event_dir / "gnss_snapshot.json", gnss_obj)
    _write_json(event_dir / "bundle_manifest.json", manifest)
    _write_json(event_dir / "upload_status.json", upload_status)

    meta = {
        "event_id": eid,
        "event_type": event_type,
        "event_types": list(event_types or []),
        "session_id": session_id,
        "device_id": device_id,
        "cam_id": int(cam_id),
        "trigger_ts": float(trigger_ts),
        "save_root": str(root),
        "event_dir": str(event_dir),
        "clip_path": str(clip_path) if clip_frames else None,

        "primary_frame_path": primary_frame_path,
        "primary_frame_id": primary_input.get("frame_id"),
        "primary_ts": primary_input.get("ts"),
        "primary_pos_sec": primary_input.get("pos_sec"),
        "primary_latency_ms": primary_input.get("latency_ms"),
        "primary_text": primary_text or primary_input.get("primary_text") or "",

        "sampled_frame_paths": [],
        "yolo_detect": yolo_detect or [],
        "can_snapshot": can_snapshot or {},
        "gnss_snapshot": gnss_obj,
        "buffer_summary": buffer.summary() if buffer is not None else {},
    }
    _write_json(event_dir / "metadata.json", meta)

    return {
        "event_id": eid,
        "event_type": event_type,
        "event_types": list(event_types or []),
        "session_id": session_id,
        "device_id": device_id,
        "event_dir": str(event_dir),
        "clip_path": str(clip_path) if clip_frames else None,
        "primary_frame_path": primary_frame_path,
        "sampled_frame_paths": [],
    }
