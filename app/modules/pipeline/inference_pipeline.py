import time
import threading
import glob
import subprocess

from app.runtime.bus import STATE
from app.core.config import load_config
from app.core.logger import write_jsonl
from app.modules.input.video_file_source import VideoFileSource
from app.modules.input.image_dir_source import ImageDirSource
from app.modules.input.v4l2_mjpg_source import V4L2MJPGSource

_speech_policy = None
_video_source = None
_camera_source = None

RUN_LOCK = threading.Lock()

LATEST_FRAME = None  # latest frame (numpy BGR)
LATEST = None  # latest inference result dict


def _is_video_capture_device(dev: str) -> bool:
    try:
        cp = subprocess.run(
            ["v4l2-ctl", "-d", dev, "--all"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        out = (cp.stdout or "")
        # metadata node ではなく、映像本体ノードを優先
        return ("Format Video Capture:" in out)
    except Exception:
        return False


def _auto_pick_camera_device(preferred_device: str | None, preferred_index: int | None) -> str:
    # 1) 明示deviceが有効なら最優先
    if preferred_device and _is_video_capture_device(preferred_device):
        return preferred_device

    # 2) camera_index由来の候補
    if preferred_index is not None:
        cand = f"/dev/video{int(preferred_index)}"
        if _is_video_capture_device(cand):
            return cand

    # 3) 走査して最初の Video Capture を使う
    for dev in sorted(glob.glob("/dev/video*")):
        if _is_video_capture_device(dev):
            return dev

    # 4) 最終フォールバック
    if preferred_device:
        return preferred_device
    if preferred_index is not None:
        return f"/dev/video{int(preferred_index)}"
    return "/dev/video0"


def _get_source(cfg):
    """
    Returns an object which provides read_frame() -> np.ndarray|None
    """
    global _video_source, _camera_source

    inp = (cfg.get("input") or {})
    itype = (inp.get("type") or "video_file").lower()

    if itype == "video_file":
        if _video_source is None:
            path = inp.get("path")
            start_sec = inp.get("start_sec", 0)
            if not path:
                raise ValueError("input.path is required for video_file")
            _video_source = VideoFileSource(path, start_sec)
        return _video_source

    if itype == "image_dir":
        if _video_source is None:
            path = inp.get("path")
            fps = float(inp.get("fps", 29.97) or 29.97)
            loop = bool(inp.get("loop", False))
            if not path:
                raise ValueError("input.path is required for image_dir")
            _video_source = ImageDirSource(path=path, fps=fps, loop=loop)
        return _video_source

    # camera / v4l2 path
    if itype in ("camera", "v4l2", "camera_v4l2_mjpg"):
        if _camera_source is None:
            cam_index = int(inp.get("camera_index", 0) or 0)
            preferred_device = inp.get("device")
            device = _auto_pick_camera_device(preferred_device, cam_index)

            width = int(inp.get("width", 1920) or 1920)
            height = int(inp.get("height", 1080) or 1080)
            fps = float(inp.get("fps", 30) or 30)

            print(f"[camera] selected device={device} (preferred={preferred_device}, camera_index={cam_index})", flush=True)

            _camera_source = V4L2MJPGSource(
                device=device,
                width=width,
                height=height,
                fps=fps,
                mmap=int(inp.get("mmap", 3) or 3),
            )
        return _camera_source

    raise ValueError(f"unknown input.type: {itype}")


def run_once() -> dict:
    global LATEST, LATEST_FRAME

    with RUN_LOCK:
        cfg = load_config()

        # IMPORTANT: prevent conflicts with scheduler/online mode
        if (cfg.get("mode") or "").lower() == "online":
            return {"ok": False, "message": "run_once is disabled in online mode. Use scheduler.", "result": None, "latency_ms": 0}

        src = _get_source(cfg)
        frame = src.read_frame() if hasattr(src, "read_frame") else None

        if frame is None:
            # video may be at EOF; try reset once for video_file
            try:
                if (cfg.get('input', {}).get('type') or '').lower() == 'video_file':
                    reset_source()
                    src = _get_source(cfg)
                    frame = src.read_frame()
            except Exception:
                pass

        if frame is None:
            err = {"ok": False, "message": "frame is None (capture failed)", "result": None, "latency_ms": 0}
            try:
                with STATE.lock:
                    STATE.latest_error[0] = err.get("message")
                    STATE.latest_ts[0] = time.time()
            except Exception:
                pass
            return err

        # keep latest frame for UI
        if not cfg.get('yolo', {}).get('enabled', False):
            LATEST_FRAME = frame

        prompt = cfg["vlm"]["prompt"]

        # VLM engine switch (unified)
        t0 = time.time()
        result = _run_vlm(frame, cfg)
        latency_ms = int((time.time() - t0) * 1000)

        record = {
            "type": "inference",
            "input": {"source": cfg["input"]["type"], "path": cfg["input"].get("path", "")},
            "vlm": {"engine": cfg["vlm"].get("engine", ""), "model_name": cfg["vlm"].get("model_name", "")},
            "prompt": prompt,
            "result": result,
            "yolo": None,
            "latency_ms": latency_ms,
        }
        log_path = write_jsonl(cfg["logging"]["dir"], record)

        LATEST = {
            "ok": True,
            "log_path": log_path,
            "result": result,
            "yolo": None,
            "latency_ms": latency_ms,
        }

        # publish to shared STATE (used by /latest and /frame.jpg and /stream.mjpeg)
        try:
            with STATE.lock:
                STATE.latest_error[0] = None
                STATE.latest_ts[0] = time.time()
                STATE.latest_frame_bgr[0] = LATEST_FRAME
                STATE.latest_vlm[0] = result
                STATE.latest_dets[0] = None
        except Exception as e:
            import traceback
            print("[run_once] STATE update failed:", repr(e), flush=True)
            traceback.print_exc()

        return LATEST


def reset_source():
    """Reset input source (video/camera) so that next run_once recreates capture."""
    global _video_source, _camera_source, LATEST_FRAME
    if _video_source is not None:
        try:
            _video_source.close()
        except Exception:
            pass
    if _camera_source is not None:
        try:
            _camera_source.close()
        except Exception:
            pass
    _video_source = None
    _camera_source = None
    LATEST_FRAME = None


def _run_vlm(frame_bgr, cfg: dict):
    vcfg = cfg.get("vlm", {}) or {}
    engine = (vcfg.get("engine") or "stub").lower()
    model = vcfg.get("model_name") or "stub"
    prompt = (vcfg.get("prompt") or "").strip() or "状況を短く説明して"

    if engine == "ollama":
        from app.modules.vlm.vlm_ollama import VlmOllama
        host = vcfg.get("ollama_host") or "http://ollama:11434"
        return VlmOllama(host, model).infer(frame_bgr, prompt)

    elif engine == "hf":
        from app.modules.vlm.vlm_hf import VlmHf, HfOpts
        opts = HfOpts(
            device=vcfg.get("hf_device") or "cuda",
            dtype=vcfg.get("hf_dtype") or "float16",
            max_new_tokens=int(vcfg.get("max_new_tokens") or 128),
            temperature=float(vcfg.get("temperature") or 0.2),
            do_sample=bool(vcfg.get("do_sample") or False),
            infer_width=int(vcfg.get("infer_width") or 640),
        )
        return VlmHf(model, opts=opts).infer(frame_bgr, prompt)

    else:
        from app.modules.vlm.vlm_stub import VlmStub
        return VlmStub().infer(frame_bgr, prompt)
