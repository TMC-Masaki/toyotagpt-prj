import threading
from typing import Optional
import sys
import time
from app.modules.workers.vision_worker import VisionWorker
from app.modules.workers.vlm_worker import VlmWorker
from app.runtime.bus import STATE
from app.modules.workers.yolo_worker import YoloWorker
from app.modules.workers.event_save_worker import EventSaveWorker
from app.modules.workers.secondary_vlm_worker import SecondaryVlmWorker
from app.modules.workers.upload_worker import UploadWorker

def _warmup_torch() -> None:
    """
    Warm up torch in the main thread BEFORE starting any worker threads.
    This prevents 'partially initialized module torch ... has no attribute nn'
    caused by concurrent first-imports from multiple threads.
    """
    try:
        import torch  # noqa: F401
        import torch.nn  # noqa: F401
        import torch.jit  # noqa: F401
    except Exception:
        # if a partial module got cached, remove it so next import is clean
        sys.modules.pop("torch", None)
        sys.modules.pop("torch._C", None)
        raise

class Scheduler:
    """
    Orchestrator:
    - start(): start vision + vlm workers
    - stop(): stop them
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._vision: Optional[VisionWorker] = None
        self._vlm: Optional[VlmWorker] = None
        self._yolo: Optional[YoloWorker] = None
        self._event_save: Optional[EventSaveWorker] = None
        self._secondary_vlm: Optional[SecondaryVlmWorker] = None
        self._upload: Optional[UploadWorker] = None
        self._started_at = None
        self._join_timeout_sec = 180.0

    def _join_worker(self, w, name: str) -> None:
        if w is None:
            return
        try:
            if w.is_alive():
                print(f"[scheduler] joining {name} ...", flush=True)
                w.join(timeout=self._join_timeout_sec)
                print(f"[scheduler] joined {name}: alive={w.is_alive()}", flush=True)
        except Exception as e:
            print(f"[scheduler] join error {name}: {e}", flush=True)

    def _has_alive_workers_locked(self) -> bool:
        workers = [self._vision, self._yolo, self._vlm, self._event_save, self._secondary_vlm, self._upload]
        for w in workers:
            try:
                if w is not None and w.is_alive():
                    return True
            except Exception:
                pass
        return False

    def _clear_workers_locked(self) -> None:
        self._vision = None
        self._yolo = None
        self._vlm = None
        self._event_save = None
        self._secondary_vlm = None
        self._upload = None

    def start(self):
        with self._lock:
            if self._running:
                return

            if self._has_alive_workers_locked():
                print("[scheduler] start aborted: old workers still alive", flush=True)
                return

            self._clear_workers_locked()

            # warm up torch before any threads touch it
            _warmup_torch()

            self._vision = VisionWorker(cam_id=0)
            self._yolo = YoloWorker(cam_id=0)
            self._vlm = VlmWorker()
            self._event_save = EventSaveWorker(cam_id=0)
            self._secondary_vlm = SecondaryVlmWorker(cam_id=0)
            self._upload = UploadWorker(cam_id=0)
            self._vision.start()
            self._yolo.start()
            self._vlm.start()
            self._event_save.start()
            self._secondary_vlm.start()
            self._upload.start()
            self._started_at = time.time()
            try:
                STATE.eval_started_at = self._started_at
            except Exception:
                pass
            self._running = True

    def stop(self):
        with self._lock:
            if not self._running and not self._has_alive_workers_locked():
                return
            if self._vision:
                self._vision.stop()
            if self._yolo:
                self._yolo.stop()
            if self._vlm:
                self._vlm.stop()
            if self._event_save:
                self._event_save.stop()
            if self._secondary_vlm:
                self._secondary_vlm.stop()
            if self._upload:
                self._upload.stop()

            self._join_worker(self._vision, "vision")
            self._join_worker(self._yolo, "yolo")
            self._join_worker(self._vlm, "vlm")
            self._join_worker(self._event_save, "event_save")
            self._join_worker(self._secondary_vlm, "secondary_vlm")
            self._join_worker(self._upload, "upload")

            # IMPORTANT: release camera/video source subprocess/device handles
            try:
                from app.modules.pipeline import inference_pipeline as ip
                ip.reset_source()
            except Exception as e:
                print(f"[scheduler] reset_source error: {e}", flush=True)

            try:
                with STATE.lock:
                    STATE.latest_frame_bgr[0] = None
                    STATE.latest_ts[0] = None
                    STATE.latest_frame_id[0] = None

                    STATE.latest_vlm[0] = None
                    STATE.latest_vlm_latency_ms[0] = None
                    STATE.latest_vlm_ttft_ms[0] = None
                    STATE.latest_vlm_fps[0] = None

                    if hasattr(STATE, "latest_dets"):
                        STATE.latest_dets[0] = None
                    if hasattr(STATE, "latest_error"):
                        STATE.latest_error[0] = None
                    if hasattr(STATE, "latest_pos_sec"):
                        STATE.latest_pos_sec[0] = None
                    if hasattr(STATE, "latest_preview_jpg"):
                        STATE.latest_preview_jpg[0] = None
                    if hasattr(STATE, "latest_preview_frame_id"):
                        STATE.latest_preview_frame_id[0] = None
                    if hasattr(STATE, "latest_preview_ts"):
                        STATE.latest_preview_ts[0] = None
                    if hasattr(STATE, "latest_event_save"):
                        STATE.latest_event_save[0] = None
                    if hasattr(STATE, "latest_event_state"):
                        STATE.latest_event_state[0] = {
                            "event_type": "none",
                            "event_types": [],
                            "ts": 0.0,
                            "frame_id": None,
                            "text": "",
                        }
                    if hasattr(STATE, "latest_event_log"):
                        STATE.latest_event_log[0] = []
                    if hasattr(STATE, "latest_secondary_result"):
                        STATE.latest_secondary_result[0] = None
                    if hasattr(STATE, "latest_secondary_status"):
                        STATE.latest_secondary_status[0] = None
                    if hasattr(STATE, "latest_secondary_error"):
                        STATE.latest_secondary_error[0] = None
            except Exception as e:
                print(f"[scheduler] clear state error: {e}", flush=True)

            self._clear_workers_locked()
            self._running = False
            self._started_at = None
            try:
                STATE.eval_started_at = None
            except Exception:
                pass
            try:
                STATE.eval_started_at = None
            except Exception:
                pass

    def is_running(self) -> bool:
        with self._lock:
            return self._running
