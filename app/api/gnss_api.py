from fastapi import APIRouter
from app.runtime.bus import STATE

router = APIRouter()

@router.get("/gnss/latest")
def gnss_latest():
    with STATE.lock:
        return STATE.latest_gnss.get(0)

@router.get("/gnss/track")
def gnss_track():
    with STATE.lock:
        return STATE.gnss_track.get(0, [])

@router.get("/gnss/status")
def gnss_status():
    with STATE.lock:
        latest = STATE.latest_gnss.get(0)
        return {
            "ok": latest is not None,
            "latest": latest,
            "last_ts": STATE.latest_gnss_ts.get(0),
            "error": STATE.latest_gnss_error.get(0),
            "track_len": len(STATE.gnss_track.get(0, []) or []),
        }
