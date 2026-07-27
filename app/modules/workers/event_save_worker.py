import os
import time
import threading
from queue import Empty

from app.runtime.bus import STATE, EVENT_SAVE_Q, SECONDARY_INFER_Q, put_latest
from app.runtime.event_recorder import save_event_bundle
from app.runtime.eval_log import emit_eval_log


class EventSaveWorker(threading.Thread):
    daemon = True

    def __init__(self, cam_id: int = 0):
        super().__init__()
        self.cam_id = cam_id
        self._stop_evt = threading.Event()

    def stop(self):
        self._stop_evt.set()

    def _build_gnss_snapshot(self):
        with STATE.lock:
            gnss = dict(STATE.latest_gnss.get(self.cam_id) or {})
            gnss_ts = STATE.latest_gnss_ts.get(self.cam_id)
            gnss_mode = (getattr(STATE, "latest_gnss_mode", {}) or {}).get(self.cam_id)
            gnss_connected = (getattr(STATE, "latest_gnss_connected", {}) or {}).get(self.cam_id)
            gnss_error = (getattr(STATE, "latest_gnss_error", {}) or {}).get(self.cam_id)

        status = "UNKNOWN"
        if gnss_error:
            status = "ERROR"
        elif gnss_connected and (gnss.get("lat") is not None) and (gnss.get("lon") is not None):
            status = "OK"
        elif gnss_connected:
            status = "NO_FIX"

        return {
            "ts": gnss_ts,
            "status": status,
            "lat": gnss.get("lat"),
            "lon": gnss.get("lon"),
            "alt_m": gnss.get("alt"),
            "speed_mps": gnss.get("speed"),
            "heading_deg": gnss.get("track"),
            "fix_type": gnss.get("mode"),
            "hdop": gnss.get("hdop"),
            "mode": gnss_mode,
            "connected": gnss_connected,
            "error": gnss_error,
            "raw": gnss,
        }

    def run(self):
        print(f"[event_save_worker] run_enter cam_id={self.cam_id}", flush=True)
        while not self._stop_evt.is_set():
            try:
                job = EVENT_SAVE_Q.get(timeout=0.2)
            except Empty:
                continue
            except Exception:
                time.sleep(0.1)
                continue

            if not isinstance(job, dict):
                continue

            try:
                primary_input = dict(job.get("primary_input") or {})
                primary_input.setdefault("primary_text", str(job.get("primary_text") or ""))
                primary_input.setdefault("raw_text", str(job.get("primary_text") or ""))
                primary_input.setdefault("prompt_version", "primary_unknown")

                gnss_snapshot = self._build_gnss_snapshot()

                saved = save_event_bundle(
                    save_root=str(job.get("save_root") or "/logs/events"),
                    event_type=str(job.get("event_type") or "event"),
                    event_types=list(job.get("event_types") or []),
                    cam_id=int(job.get("cam_id") or self.cam_id),
                    trigger_ts=float(job.get("trigger_ts") or time.time()),
                    primary_text=str(job.get("primary_text") or ""),
                    primary_input=primary_input,
                    yolo_detect=job.get("yolo_detect") or [],
                    can_snapshot=job.get("can_snapshot") or {},
                    gnss_snapshot=gnss_snapshot,
                    buffer=job.get("buffer"),
                    session_id=str(job.get("session_id") or os.getenv("VLM_SESSION_ID") or ""),
                    device_id=str(job.get("device_id") or os.getenv("VLM_DEVICE_ID") or "jetson01"),
                )

                with STATE.lock:
                    STATE.latest_event_save[self.cam_id] = saved

                print(
                    f"[event_save_worker] saved event_type={saved.get('event_type')} "
                    f"dir={saved.get('event_dir')} "
                    f"clip={saved.get('clip_path')} "
                    f"sampled={len(saved.get('sampled_frame_paths') or [])}",
                    flush=True,
                )

                emit_eval_log(
                    event="EVENT_SAVED",
                    frame_id=job.get("frame_id"),
                    video_sec=job.get("video_sec"),
                    payload=str(saved.get("event_dir")),
                )

                sec_job = {
                    "cam_id": self.cam_id,
                    "event_id": saved.get("event_id"),
                    "event_type": saved.get("event_type"),
                    "event_types": list(saved.get("event_types") or []),
                    "event_dir": saved.get("event_dir"),
                    "clip_path": saved.get("clip_path"),
                    "primary_frame_path": saved.get("primary_frame_path"),
                    "sampled_frame_paths": list(saved.get("sampled_frame_paths") or []),
                }
                put_latest(SECONDARY_INFER_Q, sec_job)

                with STATE.lock:
                    STATE.latest_secondary_status[self.cam_id] = "queued"
                    STATE.latest_secondary_error[self.cam_id] = None

                print(
                    f"[event_save_worker] queued secondary event_type={saved.get('event_type')} "
                    f"event_dir={saved.get('event_dir')}",
                    flush=True,
                )

            except Exception as e:
                print(f"[event_save_worker] save error: {e!r}", flush=True)
