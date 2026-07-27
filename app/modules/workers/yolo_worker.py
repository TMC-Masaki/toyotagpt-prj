from __future__ import annotations

import time
import threading
from typing import Optional, Any

import cv2

from app.core.config import load_config
from app.runtime.bus import STATE
from app.runtime.eval_log import emit_eval_log, summarize_dets
from app.utils.draw import draw_detections

# NOTE: do NOT import ultralytics/torch at module import time (avoid circular import/race)


def _encode_preview_jpg(frame):
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
    if not ok:
        return None
    return buf.tobytes()



class YoloWorker(threading.Thread):
    """
    Dedicated YOLO worker (per cam_id).
    - reads latest frame from STATE
    - runs YOLO at preview_hz (throttled)
    - writes STATE.latest_dets with frame_id binding
    """
    daemon = True

    def __init__(self, cam_id: int = 0):
        super().__init__()
        self.cam_id = cam_id
        self._stop_evt = threading.Event()
        self._last_run_t = 0.0
        self._last_frame_id = -1
        self._last_done_t = 0.0
        self._last_preview_t = 0.0
        self._det: Optional[Any] = None
        self._det_cfg_sig = None  # to recreate detector on config change

    def stop(self):
        self._stop_evt.set()

    def _cfg_signature(self, ycfg: dict):
        # conf / iou は実行時に差し替えるだけなので再生成条件に含めない
        return (
            ycfg.get("model_name"),
            int(ycfg.get("imgsz", 640)),
        )

    def _get_detector(self, ycfg: dict):
        # delayed import to avoid torch circular import during app startup
        from app.modules.detection.yolo_detector import YoloDetector

        sig = self._cfg_signature(ycfg)
        if self._det is None or self._det_cfg_sig != sig:
            emit_eval_log(event="YOLO_DET_RECREATE", payload=f"old={self._det_cfg_sig} new={sig}")
            self._det_cfg_sig = sig
            t_det0 = time.time()
            self._det = YoloDetector(
                model_name=sig[0] or "yolov8n.pt",
                conf=float(ycfg.get("conf", 0.25)),
                iou=float(ycfg.get("iou", 0.45)),
                imgsz=sig[1],
            )

            # warmup once so first real frame does not pay the full CUDA/Ultralytics startup cost
            try:
                import numpy as np
                warm = np.zeros((640, 640, 3), dtype=np.uint8)
                _ = self._det.detect(warm)
                emit_eval_log(event="YOLO_WARMUP_OK", payload=f"sig={sig}")
            except Exception as e:
                emit_eval_log(event="YOLO_WARMUP_ERR", payload=repr(e))

            emit_eval_log(event="YOLO_DET_READY", payload=f"sec={time.time()-t_det0:.3f} sig={sig}")
        return self._det

    def run(self):
        last_skip_log = 0.0
        while not self._stop_evt.is_set():
            cfg = load_config() or {}
            ycfg = cfg.get("yolo", {}) or {}
            enabled = bool(ycfg.get("enabled", False))
            if not enabled:
                with STATE.lock:
                    STATE.latest_dets[self.cam_id] = None
                    STATE.latest_yolo_latency_ms[self.cam_id] = None
                    STATE.latest_yolo_fps[self.cam_id] = None
                now2 = time.time()
                if (now2 - last_skip_log) >= 2.0:
                    emit_eval_log(event="YOLO_DISABLED_SKIP", payload="enabled=false")
                    last_skip_log = now2
                time.sleep(0.05)
                continue

            hz = float(ycfg.get("preview_hz", 3.0) or 3.0)
            if hz <= 0:
                hz = 1.0
            period = 1.0 / hz

            now = time.time()
            if (now - self._last_run_t) < period:
                time.sleep(0.005)
                continue

            with STATE.lock:
                frame = STATE.latest_frame_bgr.get(self.cam_id)
                fid = STATE.latest_frame_id.get(self.cam_id)
                fts = STATE.latest_ts.get(self.cam_id)
                pos_sec = (getattr(STATE, "latest_pos_sec", {}) or {}).get(self.cam_id)

            if frame is None or fid is None:
                time.sleep(0.01)
                continue

            if fid == self._last_frame_id:
                time.sleep(0.005)
                continue

            self._last_run_t = now
            self._last_frame_id = fid

            try:
                emit_eval_log(event="YOLO_SUBMIT", frame_id=fid, video_sec=pos_sec, payload=f"frame_id={fid}")
                t0 = time.time()
                det = self._get_detector(ycfg)
                t1 = time.time()

                # conf / iou は detector 再生成せず、その場で更新
                det.conf = float(ycfg.get("conf", 0.25))
                det.iou = float(ycfg.get("iou", 0.45))

                out = det.detect(frame.copy())
                done_t = time.time()
                latency_ms = int((done_t - t0) * 1000)
                emit_eval_log(
                    event="YOLO_TIMING",
                    frame_id=fid,
                    video_sec=pos_sec,
                    payload=f"get_det={t1-t0:.3f}s detect={done_t-t1:.3f}s total={done_t-t0:.3f}s"
                )

                fps = None
                if self._last_done_t > 0:
                    dt = done_t - self._last_done_t
                    if dt > 1e-6:
                        fps = 1.0 / dt
                self._last_done_t = done_t

                det_pack = {
                    "frame_id": int(fid),
                    "ts": float(done_t),
                    "model": out.get("model"),
                    "detections": out.get("detections") or [],
                }
                with STATE.lock:
                    STATE.latest_dets[self.cam_id] = det_pack
                    STATE.latest_yolo_latency_ms[self.cam_id] = float(latency_ms)
                    if fps is not None:
                        STATE.latest_yolo_fps[self.cam_id] = float(fps)

                # overlay済み preview JPEG を間引いて更新
                try:
                    cfg_now = load_config() or {}
                    overlay_enabled = bool(((cfg_now.get("evaluation", {}) or {}).get("overlay_enabled", True)))
                    ycfg_now = ((cfg_now.get("yolo", {}) or {}) if isinstance(cfg_now, dict) else {})
                    preview_hz = float(ycfg_now.get("preview_hz", 3.0) or 3.0)
                    if preview_hz <= 0:
                        preview_hz = 3.0
                except Exception:
                    overlay_enabled = True
                    preview_hz = 3.0

                try:
                    preview_interval = 1.0 / preview_hz
                    do_preview_update = (self._last_preview_t <= 0.0) or ((done_t - self._last_preview_t) >= preview_interval)

                    if do_preview_update:
                        preview_frame = frame
                        if overlay_enabled and (det_pack.get("detections") or []):
                            preview_frame = draw_detections(frame.copy(), det_pack.get("detections") or [])
                        else:
                            preview_frame = frame.copy()

                        try:
                            h, w = preview_frame.shape[:2]
                            target_w = 960
                            if w > target_w:
                                target_h = int(h * (target_w / float(w)))
                                preview_frame = cv2.resize(preview_frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
                        except Exception:
                            pass

                        preview_jpg = _encode_preview_jpg(preview_frame)
                        if preview_jpg is not None:
                            with STATE.lock:
                                STATE.latest_preview_jpg[self.cam_id] = preview_jpg
                                STATE.latest_preview_frame_id[self.cam_id] = int(fid)
                                STATE.latest_preview_ts[self.cam_id] = float(done_t)
                            self._last_preview_t = done_t
                except Exception as e:
                    print(f"[yolo_worker] preview update error: {e!r}", flush=True)

                emit_eval_log(
                    event="YOLO_RESULT",
                    frame_id=fid,
                    video_sec=pos_sec,
                    yolo_fps=fps,
                    yolo_latency_ms=latency_ms,
                    payload=summarize_dets(det_pack),
                )
            except Exception as e:
                with STATE.lock:
                    STATE.latest_dets[self.cam_id] = {
                        "frame_id": int(fid),
                        "ts": float(now),
                        "model": "error",
                        "detections": [],
                        "ok": False,
                        "error": str(e),
                    }
                time.sleep(0.05)
