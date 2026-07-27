import os
import time
from pathlib import Path
import subprocess
from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel
import cv2

from app.core.config import load_config, save_config
from app.modules.pipeline import inference_pipeline as ip
from app.modules.pipeline.scheduler import Scheduler
from app.runtime.bus import STATE
from app.modules.policy.risk_policy import evaluate_risk

from app.modules.policy.event_policy import evaluate_event

VLM_RISK_SPEECH_MAP = {
    "blind_spot": "見通しが悪くなっています。速度に注意しましょう",
    "pedestrian_attention": "歩行者の動きに注意しましょう",
    "intersection_complexity": "交通環境が複雑になっています。速度に注意しましょう",
}

RULE_RISK_HIGH_SPEECH_MAP = {
    "scene_complexity": "危険、交通環境に注意しましょう",
    "vru_load": "危険、歩行者や自転車に注意しましょう",
    "blindspot_predictive": "危険、見通しが悪くなっています",
}

RULE_RISK_MID_SPEECH_MAP = {
    "scene_complexity": "道路環境が複雑になってきました。速度に注意しましょう",
    "vru_load": "歩行者や自転車が多くなってきました。速度に注意しましょう",
    "blindspot_predictive": "この先、見通しが悪くなっています。速度に注意しましょう",
}


def _safe_float(v, default=0.0):
    try:
        if v is None:
            return float(default)
        return float(v)
    except Exception:
        return float(default)


def _build_speech_payload(*, risk: dict, event: dict) -> dict:
    risk_level = str((risk or {}).get("risk_level") or "").upper()
    scene_complexity = _safe_float((risk or {}).get("scene_complexity"), 0.0)
    vru_load = _safe_float((risk or {}).get("vru_load"), 0.0)
    blindspot_predictive = _safe_float((risk or {}).get("blindspot_predictive_load"), 0.0)
    vlm_risk_event_types = list((event or {}).get("vlm_risk_event_types") or [])

    text = ""
    category = ""
    repeat_sec = None
    speech_key = ""

    dominant = {
        "scene_complexity": scene_complexity,
        "vru_load": vru_load,
        "blindspot_predictive": blindspot_predictive,
    }
    best_key = max(dominant, key=dominant.get) if dominant else ""
    best_val = dominant.get(best_key, 0.0)

    if risk_level == "HIGH" and best_val > 0.0:
        text = RULE_RISK_HIGH_SPEECH_MAP.get(best_key, "")
        category = "rule_risk_high"
        repeat_sec = 3
        speech_key = f"{category}:{best_key}"
    elif risk_level == "MID" and best_val > 0.0:
        text = RULE_RISK_MID_SPEECH_MAP.get(best_key, "")
        category = "rule_risk_mid"
        repeat_sec = None
        speech_key = f"{category}:{best_key}"
    elif risk_level in ("MID", "HIGH") and vlm_risk_event_types:
        for k in vlm_risk_event_types:
            if k in VLM_RISK_SPEECH_MAP:
                text = VLM_RISK_SPEECH_MAP[k]
                category = "vlm_risk"
                repeat_sec = None
                speech_key = f"{category}:{k}"
                break

    return {
        "speech_text": text,
        "speech_category": category,
        "speech_repeat_sec": repeat_sec,
        "speech_key": speech_key,
    }

from app.runtime.eval_log import summarize_dets

router = APIRouter()
_scheduler = Scheduler()


def _load_latest_secondary_from_disk():
    try:
        root = Path("/logs/events")
        if not root.exists():
            return None
        dirs = sorted([x for x in root.iterdir() if x.is_dir()])
        if not dirs:
            return None
        for latest in reversed(dirs):
            p = latest / "secondary_result.json"
            if not p.exists():
                continue
            import json
            obj = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(obj, dict):
                continue
            return {
                "event_id": obj.get("event_id"),
                "event_type": obj.get("event_type"),
                "event_types": obj.get("event_types") or [],
                "event_dir": str(latest),
                "text": obj.get("text") or "",
                "latency_ms": obj.get("latency_ms"),
            }
        return None
    except Exception:
        return None



