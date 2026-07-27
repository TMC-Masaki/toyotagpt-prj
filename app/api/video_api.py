from fastapi import APIRouter, HTTPException, Query
import cv2

from app.core.config import load_config
from app.modules.pipeline import inference_pipeline as ip

router = APIRouter()

@router.get("/video/status")
def video_status():
    cfg = load_config()
    itype = (cfg.get("input", {}) or {}).get("type", "")
    if itype == "image_dir":
        inp = cfg.get("input", {}) or {}
        return {
            "ok": True,
            "supported": True,
            "input_type": "image_dir",
            "path": inp.get("path"),
            "fps": inp.get("fps", 29.97),
            "loop": inp.get("loop", False),
        }

    if itype != "video_file":
        return {"ok": True, "supported": False, "reason": "input is not video_file"}

    # IMPORTANT:
    # /video/status must NOT create or start a source.
    # It should only inspect an already-running source.
    src = getattr(ip, "_video_source", None)

    if src is None:
        return {"ok": True, "supported": True, "ready": False, "pos_sec": None, "duration_sec": None, "fps": None, "frame_count": None}

    # 1) Prefer source-maintained position (most reliable)
    fn = getattr(src, "get_pos_sec", None)
    if callable(fn):
        try:
            pos = float(fn())
        except Exception:
            pos = None
    else:
        pos = None

    # duration/fps/frame_count (best-effort)
    dur = 0.0
    dur_fn = getattr(src, "get_duration_sec", None)
    if callable(dur_fn):
        try:
            dur = float(dur_fn())
        except Exception:
            dur = 0.0

    fps = float(getattr(src, "fps", 0.0) or 0.0)

    frame_count = None
    cap = getattr(src, "cap", None)
    if cap is not None:
        try:
            fc = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
            if fc > 0:
                frame_count = int(fc)
        except Exception:
            pass

    return {
        "ok": True,
        "supported": True,
        "ready": True,
        "pos_sec": pos,
        "duration_sec": dur,
        "fps": fps,
        "frame_count": frame_count,
    }

@router.get("/video/seek")
@router.post("/video/seek")
def video_seek(pos_sec: float = Query(..., description="Seek position in seconds")):
    cfg = load_config()
    itype = (cfg.get("input", {}) or {}).get("type", "")
    if itype != "video_file":
        raise HTTPException(status_code=400, detail="input is not video_file")

    # ✅ 必ず両方定義する
    src_inf = getattr(ip, "_video_source", None)
    src_pre = getattr(ip, "_preview_source", None)

    if src_inf is None and src_pre is None:
        return {"ok": True, "applied": False, "reason": "source not initialized yet"}

    applied = False
    errors = []

    for src in (src_pre, src_inf):
        if src is None:
            continue
        seek = getattr(src, "seek_sec", None)
        if not callable(seek):
            seek = getattr(src, "seek", None)
        if callable(seek):
            try:
                seek(float(pos_sec))
                applied = True
            except Exception as e:
                errors.append(str(e))

    if not applied:
        raise HTTPException(status_code=500, detail=f"seek failed: {errors[0] if errors else 'unknown'}")

    return {"ok": True, "applied": True, "pos_sec": float(pos_sec)}
