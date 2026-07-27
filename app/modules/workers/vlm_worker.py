import time
import threading

from app.core.config import load_config
from app.runtime.bus import STATE, EVENT_BUFFER, EVENT_SAVE_Q, put_latest
from app.modules.policy.event_policy import evaluate_event
from app.runtime.eval_log import emit_eval_log
from app.modules.pipeline import inference_pipeline as ip


class VlmWorker(threading.Thread):
    """
    Robust VLM worker (no queue dependency):
    - polls STATE.latest_frame_bgr / latest_frame_id
    - runs VLM at cfg.vlm.emit_interval_sec (or fallback)
    - writes STATE.latest_vlm[cam_id]
    """
    daemon = True

    def __init__(self, cam_id: int = 0):
        super().__init__()
        self.cam_id = cam_id
        self._stop_evt = threading.Event()
        self._last_run_t = 0.0
        self._last_frame_id = -1
        self._last_done_t = 0.0
        self._last_event_sig = None
        self._last_event_t = 0.0

    def stop(self):
        self._stop_evt.set()
        try:
            with STATE.lock:
                STATE.latest_event_state[self.cam_id] = {
                    "event_type": "none",
                    "event_types": [],
                    "ts": 0.0,
                    "frame_id": None,
                    "text": "",
                }
                STATE.latest_event_log[self.cam_id] = []
        except Exception:
            pass

    def run(self):
        print(f"[vlm_worker] run_enter cam_id={self.cam_id}", flush=True)
        with STATE.lock:
            STATE.latest_event_state[self.cam_id] = {
                "event_type": "none",
                "event_types": [],
                "ts": 0.0,
                "frame_id": None,
                "text": "",
            }
            STATE.latest_event_log[self.cam_id] = []

        last_log = 0.0
        last_skip_log = 0.0
        print(f"[vlm_worker] loop_ready cam_id={self.cam_id}", flush=True)
        while not self._stop_evt.is_set():
            print(f"[vlm_worker] before load_config cam_id={self.cam_id}", flush=True)
            cfg = load_config()
            print(f"[vlm_worker] after load_config cam_id={self.cam_id}", flush=True)
            vcfg = cfg.get("vlm", {}) or {}
            engine = (vcfg.get("engine") or "stub").lower()
            if engine == "stub":
                with STATE.lock:
                    STATE.latest_vlm[self.cam_id] = None
                    STATE.latest_vlm_latency_ms[self.cam_id] = None
                    STATE.latest_vlm_ttft_ms[self.cam_id] = None
                    STATE.latest_vlm_fps[self.cam_id] = None
                if (time.time() - last_skip_log) >= 2.0:
                    print(f"[vlm_worker] skip: engine=stub", flush=True)
                    emit_eval_log(event="VLM_DISABLED_SKIP", payload="engine=stub")
                    last_skip_log = time.time()
                time.sleep(0.1)
                continue

            # interval (seconds)
            raw_emit = vcfg.get("emit_interval_sec", None)
            try:
                emit_every = float(raw_emit) if raw_emit is not None else 2.0
            except Exception:
                emit_every = 2.0
            if emit_every <= 0:
                emit_every = 2.0

            now = time.time()
            if (now - self._last_run_t) < emit_every:
                if (time.time() - last_skip_log) >= 5.0:
                    print(f"[vlm_worker] skip: emit_interval dt={now - self._last_run_t:.3f} emit_every={emit_every:.3f}", flush=True)
                    last_skip_log = time.time()
                time.sleep(0.02)
                continue

            with STATE.lock:
                frame = STATE.latest_frame_bgr.get(self.cam_id)
                ts = STATE.latest_ts.get(self.cam_id)
                fid = STATE.latest_frame_id.get(self.cam_id)
                pos_sec = (getattr(STATE, "latest_pos_sec", {}) or {}).get(self.cam_id)
            print(f"[vlm_worker] state cam_id={self.cam_id} has_frame={frame is not None} fid={fid} ts={ts} pos_sec={pos_sec}", flush=True)

            if frame is None:
                if (time.time() - last_skip_log) >= 5.0:
                    print(f"[vlm_worker] skip: no frame cam_id={self.cam_id}", flush=True)
                    last_skip_log = time.time()
                time.sleep(0.05)
                continue

            # avoid re-running on same frame_id if present
            if fid is not None and int(fid) == int(self._last_frame_id):
                if (time.time() - last_skip_log) >= 5.0:
                    print(f"[vlm_worker] skip: same frame_id fid={fid} last_frame_id={self._last_frame_id}", flush=True)
                    last_skip_log = time.time()
                time.sleep(0.02)
                continue

            run_fid = int(fid) if fid is not None else None

            t0 = time.time()
            try:
                with STATE.lock:
                    STATE.latest_primary_infer_input[self.cam_id] = {
                        "frame_bgr": frame.copy(),
                        "frame_id": int(fid) if fid is not None else None,
                        "ts": float(ts or time.time()),
                        "pos_sec": pos_sec,
                        "primary_text": "",
                        "latency_ms": None,
                    }

                emit_eval_log(event="VLM_SUBMIT", frame_id=fid, video_sec=pos_sec, payload=f"frame_id={fid}")
                print(f"[vlm_worker] run: engine={engine} fid={fid} emit_every={emit_every}", flush=True)
                result = ip._run_vlm(frame, cfg)
                latency_ms = int((time.time() - t0) * 1000)

                if not isinstance(result, dict):
                    result = {"text": str(result)}

                done_t = time.time()
                self._last_run_t = done_t
                if run_fid is not None:
                    self._last_frame_id = run_fid
                fps = None
                if self._last_done_t > 0:
                    dt = done_t - self._last_done_t
                    if dt > 1e-6:
                        fps = 1.0 / dt
                self._last_done_t = done_t

                pack = {
                    "ts": float(ts or time.time()),
                    "frame_id": int(fid) if fid is not None else None,
                    "latency_ms": latency_ms,
                    "ttft_ms": None,
                    "text": str(result.get("text", "")),
                    "raw": result,
                }
                with STATE.lock:
                    if self.cam_id in STATE.latest_primary_infer_input:
                        try:
                            STATE.latest_primary_infer_input[self.cam_id]["primary_text"] = str(pack.get("text") or "")
                            STATE.latest_primary_infer_input[self.cam_id]["latency_ms"] = int(latency_ms)
                        except Exception:
                            pass
                    STATE.latest_vlm[self.cam_id] = pack
                    STATE.latest_error[self.cam_id] = None
                    STATE.latest_vlm_latency_ms[self.cam_id] = float(latency_ms)
                    STATE.latest_vlm_ttft_ms[self.cam_id] = None
                    if fps is not None:
                        STATE.latest_vlm_fps[self.cam_id] = float(fps)

                # Event detect (primary VLM text is event-key list)
                try:
                    ev = evaluate_event(vlm_text=pack.get("text"))
                    event_type = str(ev.get("event_type") or "none")
                    event_types = list(ev.get("event_types") or [])
                    event_sig = ",".join(event_types) if event_types else "none"

                    now2 = time.time()
                    cooldown_sec = 10.0

                    if event_type == "none":
                        with STATE.lock:
                            STATE.latest_event_state[self.cam_id] = {
                                "event_type": "none",
                                "event_types": [],
                                "ts": float(now2),
                                "frame_id": int(fid) if fid is not None else None,
                                "text": str(pack.get("text") or ""),
                            }

                    if event_type != "none" and event_types:
                        if (self._last_event_sig != event_sig) or ((now2 - self._last_event_t) >= cooldown_sec):
                            print(f"[event_recorder] trigger event_type={event_type} event_types={event_types} fid={fid} text={pack.get('text')!r}", flush=True)

                            with STATE.lock:
                                STATE.latest_event_state[self.cam_id] = {
                                    "event_type": event_type,
                                    "event_types": list(event_types),
                                    "ts": float(now2),
                                    "frame_id": int(fid) if fid is not None else None,
                                    "text": str(pack.get("text") or ""),
                                }

                                log_list = list(STATE.latest_event_log.get(self.cam_id) or [])
                                log_list.append({
                                    "ts": float(now2),
                                    "frame_id": int(fid) if fid is not None else None,
                                    "event_type": event_type,
                                    "event_types": list(event_types),
                                    "text": str(pack.get("text") or ""),
                                })
                                # 上限100件
                                STATE.latest_event_log[self.cam_id] = log_list[-100:]

                                yolo_detect = STATE.latest_dets.get(self.cam_id)
                                can_snapshot = {
                                    "status": STATE.latest_can_status.get(self.cam_id),
                                    "speed_kmh": STATE.latest_vehicle_speed.get(self.cam_id),
                                    "shift": STATE.latest_shift.get(self.cam_id),
                                    "accel_xyz": STATE.latest_accel_xyz.get(self.cam_id),
                                    "pedal": STATE.latest_pedal.get(self.cam_id),
                                    "steering_rate": STATE.latest_steering_rate.get(self.cam_id),
                                    "signals": STATE.latest_can_signals.get(self.cam_id),
                                }

                            event_save_enabled = bool((cfg.get("output", {}) or {}).get("event_save_enabled", True))
                            save_root = str((cfg.get("output", {}) or {}).get("save_dir") or "/mnt/vlm_data/logs/events")
                            print(f"[event_recorder] save_enabled={event_save_enabled} save_root={save_root}", flush=True)

                            if event_save_enabled:
                                with STATE.lock:
                                    primary_input = dict(STATE.latest_primary_infer_input.get(self.cam_id) or {})

                                primary_input.setdefault("prompt_version", "primary_v1")
                                primary_input.setdefault("engine", engine)
                                primary_input.setdefault("model_name", vcfg.get("model_name"))
                                primary_input.setdefault("infer_width", vcfg.get("infer_width"))
                                primary_input.setdefault("max_new_tokens", vcfg.get("max_new_tokens"))
                                primary_input.setdefault("latency_ms", latency_ms)
                                primary_input.setdefault("frame_id", int(fid) if fid is not None else None)
                                primary_input.setdefault("ts", float(ts or time.time()))
                                primary_input.setdefault("pos_sec", pos_sec)
                                primary_input.setdefault("primary_text", str(pack.get("text") or ""))
                                primary_input.setdefault("raw_text", str(result.get("text") or pack.get("text") or ""))

                                job = {
                                    "save_root": save_root,
                                    "event_type": event_type,
                                    "event_types": list(event_types),
                                    "cam_id": self.cam_id,
                                    "trigger_ts": float(ts or time.time()),
                                    "primary_text": str(pack.get("text") or ""),
                                    "primary_input": primary_input,
                                    "yolo_detect": yolo_detect,
                                    "can_snapshot": can_snapshot,
                                    "buffer": EVENT_BUFFER[self.cam_id],
                                    "frame_id": fid,
                                    "video_sec": pos_sec,
                                    "primary_latency_ms": latency_ms,
                                }
                                put_latest(EVENT_SAVE_Q, job)
                                print(
                                    f"[event_recorder] queued event_type={event_type} "
                                    f"event_types={event_types} "
                                    f"fid={fid} save_root={save_root}",
                                    flush=True,
                                )
                            else:
                                print(f"[event_recorder] skip save event_type={event_type}", flush=True)

                            self._last_event_sig = event_sig
                            self._last_event_t = now2
                except Exception as e:
                    print(f"[event_recorder] save error: {e!r}", flush=True)

                emit_eval_log(
                    event="VLM_RESULT",
                    frame_id=fid,
                    video_sec=pos_sec,
                    vlm_ttft_ms=None,
                    vlm_latency_ms=latency_ms,
                    payload=str(result.get("text", "")),
                )

                if now - last_log >= 5.0:
                    print(f"[vlm_worker] ok engine={engine} model={vcfg.get('model_name')} latency_ms={latency_ms}", flush=True)
                    last_log = now

            except Exception as e:
                import traceback
                print("[vlm_worker] infer error:", repr(e), flush=True)
                traceback.print_exc()
                self._last_run_t = time.time()
                with STATE.lock:
                    STATE.latest_error[self.cam_id] = f"vlm: infer error: {e}"

            time.sleep(0.01)