def _safe_is_alive(t) -> bool:
    try:
        return bool(t and t.is_alive())
    except Exception:
        return False


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/config")
def get_config():
    return load_config()


class CanMockUpdate(BaseModel):
    vehicle_speed: float | None = None
    shift: str | None = None
    accel_x: float | None = None
    accel_y: float | None = None
    accel_z: float | None = None
    pedal_accel: float | None = None
    pedal_brake: float | None = None
    steering_rate: float | None = None
    can_status: str | None = None
    can_error: str | None = None


class ConfigUpdate(BaseModel):
    # YOLO
    yolo_enabled: bool | None = None
    yolo_model_name: str | None = None
    yolo_conf: float | None = None
    yolo_iou: float | None = None
    yolo_imgsz: int | None = None
    yolo_preview_hz: float | None = None

    # VLM
    vlm_engine: str | None = None
    vlm_model_name: str | None = None
    vlm_max_new_tokens: int | None = None
    vlm_infer_width: int | None = None
    prompt: str | None = None

    # input
    input_type: str | None = None
    input_path: str | None = None
    camera_index: int | None = None
    input_device: str | None = None
    input_width: int | None = None
    input_height: int | None = None
    input_fps: int | None = None

    # pipeline
    pipeline_interval_sec: float | None = None
    vlm_emit_interval_sec: float | None = None

    # risk
    risk_scene_complexity_weight: float | None = None
    risk_vru_weight: float | None = None
    risk_blindspot_weight: float | None = None
    risk_speed_mismatch_weight: float | None = None
    risk_mid_threshold: float | None = None
    risk_high_threshold: float | None = None

    # can
    can_mode: str | None = None
    can_dummy_vehicle_speed: float | None = None
    can_dummy_shift: str | None = None
    can_dummy_accel_x: float | None = None
    can_dummy_accel_y: float | None = None
    can_dummy_accel_z: float | None = None
    can_dummy_pedal_accel: float | None = None
    can_dummy_pedal_brake: float | None = None
    can_dummy_steering_rate: float | None = None

    # speech
    speech_enabled: bool | None = None
    speech_min_interval_sec: float | None = None
    speech_detail: str | None = None
    # evaluation
    evaluation_overlay_enabled: bool | None = None
    evaluation_log_enabled: bool | None = None

    # upload
    upload_enabled: bool | None = None


