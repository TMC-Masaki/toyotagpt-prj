import time
import threading

from app.core.config import load_config
from app.modules.pipeline import inference_pipeline as ip
from app.runtime.bus import STATE, VLM_IN_Q, put_latest, EVENT_BUFFER


class VisionWorker(threading.Thread):
    """
    Frame producer (per cam_id).
    - reads frames from a single shared input source
    - updates STATE.latest_frame_bgr/latest_ts/latest_frame_id/latest_pos_sec
    - emits low-frequency events to VLM queue
    NOTE: YOLO is NOT run here. (handled by YoloWorker)

    Auto-recovery:
    - if camera source returns None / raises error repeatedly,
      recreate the source automatically.
    """
    daemon = True

    def __init__(self, cam_id: int = 0):
        super().__init__()
        self.cam_id = cam_id
        self._stop_evt = threading.Event()
        self._last_vlm_emit = 0.0
        self._src_sig = None

        # auto-recovery state
        self._consecutive_failures = 0
        self._last_recover_t = 0.0

    def stop(self):
        self._stop_evt.set()
        try:
            # read_frame() blocking を早く抜けるために source を即 close/reset
            ip.reset_source()
            print(f"[vision] stop: reset_source cam_id={self.cam_id}", flush=True)
        except Exception as e:
            print(f"[vision] stop: reset_source error cam_id={self.cam_id} err={e!r}", flush=True)

    def _make_src_sig(self, cfg: dict):
        inp = (cfg.get("input", {}) or {})
        return (
            str(inp.get("type") or ""),
            str(inp.get("path") or ""),
            str(inp.get("device") or ""),
            int(inp.get("camera_index", 0) or 0),
            int(inp.get("width", 0) or 0),
            int(inp.get("height", 0) or 0),
            float(inp.get("fps", 0) or 0),
        )

    def _recover_source(self, cfg: dict, reason: str):
        now = time.time()

        # reset storm 防止
        if (now - self._last_recover_t) < 1.0:
            return None

        self._last_recover_t = now

        try:
            print(f"[vision] recovering source: reason={reason}", flush=True)
            ip.reset_source()
            src = ip._get_source(cfg)
            self._src_sig = self._make_src_sig(cfg)
            self._consecutive_failures = 0
            with STATE.lock:
                STATE.latest_error[self.cam_id] = None
            print("[vision] source recovered", flush=True)
            return src
        except Exception as e:
            with STATE.lock:
                STATE.latest_error[self.cam_id] = f"vision: recover error: {e}"
            print(f"[vision] source recover failed: {e!r}", flush=True)
            return None

    def run(self):
        # init source once
        try:
            EVENT_BUFFER[self.cam_id].reopen()
        except Exception:
            pass

        cfg = load_config() or {}
        self._src_sig = self._make_src_sig(cfg)
        try:
            src = ip._get_source(cfg)
        except Exception as e:
            with STATE.lock:
                STATE.latest_error[self.cam_id] = f"vision: source init error: {e}"
            return

        while not self._stop_evt.is_set():
            loop_t0 = time.time()
            cfg = load_config() or {}
            inp = (cfg.get("input", {}) or {})
            itype = inp.get("type", "")

            # input/source setting changed -> recreate source
            sig = self._make_src_sig(cfg)
            if sig != self._src_sig:
                try:
                    ip.reset_source()
                    src = ip._get_source(cfg)
                    self._src_sig = sig
                    self._consecutive_failures = 0
                    try:
                        EVENT_BUFFER[self.cam_id].clear()
                        print(f"[vision] event buffer cleared: source changed cam_id={self.cam_id}", flush=True)
                    except Exception:
                        pass
                    with STATE.lock:
                        STATE.latest_error[self.cam_id] = None
                    print(f"[vision] source recreated sig={sig}", flush=True)
                except Exception as e:
                    with STATE.lock:
                        STATE.latest_error[self.cam_id] = f"vision: source recreate error: {e}"
                    time.sleep(0.2)
                    continue

            # capture period
            capture_period = None
            try:
                if itype == "video_file" and hasattr(src, "fps"):
                    fps = float(getattr(src, "fps", 0.0) or 0.0)
                    if fps > 1e-3:
                        capture_period = 1.0 / fps
            except Exception:
                capture_period = None

            # camera は input.fps を優先
            if capture_period is None and itype in ("camera", "v4l2", "camera_v4l2_mjpg"):
                try:
                    cam_fps = float(inp.get("fps", 30) or 30)
                except Exception:
                    cam_fps = 30.0
                if cam_fps <= 1e-3:
                    cam_fps = 30.0
                capture_period = 1.0 / cam_fps

            if capture_period is None:
                capture_period = float((cfg.get("pipeline", {}) or {}).get("interval_sec", 0.2) or 0.2)

            if capture_period < 0:
                capture_period = 0.0

            # read one frame
            try:
                frame = src.read_frame() if hasattr(src, "read_frame") else None
            except Exception as e:
                self._consecutive_failures += 1
                with STATE.lock:
                    STATE.latest_error[self.cam_id] = f"vision: source error: {e}"

                if itype != "video_file" and self._consecutive_failures >= 3:
                    new_src = self._recover_source(cfg, f"exception x{self._consecutive_failures}")
                    if new_src is not None:
                        src = new_src
                        continue

                sleep_s = max(0.005, capture_period - (time.time() - loop_t0))
                time.sleep(sleep_s)
                continue

            if frame is None:
                self._consecutive_failures += 1
                with STATE.lock:
                    STATE.latest_error[self.cam_id] = f"vision: frame is None x{self._consecutive_failures}"

                # video_file は起動直後の空振りを許容する
                try:
                    if itype == "video_file":
                        if self._consecutive_failures >= 10:
                            print(f"[vision] video_file reset after none x{self._consecutive_failures}", flush=True)
                            ip.reset_source()
                            cfg2 = load_config()
                            src = ip._get_source(cfg2)
                            self._consecutive_failures = 0
                        else:
                            time.sleep(0.02)
                        continue
                except Exception as e:
                    with STATE.lock:
                        STATE.latest_error[self.cam_id] = f"vision: video_file recover error: {e}"
                    time.sleep(0.05)
                    continue

                # camera auto-recover
                if itype != "video_file" and self._consecutive_failures >= 3:
                    new_src = self._recover_source(cfg, f"frame_none x{self._consecutive_failures}")
                    if new_src is not None:
                        src = new_src
                        continue

                sleep_s = max(0.005, capture_period - (time.time() - loop_t0))
                time.sleep(sleep_s)
                continue

            # success
            self._consecutive_failures = 0
            ts = time.time()
            read_to_publish_t0 = time.time()

            # frame_id increment
            with STATE.lock:
                fid = int(STATE.latest_frame_id.get(self.cam_id, 0) or 0) + 1
                STATE.latest_frame_id[self.cam_id] = fid

            # best-effort pos_sec
            pos_sec = None
            try:
                fn = getattr(src, "get_pos_sec", None)
                if callable(fn):
                    pos_sec = float(fn())
            except Exception:
                pos_sec = None

            with STATE.lock:
                STATE.latest_frame_bgr[self.cam_id] = frame
                STATE.latest_ts[self.cam_id] = ts
                if pos_sec is not None and hasattr(STATE, "latest_pos_sec"):
                    STATE.latest_pos_sec[self.cam_id] = pos_sec
                STATE.latest_error[self.cam_id] = None

            try:
                ok = EVENT_BUFFER[self.cam_id].append(frame_bgr=frame, ts=ts, frame_id=fid)
                print(f"[vision] event buffer append cam_id={self.cam_id} fid={fid} ok={ok} summary={EVENT_BUFFER[self.cam_id].summary()}", flush=True)
            except Exception as e:
                print(f"[vision] event buffer append error: {e!r}", flush=True)

            try:
                h, w = frame.shape[:2]
            except Exception:
                h, w = -1, -1
            publish_ms = (time.time() - read_to_publish_t0) * 1000.0
            print(
                f"[vision_pub] fid={fid} pos_sec={pos_sec} publish_ms={publish_ms:.1f} size={w}x{h}",
                flush=True
            )

            # VLM event emit (logic unchanged)
            vlm_cfg = cfg.get("vlm", {}) or {}
            engine = (vlm_cfg.get("engine") or "stub").lower()
            emit_stub = bool(vlm_cfg.get("emit_stub", False))

            raw_emit = vlm_cfg.get("emit_interval_sec", None)
            if raw_emit is None:
                emit_every = max(1.0, capture_period)
            else:
                try:
                    emit_every = float(raw_emit)
                except Exception:
                    emit_every = max(1.0, capture_period)

            if emit_every <= 0:
                emit_every = max(1.0, capture_period)

            if (engine != "stub") or emit_stub:
                if ts - self._last_vlm_emit >= emit_every:
                    put_latest(VLM_IN_Q, {"cam_id": self.cam_id, "ts": ts, "frame_id": fid})
                    self._last_vlm_emit = ts

            # pacing (subtract work already spent in this loop)
            if itype == "video_file":
                fps = float(getattr(src, "fps", 0.0) or 0.0)
                period = (1.0 / fps) if fps > 1e-6 else 1.0 / 30.0
                remain = period - (time.time() - loop_t0)
                time.sleep(max(0.0, remain))
            else:
                remain = capture_period - (time.time() - loop_t0)
                time.sleep(max(0.0, remain))

        try:
            EVENT_BUFFER[self.cam_id].close()
            print(f"[vision] event buffer closed cam_id={self.cam_id}", flush=True)
        except Exception:
            pass
