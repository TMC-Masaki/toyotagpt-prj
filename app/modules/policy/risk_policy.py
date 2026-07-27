from __future__ import annotations

from typing import Any


VULNERABLE_OBJECTS = {"person", "bicycle", "motorcycle"}
LARGE_VEHICLES = {"truck", "bus"}
ROAD_VEHICLES = {"car", "bus", "truck", "motorcycle", "bicycle"}

BLINDSPOT_KEYWORDS = [
    "死角", "見通し", "見えにく", "陰", "遮", "停車車両", "駐車車両",
    "工事", "渋滞末尾", "合流", "横断", "飛び出し"
]

PREDICTIVE_KEYWORDS = [
    "飛び出し", "横断", "接近", "衝突", "急", "注意", "減速", "回避",
    "見落とし", "認知", "予測", "不明"
]


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(x)))


def _parse_speed_kmh(speed_text: str | None) -> float:
    if not speed_text:
        return 0.0
    s = str(speed_text).strip().lower().replace("km/h", "").strip()
    try:
        return float(s)
    except Exception:
        return 0.0


def _norm_names(yolo_detect: list[str] | None) -> list[str]:
    if not isinstance(yolo_detect, list):
        return []
    return [str(x).strip().lower() for x in yolo_detect if str(x).strip()]


def compute_scene_complexity(yolo_detect: list[str] | None) -> float:
    names = _norm_names(yolo_detect)
    if not names:
        return 0.0

    uniq = set(names)
    count = len(names)
    kind_count = len(uniq)
    has_large = any(x in uniq for x in LARGE_VEHICLES)

    score = 0.0

    # 数
    if count >= 1:
        score += 0.20
    if count >= 3:
        score += 0.20
    if count >= 5:
        score += 0.20

    # 種類
    if kind_count >= 2:
        score += 0.15
    if kind_count >= 3:
        score += 0.15

    # 大型車両
    if has_large:
        score += 0.10

    return _clamp(score)


def compute_vru_load(yolo_detect: list[str] | None) -> float:
    names = _norm_names(yolo_detect)
    if not names:
        return 0.0

    person_count = sum(1 for x in names if x == "person")
    bicycle_count = sum(1 for x in names if x == "bicycle")
    motorcycle_count = sum(1 for x in names if x == "motorcycle")

    person_score = 0.0
    if person_count >= 1:
        person_score = 0.50
    if person_count >= 2:
        person_score = 0.65
    if person_count >= 3:
        person_score = 0.80
    if person_count >= 4:
        person_score = 0.95

    bicycle_score = 0.0
    if bicycle_count >= 1:
        bicycle_score = 0.20
    if bicycle_count >= 2:
        bicycle_score = 0.35
    if bicycle_count >= 3:
        bicycle_score = 0.50

    motorcycle_score = 0.0
    if motorcycle_count >= 1:
        motorcycle_score = 0.15
    if motorcycle_count >= 2:
        motorcycle_score = 0.25
    if motorcycle_count >= 3:
        motorcycle_score = 0.35

    score = max(person_score, bicycle_score, motorcycle_score)
    return _clamp(score)


def compute_blindspot_predictive_load(
    vlm_text: str | None,
    vlm_risk_event_types: list[str] | None = None,
) -> tuple[float, str]:
    event_types = [str(x).strip() for x in (vlm_risk_event_types or []) if str(x).strip()]

    if "blind_spot" in event_types:
        return 0.85, "vlm_blind_spot_event"

    txt = str(vlm_text or "").strip()
    if not txt:
        return 0.0, "no_vlm_hint"

    lowered = txt.lower()
    if "blind_spot" in lowered:
        return 0.85, "vlm_blind_spot_text"

    return 0.0, "no_blindspot_hint"


def compute_base_speed(speed_kmh: float) -> float:
    if speed_kmh < 10:
        return 0.0
    if speed_kmh < 20:
        return 0.2
    if speed_kmh < 30:
        return 0.4
    if speed_kmh < 40:
        return 0.6
    if speed_kmh < 60:
        return 0.8
    return 1.0


