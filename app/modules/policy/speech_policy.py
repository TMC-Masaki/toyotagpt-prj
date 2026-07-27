from __future__ import annotations

from typing import Any


HIGH_RISK_OBJECTS = {
    "person", "bicycle", "motorcycle", "car", "bus", "truck"
}

MID_RISK_KEYWORDS = [
    "危険", "注意", "飛び出し", "接近", "衝突", "障害物",
    "工事", "事故", "落下物", "陥没"
]


def _parse_speed_kmh(speed_text: str | None) -> float:
    if not speed_text:
        return 0.0
    s = str(speed_text).strip().lower().replace("km/h", "").strip()
    try:
        return float(s)
    except Exception:
        return 0.0


def _has_high_risk_object(yolo_detect: list[str] | None) -> bool:
    if not isinstance(yolo_detect, list):
        return False
    names = {str(x).strip().lower() for x in yolo_detect}
    return any(x in names for x in HIGH_RISK_OBJECTS)


def _has_mid_risk_keyword(vlm_text: str | None) -> bool:
    txt = str(vlm_text or "").strip()
    if not txt:
        return False
    return any(k in txt for k in MID_RISK_KEYWORDS)


def evaluate_speech_policy(
    *,
    yolo_detect: list[str] | None,
    vlm_text: str | None,
    vehicle_speed_text: str | None,
    shift: str | None,
) -> dict[str, Any]:
    speed = _parse_speed_kmh(vehicle_speed_text)
    shift_s = str(shift or "").upper().strip()

    has_obj = _has_high_risk_object(yolo_detect)
    has_kw = _has_mid_risk_keyword(vlm_text)

    # 停車レンジは基本的に危険度を下げる
    stopped_like = shift_s in {"P", "N"} or speed < 1.0

    risk_level = "LOW"
    speak_interval_sec = 10.0
    reason = "default"

    if has_obj and speed >= 30.0 and not stopped_like:
        risk_level = "HIGH"
        speak_interval_sec = 2.0
        reason = "high_risk_object_and_speed"
    elif has_obj and speed >= 1.0 and not stopped_like:
        risk_level = "MID"
        speak_interval_sec = 5.0
        reason = "risk_object_detected"
    elif has_kw:
        risk_level = "MID"
        speak_interval_sec = 5.0
        reason = "vlm_keyword"
    else:
        risk_level = "LOW"
        speak_interval_sec = 10.0
        reason = "low_risk"

    return {
        "risk_level": risk_level,
        "speak_interval_sec": speak_interval_sec,
        "speak_reason": reason,
    }