@router.post("/config")
def update_config(req: ConfigUpdate):
    cfg = load_config()
    need_reset_source = False

    # pipeline
    if req.pipeline_interval_sec is not None:
        cfg.setdefault("pipeline", {})
        cfg["pipeline"]["interval_sec"] = float(req.pipeline_interval_sec)

    # vlm
    if req.prompt is not None:
        cfg.setdefault("vlm", {})
        cfg["vlm"]["prompt"] = req.prompt
    if req.vlm_engine is not None:
        cfg.setdefault("vlm", {})
        cfg["vlm"]["engine"] = str(req.vlm_engine)
    if req.vlm_model_name is not None:
        cfg.setdefault("vlm", {})
        cfg["vlm"]["model_name"] = str(req.vlm_model_name)

    if req.vlm_emit_interval_sec is not None:
        cfg.setdefault("vlm", {})
        cfg["vlm"]["emit_interval_sec"] = float(req.vlm_emit_interval_sec)
    if req.vlm_max_new_tokens is not None:
        cfg.setdefault("vlm", {})
        cfg["vlm"]["max_new_tokens"] = int(req.vlm_max_new_tokens)

    if req.vlm_infer_width is not None:
        cfg.setdefault("vlm", {})
        cfg["vlm"]["infer_width"] = int(req.vlm_infer_width)

    # input
    if req.input_type is not None:
        cfg.setdefault("input", {})
        cfg["input"]["type"] = str(req.input_type)
        need_reset_source = True
    if req.input_path is not None:
        cfg.setdefault("input", {})
        cfg["input"]["path"] = str(req.input_path)
        need_reset_source = True
    if req.camera_index is not None:
        cfg.setdefault("input", {})
        cam_idx = int(req.camera_index)
        cfg["input"]["camera_index"] = cam_idx
        need_reset_source = True

    if req.input_device is not None:
        cfg.setdefault("input", {})
        dev = str(req.input_device).strip()
        cfg["input"]["device"] = dev if dev else None
        need_reset_source = True

    if req.input_width is not None:
        cfg.setdefault("input", {})
        cfg["input"]["width"] = int(req.input_width)
        need_reset_source = True

    if req.input_height is not None:
        cfg.setdefault("input", {})
        cfg["input"]["height"] = int(req.input_height)
        need_reset_source = True

    if req.input_fps is not None:
        cfg.setdefault("input", {})
        cfg["input"]["fps"] = int(req.input_fps)
        need_reset_source = True

    # yolo
    if req.yolo_enabled is not None:
        cfg.setdefault("yolo", {})
        cfg["yolo"]["enabled"] = bool(req.yolo_enabled)
    if req.yolo_model_name is not None:
        cfg.setdefault("yolo", {})
        cfg["yolo"]["model_name"] = str(req.yolo_model_name)
    if req.yolo_conf is not None:
        cfg.setdefault("yolo", {})
        cfg["yolo"]["conf"] = float(req.yolo_conf)
    if req.yolo_iou is not None:
        cfg.setdefault("yolo", {})
        cfg["yolo"]["iou"] = float(req.yolo_iou)
    if req.yolo_imgsz is not None:
        cfg.setdefault("yolo", {})
        cfg["yolo"]["imgsz"] = int(req.yolo_imgsz)
    if req.yolo_preview_hz is not None:
        cfg.setdefault("yolo", {})
        cfg["yolo"]["preview_hz"] = float(req.yolo_preview_hz)

    # risk
    if req.risk_scene_complexity_weight is not None:
        cfg.setdefault("risk", {})
        cfg["risk"]["scene_complexity_weight"] = float(req.risk_scene_complexity_weight)
    if req.risk_vru_weight is not None:
        cfg.setdefault("risk", {})
        cfg["risk"]["vru_weight"] = float(req.risk_vru_weight)
    if req.risk_blindspot_weight is not None:
        cfg.setdefault("risk", {})
        cfg["risk"]["blindspot_weight"] = float(req.risk_blindspot_weight)
    if req.risk_speed_mismatch_weight is not None:
        cfg.setdefault("risk", {})
        cfg["risk"]["speed_mismatch_weight"] = float(req.risk_speed_mismatch_weight)
    if req.risk_mid_threshold is not None:
        cfg.setdefault("risk", {})
        cfg["risk"]["mid_threshold"] = float(req.risk_mid_threshold)
    if req.risk_high_threshold is not None:
        cfg.setdefault("risk", {})
        cfg["risk"]["high_threshold"] = float(req.risk_high_threshold)

    # can
    if req.can_mode is not None:
        cfg.setdefault("can", {})
        cfg["can"]["mode"] = str(req.can_mode)
    if any(v is not None for v in [
        req.can_dummy_vehicle_speed, req.can_dummy_shift,
        req.can_dummy_accel_x, req.can_dummy_accel_y, req.can_dummy_accel_z,
        req.can_dummy_pedal_accel, req.can_dummy_pedal_brake, req.can_dummy_steering_rate
    ]):
        cfg.setdefault("can", {})
        cfg.setdefault("can", {}).setdefault("dummy", {})
        if req.can_dummy_vehicle_speed is not None:
            cfg["can"]["dummy"]["vehicle_speed"] = float(req.can_dummy_vehicle_speed)
        if req.can_dummy_shift is not None:
            cfg["can"]["dummy"]["shift"] = str(req.can_dummy_shift)
        if req.can_dummy_accel_x is not None:
            cfg["can"]["dummy"]["accel_x"] = float(req.can_dummy_accel_x)
        if req.can_dummy_accel_y is not None:
            cfg["can"]["dummy"]["accel_y"] = float(req.can_dummy_accel_y)
        if req.can_dummy_accel_z is not None:
            cfg["can"]["dummy"]["accel_z"] = float(req.can_dummy_accel_z)
        if req.can_dummy_pedal_accel is not None:
            cfg["can"]["dummy"]["pedal_accel"] = float(req.can_dummy_pedal_accel)
        if req.can_dummy_pedal_brake is not None:
            cfg["can"]["dummy"]["pedal_brake"] = float(req.can_dummy_pedal_brake)
        if req.can_dummy_steering_rate is not None:
            cfg["can"]["dummy"]["steering_rate"] = float(req.can_dummy_steering_rate)

    # speech
    if req.speech_enabled is not None:
        cfg.setdefault("speech", {})
        cfg["speech"]["enabled"] = bool(req.speech_enabled)
    if req.speech_min_interval_sec is not None:
        cfg.setdefault("speech", {})
        cfg["speech"]["min_interval_sec"] = float(req.speech_min_interval_sec)
    if req.speech_detail is not None:
        cfg.setdefault("speech", {})
        cfg["speech"]["detail"] = str(req.speech_detail)

    # evaluation
    if req.evaluation_overlay_enabled is not None:
        cfg.setdefault("evaluation", {})
        cfg["evaluation"]["overlay_enabled"] = bool(req.evaluation_overlay_enabled)
    if req.evaluation_log_enabled is not None:
        cfg.setdefault("evaluation", {})
        cfg["evaluation"]["log_enabled"] = bool(req.evaluation_log_enabled)

    # upload
    if req.upload_enabled is not None:
        cfg.setdefault("upload", {})
        cfg["upload"]["enabled"] = bool(req.upload_enabled)

    save_config(cfg)

    # 入力設定を変えたときだけソースをリセット
    if need_reset_source:
        try:
            ip.reset_source()
        except Exception:
            pass

    return {"status": "updated", "config": cfg}


