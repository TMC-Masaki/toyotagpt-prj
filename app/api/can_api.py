from fastapi import APIRouter
from app.runtime.bus import STATE

router = APIRouter()


@router.get("/can/status")
def can_status():
    with STATE.lock:
        return {
            "status": (STATE.latest_can_status.get(0)),
            "ts": (STATE.latest_can_ts.get(0)),
            "error": (STATE.latest_can_error.get(0)),
            "iface": (STATE.latest_can_iface.get(0)),
            "rx_count": (STATE.latest_can_rx_count.get(0, 0)),
            "speed_kmh": (STATE.latest_vehicle_speed.get(0)),
            "shift": (STATE.latest_shift.get(0)),
            "accel_xyz": (STATE.latest_accel_xyz.get(0)),
            "pedal": (STATE.latest_pedal.get(0)),
            "steering_rate": (STATE.latest_steering_rate.get(0)),
        }


@router.get("/can/signals")
def can_signals():
    with STATE.lock:
        return STATE.latest_can_signals.get(0, {})


@router.get("/can/frame")
def can_frame():
    with STATE.lock:
        return STATE.latest_can_frame.get(0, {})
