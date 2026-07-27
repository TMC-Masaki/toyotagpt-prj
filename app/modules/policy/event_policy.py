from __future__ import annotations

from typing import Any

SHARE_VALUE_EVENT_KEYS = [
    "road_depression",
    "fallen_object",
    "road_work",
    "traffic_jam",
    "accident",
]

VLM_RISK_EVENT_KEYS = [
    "blind_spot",
    "pedestrian_attention",
    "intersection_complexity",
]

ALLOWED_EVENT_KEYS = SHARE_VALUE_EVENT_KEYS + VLM_RISK_EVENT_KEYS
ALLOWED_EVENT_KEY_SET = set(ALLOWED_EVENT_KEYS)
SHARE_VALUE_EVENT_KEY_SET = set(SHARE_VALUE_EVENT_KEYS)
VLM_RISK_EVENT_KEY_SET = set(VLM_RISK_EVENT_KEYS)


def _normalize_event_text(txt: str) -> str:
    s = str(txt or "").strip()

    if "検出Event" in s:
        for line in s.splitlines():
            line = line.strip()
            if line.startswith("検出Event"):
                _, _, rhs = line.partition("：")
                if not rhs:
                    _, _, rhs = line.partition(":")
                s = rhs.strip()
                break

    return s.strip()


def _parse_event_keys(txt: str) -> list[str]:
    s = _normalize_event_text(txt)

    if not s:
        return []

    if s.lower() == "none":
        return []

    keys: list[str] = []
    for part in s.split(","):
        k = str(part).strip()
        if not k:
            continue
        if k == "none":
            continue
        if k in ALLOWED_EVENT_KEY_SET and k not in keys:
            keys.append(k)
    return keys


def evaluate_event(
    *,
    vlm_text: str | None,
) -> dict[str, Any]:
    txt = str(vlm_text or "").strip()
    if not txt:
        return {
            "event_type": "none",
            "event_types": [],
            "share_value_event_types": [],
            "vlm_risk_event_types": [],
            "event_confidence": 0.0,
            "event_reason": "no_vlm_text",
        }

    keys = _parse_event_keys(txt)
    share_value_event_types = [k for k in keys if k in SHARE_VALUE_EVENT_KEY_SET]
    vlm_risk_event_types = [k for k in keys if k in VLM_RISK_EVENT_KEY_SET]

    if not keys:
        return {
            "event_type": "none",
            "event_types": [],
            "share_value_event_types": [],
            "vlm_risk_event_types": [],
            "event_confidence": 0.0,
            "event_reason": "none_or_no_valid_key",
        }

    if share_value_event_types:
        return {
            "event_type": share_value_event_types[0],
            "event_types": share_value_event_types,
            "share_value_event_types": share_value_event_types,
            "vlm_risk_event_types": vlm_risk_event_types,
            "event_confidence": 1.0,
            "event_reason": "parsed_share_value_keys",
        }

    return {
        "event_type": "none",
        "event_types": [],
        "share_value_event_types": [],
        "vlm_risk_event_types": vlm_risk_event_types,
        "event_confidence": 1.0 if vlm_risk_event_types else 0.0,
        "event_reason": "risk_only_or_no_share_value_key",
    }