@router.post("/debug/can/mock")
def debug_can_mock(req: CanMockUpdate):
    now = time.time()
    with STATE.lock:
        if req.can_status is not None:
            STATE.latest_can_status[0] = str(req.can_status)
        else:
            STATE.latest_can_status[0] = "OK"

        STATE.latest_can_ts[0] = now

        if req.can_error is not None:
            STATE.latest_can_error[0] = str(req.can_error)
        else:
            STATE.latest_can_error[0] = None

        if req.vehicle_speed is not None:
            STATE.latest_vehicle_speed[0] = float(req.vehicle_speed)

        if req.shift is not None:
            STATE.latest_shift[0] = str(req.shift)

        accel = dict((getattr(STATE, "latest_accel_xyz", {}) or {}).get(0) or {})
        if req.accel_x is not None:
            accel["x"] = float(req.accel_x)
        if req.accel_y is not None:
            accel["y"] = float(req.accel_y)
        if req.accel_z is not None:
            accel["z"] = float(req.accel_z)
        if accel:
            STATE.latest_accel_xyz[0] = accel

        pedal = dict((getattr(STATE, "latest_pedal", {}) or {}).get(0) or {})
        if req.pedal_accel is not None:
            pedal["accel"] = float(req.pedal_accel)
        if req.pedal_brake is not None:
            pedal["brake"] = float(req.pedal_brake)
        if pedal:
            STATE.latest_pedal[0] = pedal

        if req.steering_rate is not None:
            STATE.latest_steering_rate[0] = float(req.steering_rate)

    return {"ok": True, "ts": now}


@router.post("/scheduler/start")
def start_scheduler():
    _scheduler.start()
    return {"ok": True, "running": _scheduler.is_running()}


@router.post("/scheduler/stop")
def stop_scheduler():
    _scheduler.stop()
    return {"ok": True, "running": _scheduler.is_running()}


@router.get("/scheduler/status")
def scheduler_status():
    return {"running": _scheduler.is_running()}


@router.get("/latest")
def latest():
    with STATE.lock:
        out = STATE.latest_vlm.get(0)
        err = STATE.latest_error.get(0)
        dets = STATE.latest_dets.get(0)
        ts = STATE.latest_ts.get(0)

    if err:
        return {"ok": False, "message": err}
    if out is None and dets is None:
        return {"ok": False, "message": "no result yet"}
    return {"ok": True, "ts": ts, "vlm": out, "dets": dets}


