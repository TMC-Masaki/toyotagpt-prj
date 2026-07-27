from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
import time
import cv2
import numpy as np

from app.runtime.bus import STATE
from app.runtime.eval_log import emit_eval_log
from app.core.config import load_config
from app.utils.draw import draw_detections

router = APIRouter()


def _encode_jpg(frame):
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 35])
    if not ok:
        return None
    return buf.tobytes()


def mjpeg_generator(fps: int = 30, cam_id: int = 0):
    interval = 1.0 / max(1, int(fps))
    last_good = None

    while True:
        t0 = time.time()
        try:
            with STATE.lock:
                frame = STATE.latest_frame_bgr.get(cam_id)
                frame_id = STATE.latest_frame_id.get(cam_id)
                det_pack = STATE.latest_dets.get(cam_id)
                preview_jpg = (getattr(STATE, "latest_preview_jpg", {}) or {}).get(cam_id)
                preview_fid = (getattr(STATE, "latest_preview_frame_id", {}) or {}).get(cam_id)
                preview_ts = (getattr(STATE, "latest_preview_ts", {}) or {}).get(cam_id)

            if frame is None:
                if last_good is None:
                    frame = np.zeros((360, 640, 3), dtype=np.uint8)
                else:
                    frame = last_good.copy()
            else:
                try:
                    frame = frame.copy()
                except Exception:
                    pass
                last_good = frame

            draw_sec = 0.0

            # overlay 設定確認
            try:
                cfg = load_config() or {}
                overlay_enabled = bool(((cfg.get("evaluation", {}) or {}).get("overlay_enabled", True)))
            except Exception:
                overlay_enabled = True

            # prebuilt overlay JPEG を優先利用
            try:
                if overlay_enabled and preview_jpg is not None and preview_fid is not None:
                    preview_age = (time.time() - float(preview_ts)) if preview_ts is not None else 999.0
                    lag = max(0, int(frame_id) - int(preview_fid)) if (frame_id is not None and preview_fid is not None) else 999999

                    max_preview_age_sec = 5.0
                    max_preview_lag_frames = 90

                    if preview_age <= max_preview_age_sec and lag <= max_preview_lag_frames:
                        yield (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n\r\n" + preview_jpg + b"\r\n"
                        )

                        sleep_for = interval - (time.time() - t0)
                        if sleep_for > 0:
                            time.sleep(sleep_for)
                        continue
            except Exception:
                pass

            # 最新 det を少し長めに使う
            try:
                if overlay_enabled and det_pack:
                    dets = det_pack.get("detections") or []
                    det_fid = det_pack.get("frame_id")
                    det_ts = det_pack.get("ts")

                    if dets and frame_id is not None and det_fid is not None:
                        lag = max(0, int(frame_id) - int(det_fid))
                        age = (time.time() - float(det_ts)) if det_ts is not None else 999.0

                        max_lag_frames = 90
                        max_age_sec = 5.0

                        if lag <= max_lag_frames and age <= max_age_sec:
                            t_draw0 = time.time()
                            frame = draw_detections(frame, dets)
                            draw_sec = time.time() - t_draw0
                            try:
                                emit_eval_log(
                                    event="OVERLAY_DRAW",
                                    frame_id=int(frame_id) if frame_id is not None else -1,
                                    payload=f"dets={len(dets)}"
                                )
                            except Exception:
                                pass
            except Exception as e:
                print("[stream] overlay error:", repr(e), flush=True)

            # 表示だけ軽くする
            try:
                h, w = frame.shape[:2]
                target_w = 960
                if w > target_w:
                    target_h = int(h * (target_w / float(w)))
                    frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
            except Exception as e:
                print("[stream] resize error:", repr(e), flush=True)

            t_enc0 = time.time()
            jpg = _encode_jpg(frame)
            enc_sec = time.time() - t_enc0

            if jpg is not None:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Cache-Control: no-cache\r\n"
                    b"Pragma: no-cache\r\n"
                    b"Content-Length: " + str(len(jpg)).encode() + b"\r\n\r\n"
                    + jpg + b"\r\n"
                )

            total_sec = time.time() - t0
            print(
                f"[stream] timing draw={draw_sec:.3f}s enc={enc_sec:.3f}s total={total_sec:.3f}s fps_req={fps}",
                flush=True
            )

        except GeneratorExit:
            break
        except Exception as e:
            print("[stream] generator error:", repr(e), flush=True)
            time.sleep(0.05)

        dt = time.time() - t0
        time.sleep(max(0.0, interval - dt))


@router.get("/stream.mjpeg")
def stream_mjpeg(fps: int = Query(30, ge=1, le=60)):
    return StreamingResponse(
        mjpeg_generator(fps=fps, cam_id=0),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