def evaluate_risk(
    *,
    yolo_detect: list[str] | None,
    vlm_text: str | None,
    vlm_risk_event_types: list[str] | None = None,
    vehicle_speed_text: str | None,
    shift: str | None,
    scene_complexity_weight: float = 0.35,
    vru_weight: float = 0.25,
    blindspot_weight: float = 0.20,
    speed_mismatch_weight: float = 0.20,
    mid_threshold: float = 35.0,
    high_threshold: float = 55.0,
) -> dict[str, Any]:
    speed = _parse_speed_kmh(vehicle_speed_text)
    shift_s = str(shift or "").upper().strip()

    scene_complexity = compute_scene_complexity(yolo_detect)
    vru_load = compute_vru_load(yolo_detect)
    blindspot_predictive_load, blind_reason = compute_blindspot_predictive_load(vlm_text, vlm_risk_event_types)

    base_speed = compute_base_speed(speed)

    stopped_like = shift_s in {"P", "N"} or speed < 1.0

    # 場面に対して速すぎるか
    speed_context = max(scene_complexity, vru_load, blindspot_predictive_load)
    speed_mismatch = 0.0 if stopped_like else _clamp(base_speed * speed_context)

    # 重みは UI から触れるので、合計を自動正規化する
    w_scene = max(0.0, float(scene_complexity_weight))
    w_vru = max(0.0, float(vru_weight))
    w_blind = max(0.0, float(blindspot_weight))
    w_speed = max(0.0, float(speed_mismatch_weight))

    w_sum = w_scene + w_vru + w_blind + w_speed
    if w_sum <= 0.0:
        w_scene, w_vru, w_blind, w_speed = 0.35, 0.25, 0.20, 0.20
        w_sum = 1.0

    w_scene /= w_sum
    w_vru /= w_sum
    w_blind /= w_sum
    w_speed /= w_sum

    # 統合スコア
    risk_score = 100.0 * (
        w_scene * scene_complexity +
        w_vru * vru_load +
        w_blind * blindspot_predictive_load +
        w_speed * speed_mismatch
    )

    if stopped_like and risk_score > 35.0:
        risk_score *= 0.7

    mid_th = max(0.0, float(mid_threshold))
    high_th = max(0.0, float(high_threshold))
    if high_th < mid_th:
        mid_th, high_th = high_th, mid_th

    if risk_score >= high_th:
        risk_level = "HIGH"
        speak_interval_sec = 2.0
    elif risk_score >= mid_th:
        risk_level = "MID"
        speak_interval_sec = 5.0
    else:
        risk_level = "LOW"
        speak_interval_sec = 10.0

    # 一番効いた因子を理由にする
    factor_pairs = {
        "scene_complexity": scene_complexity,
        "vru_load": vru_load,
        "blindspot_predictive_load": blindspot_predictive_load,
        "speed_mismatch": speed_mismatch,
    }
    top_factor = max(factor_pairs.items(), key=lambda kv: kv[1])[0]
    reason = top_factor
    if top_factor == "blindspot_predictive_load":
        reason = blind_reason

    return {
        "risk_level": risk_level,
        "risk_score": round(risk_score, 1),
        "risk_reason": reason,
        "speak_interval_sec": speak_interval_sec,

        "scene_complexity": round(scene_complexity, 3),
        "vru_load": round(vru_load, 3),
        "blindspot_predictive_load": round(blindspot_predictive_load, 3),
        "speed_mismatch": round(speed_mismatch, 3),

        "speed_kmh": round(speed, 1),
        "shift": shift_s,
        "stopped_like": 1 if stopped_like else 0,

        "scene_complexity_weight": round(w_scene, 3),
        "vru_weight": round(w_vru, 3),
        "blindspot_weight": round(w_blind, 3),
        "speed_mismatch_weight": round(w_speed, 3),

        "mid_threshold": round(mid_th, 2),
        "high_threshold": round(high_th, 2),
    }