@router.get("/frame.jpg")
def frame_jpg():
    with STATE.lock:
        frame = STATE.latest_frame_bgr.get(0)

    if frame is None:
        return Response(content=b"NO_FRAME", media_type="text/plain", status_code=404)

    ok, buf = cv2.imencode(".jpg", frame)
    if not ok:
        return Response(content=b"ENCODE_FAIL", media_type="text/plain", status_code=500)

    return Response(content=buf.tobytes(), media_type="image/jpeg")


@router.post("/run_once")
def api_run_once():
    return ip.run_once()


@router.get("/debug/scheduler")
def debug_scheduler():
    v = getattr(_scheduler, "_vision", None)
    m = getattr(_scheduler, "_vlm", None)
    with STATE.lock:
        ts = STATE.latest_ts.get(0)
        err = STATE.latest_error.get(0)
        has = STATE.latest_frame_bgr.get(0) is not None
    return {
        "running": _scheduler.is_running(),
        "vision_alive": _safe_is_alive(v),
        "vlm_alive": _safe_is_alive(m),
        "latest_ts": ts,
        "has_frame": has,
        "latest_error": err,
        "vision_obj": str(type(v)) if v else None,
        "vlm_obj": str(type(m)) if m else None,
    }

@router.get("/debug/state")
def debug_state():
    with STATE.lock:
        le = STATE.latest_error
        lt = STATE.latest_ts
        lf = STATE.latest_frame_bgr
        lv = STATE.latest_vlm
        ld = STATE.latest_dets
        lfid = STATE.latest_frame_id

        def keys(x):
            return list(getattr(x, "keys", lambda: [])())

        return {
            "ids": {
                "latest_error": id(le),
                "latest_ts": id(lt),
                "latest_frame_bgr": id(lf),
                "latest_vlm": id(lv),
                "latest_dets": id(ld),
                "latest_frame_id": id(lfid),
            },
            "keys": {
                "latest_error": keys(le),
                "latest_ts": keys(lt),
                "latest_vlm": keys(lv),
                "latest_dets": keys(ld),
                "latest_frame_id": keys(lfid),
            },
            "vals": {
                "latest_error": le.get(0) if hasattr(le, "get") else None,
                "latest_ts": lt.get(0) if hasattr(lt, "get") else None,
                "latest_frame_id": lfid.get(0) if hasattr(lfid, "get") else None,
                "has_vlm": (lv.get(0) is not None) if hasattr(lv, "get") else False,
                "has_frame": (lf.get(0) is not None) if hasattr(lf, "get") else False,
                "has_dets": (ld.get(0) is not None) if hasattr(ld, "get") else False,
            },
        }
@router.get("/ui/state")
def ui_state():
    secondary_result = None
    secondary_status = None
    secondary_error = None
    cfg = load_config()

    # input 表示
    itype = (cfg.get("input", {}) or {}).get("type", "video_file")
    if itype == "camera":
        cam_idx = int((cfg.get("input", {}) or {}).get("camera_index", 0) or 0)
        source = "Camera"
        display = f"Camera{cam_idx+1}"
    else:
        source = "Movie"
        p = (cfg.get("input", {}) or {}).get("path", "") or ""
        display = os.path.basename(p) if p else "(no file)"

    # scheduler elapsed
    started_at = getattr(_scheduler, "_started_at", None)
    if started_at:
        api_time = max(0.0, time.time() - float(started_at))
    else:
        api_time = 0.0

    # latest values
    with STATE.lock:
        secondary_result = (getattr(STATE, "latest_secondary_result", {}) or {}).get(0)
        secondary_status = (getattr(STATE, "latest_secondary_status", {}) or {}).get(0)
        secondary_error = (getattr(STATE, "latest_secondary_error", {}) or {}).get(0)
        vlm = STATE.latest_vlm.get(0)
        dets = STATE.latest_dets.get(0)
        vlm_busy = int((getattr(STATE, "latest_vlm_busy", {}) or {}).get(0, 0) or 0)
        yolo_busy = int((getattr(STATE, "latest_yolo_busy", {}) or {}).get(0, 0) or 0)

        gnss = STATE.latest_gnss.get(0)
        gnss_ts = STATE.latest_gnss_ts.get(0)
        gnss_err = STATE.latest_gnss_error.get(0)
        gnss_mode = int((getattr(STATE, "latest_gnss_mode", {}) or {}).get(0, 0) or 0)
        gnss_connected = int((getattr(STATE, "latest_gnss_connected", {}) or {}).get(0, 0) or 0)

        can_status = (getattr(STATE, "latest_can_status", {}) or {}).get(0)
        can_ts = (getattr(STATE, "latest_can_ts", {}) or {}).get(0)
        can_err = (getattr(STATE, "latest_can_error", {}) or {}).get(0)
        can_iface = (getattr(STATE, "latest_can_iface", {}) or {}).get(0)
        vehicle_speed = (getattr(STATE, "latest_vehicle_speed", {}) or {}).get(0)
        shift = (getattr(STATE, "latest_shift", {}) or {}).get(0)
        accel_xyz = (getattr(STATE, "latest_accel_xyz", {}) or {}).get(0)
        pedal = (getattr(STATE, "latest_pedal", {}) or {}).get(0)
        steering_rate = (getattr(STATE, "latest_steering_rate", {}) or {}).get(0)
        can_signals = (getattr(STATE, "latest_can_signals", {}) or {}).get(0) or {}

        yolo_fps = (getattr(STATE, "latest_yolo_fps", {}) or {}).get(0)
        yolo_latency_ms = (getattr(STATE, "latest_yolo_latency_ms", {}) or {}).get(0)
        vlm_fps = (getattr(STATE, "latest_vlm_fps", {}) or {}).get(0)
        vlm_latency_ms = (getattr(STATE, "latest_vlm_latency_ms", {}) or {}).get(0)
        vlm_ttft_ms = (getattr(STATE, "latest_vlm_ttft_ms", {}) or {}).get(0)

    # VLM Output
    vlm_out = ""
    vlm_ts = None
    vlm_frame_id = None
    if isinstance(vlm, dict):
        vlm_out = str(vlm.get("text", "") or "")
        vlm_ts = vlm.get("ts")
        vlm_frame_id = vlm.get("frame_id")
    else:
        vlm_latency_ms = None
        vlm_ttft_ms = None

    # YOLO Detect（クラス名を抽出）
    yolo_detect = []
    if isinstance(dets, dict):
        for d in (dets.get("detections") or []):
            if not isinstance(d, dict):
                continue
            name = d.get("name") or d.get("class") or d.get("label")
            if name:
                yolo_detect.append(str(name))
    # uniq preserve order
    seen = set()
    yolo_detect = [x for x in yolo_detect if not (x in seen or seen.add(x))]
    yolo_output = summarize_dets(dets)

    speech_on = bool((cfg.get("speech", {}) or {}).get("enabled", False))
    vlm_engine = str((cfg.get("vlm", {}) or {}).get("engine", "stub") or "stub")
    vlm_enabled = (vlm_engine.lower() != "stub")
    vlm_emit_interval_sec = (cfg.get("vlm", {}) or {}).get("emit_interval_sec", None)
    vlm_running = 1 if _safe_is_alive(getattr(_scheduler, "_vlm", None)) else 0
    yolo_on = bool((cfg.get("yolo", {}) or {}).get("enabled", False))

    # hide stale outputs when disabled
    if not vlm_enabled:
        vlm_out = ""
        vlm_ts = None
        vlm_frame_id = None
        vlm_fps = None
        vlm_latency_ms = None
        vlm_ttft_ms = None

    if not yolo_on:
        yolo_detect = []
        yolo_output = "-"
        yolo_fps = None
        yolo_latency_ms = None

    # GNSS summarized status for UI
    gnss_status = "UNKNOWN"
    gnss_latlon = "-"
    if gnss_err:
        gnss_status = "GPSD CONNECT ERROR"
    elif gnss_connected and gnss_mode < 2:
        gnss_status = f"NO FIX (mode={gnss_mode})"
    elif gnss_connected and gnss and gnss.get("lat") is not None and gnss.get("lon") is not None:
        gnss_status = f"FIX OK (mode={gnss_mode})"
        gnss_latlon = f"{float(gnss['lat']):.7f}, {float(gnss['lon']):.7f}"
    elif gnss_connected:
        gnss_status = f"CONNECTED / WAITING TPV (mode={gnss_mode})"

    # CAN summarized status for UI
    can_status_text = str(can_status or "NO DATA")
    can_err_text = str(can_err or "")
    can_iface_text = str(can_iface or "-")

    if can_err_text:
        if "No such device" in can_err_text:
            can_status_text = f"IFACE MISSING ({can_iface_text})"
        else:
            can_status_text = "CAN ERROR"

    can_speed_text = "-" if vehicle_speed is None else f"{float(vehicle_speed):.1f} km/h"
    can_shift_text = str(shift or "-")

    can_accel_text = "-"
    if isinstance(accel_xyz, dict):
        ax = accel_xyz.get("x")
        ay = accel_xyz.get("y")
        az = accel_xyz.get("z")
        if ax is not None or ay is not None or az is not None:
            can_accel_text = f"x={ax}, y={ay}, z={az}"

    can_pedal_text = "-"
    if isinstance(pedal, dict):
        ap = pedal.get("accel")
        bp = pedal.get("brake")
        can_pedal_text = f"accel={ap}, brake={bp}"

    can_steer_text = "-" if steering_rate is None else f"{float(steering_rate):.1f} deg"

    can_signal_lines = []
    if isinstance(can_signals, dict):
        for label, info in can_signals.items():
            if not isinstance(info, dict):
                continue
            raw = info.get("raw")
            physical = info.get("physical")
            unit = info.get("unit") or "-"
            if isinstance(physical, float):
                physical_text = f"{physical:.3f}".rstrip("0").rstrip(".")
            else:
                physical_text = str(physical)
            can_signal_lines.append(
                f"{label}: raw={raw} / phys={physical_text} {unit}"
            )

    if can_signal_lines:
        can_signal_summary = "\n".join(can_signal_lines[:12])
    else:
        if can_err_text and "No such device" in can_err_text:
            can_signal_summary = "no decoded signals (interface missing)"
        elif can_status_text == "NO DATA":
            can_signal_summary = "no decoded signals"
        else:
            can_signal_summary = "-"
    can_signal_count = len(can_signal_lines)

    rcfg = (cfg.get("risk", {}) or {})
    event = evaluate_event(
        vlm_text=vlm_out,
    )
    risk = evaluate_risk(
        yolo_detect=yolo_detect,
        vlm_text=vlm_out,
        vlm_risk_event_types=event.get("vlm_risk_event_types", []),
        vehicle_speed_text=can_speed_text,
        shift=can_shift_text,
        scene_complexity_weight=float(rcfg.get("scene_complexity_weight", 0.35) or 0.35),
        vru_weight=float(rcfg.get("vru_weight", 0.25) or 0.25),
        blindspot_weight=float(rcfg.get("blindspot_weight", 0.20) or 0.20),
        speed_mismatch_weight=float(rcfg.get("speed_mismatch_weight", 0.20) or 0.20),
        mid_threshold=float(rcfg.get("mid_threshold", 35.0) or 35.0),
        high_threshold=float(rcfg.get("high_threshold", 55.0) or 55.0),
    )
    speech_payload = _build_speech_payload(
        risk=risk,
        event=event,
    )

    if not secondary_result:
        secondary_result = _load_latest_secondary_from_disk()
        if secondary_result and not secondary_status:
            secondary_status = "done"

    return {
        "source": source,
        "display": display,
        "voice": "ON" if speech_on else "OFF",
        "api_time_sec": api_time,

        "vlm_model": (cfg.get("vlm", {}) or {}).get("model_name", ""),
        "vlm_enabled": vlm_enabled,
        "vlm_engine": vlm_engine,
        "vlm_emit_interval_sec": vlm_emit_interval_sec,
        "vlm_busy": vlm_busy,
        "vlm_running": vlm_running,
        "vlm_status": 1 if vlm_busy else 0,
        "vlm_input": (cfg.get("vlm", {}) or {}).get("prompt", ""),
        "vlm_output": vlm_out,
        "vlm_ts": vlm_ts,
        "vlm_frame_id": vlm_frame_id,
        "vlm_fps": None if vlm_fps is None else round(float(vlm_fps), 2),
        "vlm_latency_ms": None if vlm_latency_ms is None else round(float(vlm_latency_ms), 1),
        "vlm_ttft_ms": vlm_ttft_ms,

        "yolo_model": (cfg.get("yolo", {}) or {}).get("model_name", ""),
        "yolo_status": 1 if (yolo_on and yolo_busy) else 0,
        "yolo_detect": yolo_detect,  # 配列で返す（UIで join する）
        "yolo_fps": None if yolo_fps is None else round(float(yolo_fps), 2),
        "yolo_output": yolo_output,
        "yolo_latency_ms": None if yolo_latency_ms is None else round(float(yolo_latency_ms), 1),

        "gnss_status": gnss_status,
        "gnss_latlon": gnss_latlon,
        "gnss_last_ts": gnss_ts,
        "gnss_error": gnss_err,
        "gnss_mode": gnss_mode,
        "gnss_connected": gnss_connected,

        "can_status": can_status_text,
        "can_last_ts": can_ts,
        "can_error": can_err,
        "can_speed": can_speed_text,
        "can_shift": can_shift_text,
        "can_accel": can_accel_text,
        "can_pedal": can_pedal_text,
        "can_steering_rate": can_steer_text,
        "can_signal_count": can_signal_count,
        "can_signal_summary": can_signal_summary,

        "risk_level": risk["risk_level"],
        "risk_score": risk["risk_score"],
        "risk_reason": risk["risk_reason"],
        "speak_interval_sec": risk["speak_interval_sec"],

        "scene_complexity": risk["scene_complexity"],
        "vru_load": risk["vru_load"],
        "blindspot_predictive_load": risk["blindspot_predictive_load"],
        "speed_mismatch": risk["speed_mismatch"],
        "risk_speed_kmh": risk["speed_kmh"],
        "risk_shift": risk["shift"],
        "risk_stopped_like": risk["stopped_like"],

        "risk_scene_complexity_weight": risk["scene_complexity_weight"],
        "risk_vru_weight": risk["vru_weight"],
        "risk_blindspot_weight": risk["blindspot_weight"],
        "risk_speed_mismatch_weight": risk["speed_mismatch_weight"],
        "risk_mid_threshold": risk["mid_threshold"],
        "risk_high_threshold": risk["high_threshold"],

        "event_type": event["event_type"],
        "event_confidence": event["event_confidence"],
        "event_reason": event["event_reason"],
        "share_value_event_types": event.get("share_value_event_types", []),
        "vlm_risk_event_types": event.get("vlm_risk_event_types", []),

        "speech_text": speech_payload["speech_text"],
        "speech_category": speech_payload["speech_category"],
        "speech_repeat_sec": speech_payload["speech_repeat_sec"],
        "speech_key": speech_payload["speech_key"],

        "secondary_status": secondary_status,
        "secondary_error": secondary_error,
        "secondary_text": (secondary_result or {}).get("text") if isinstance(secondary_result, dict) else "",
        "secondary_event_dir": (secondary_result or {}).get("event_dir") if isinstance(secondary_result, dict) else "",
        "secondary_latency_ms": (secondary_result or {}).get("latency_ms") if isinstance(secondary_result, dict) else None,
        "upload_enabled": bool(((cfg.get("upload") or {}).get("enabled", False))),
        "upload_mode": str(((cfg.get("upload") or {}).get("mode") or "")),
        "upload_bucket": str(((cfg.get("upload") or {}).get("s3_bucket") or "")),
        "upload_table": str(((cfg.get("upload") or {}).get("dynamodb_table") or "")),
    }


@router.post("/speech/test")
def speech_test():
    try:
        import urllib.request, json
        host = "127.0.0.1"
        req = urllib.request.Request(
            f"http://{host}:18081/speak",
            data=json.dumps({"text":"音声テストです"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": repr(e)}


class SpeechSpeakReq(BaseModel):
    text: str = ""


@router.post("/speech/speak")
def speech_speak(req: SpeechSpeakReq):
    try:
        import urllib.request, json
        host = "127.0.0.1"
        text = str(req.text or "").strip() or "音声テストです"
        http_req = urllib.request.Request(
            f"http://{host}:18081/speak",
            data=json.dumps({"text": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(http_req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": repr(e)}
