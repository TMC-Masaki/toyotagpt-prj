import base64
import cv2
import requests
import time

INFER_WIDTH = 640  # resize width for inference (0 disables)

class VlmOllama:
  def __init__(self, host: str, model: str):
    self.host = host.rstrip("/")
    self.model = model

  def infer(self, frame_bgr, prompt: str) -> dict:
    if frame_bgr is None:
      raise RuntimeError('frame is None')
    # frame -> jpg -> base64
    # resize for speed
    if INFER_WIDTH and frame_bgr.shape[1] > INFER_WIDTH:
      h, w = frame_bgr.shape[:2]
      nh = int(h * (INFER_WIDTH / w))
      frame_bgr = cv2.resize(frame_bgr, (INFER_WIDTH, nh))

    ok, buf = cv2.imencode(".jpg", frame_bgr)
    if not ok:
      raise RuntimeError("failed to encode jpg")
    b64 = base64.b64encode(buf.tobytes()).decode("utf-8")

    payload = {
      "model": self.model,
      "messages": [
        {"role": "user", "content": prompt, "images": [b64]}
      ],
      "stream": False
    }
    t0 = time.time()
    try:
      r = requests.post(f"{self.host}/api/chat", json=payload, timeout=300)
      r.raise_for_status()
    except Exception as e:
      elapsed_sec = time.time() - t0
      raise RuntimeError(f"ollama call failed (elapsed={elapsed_sec:.2f}s): {e}")
    j = r.json()
    # 返りの形は model により微差あるので安全に拾う
    text = (j.get("message") or {}).get("content") or j.get("response") or ""
    return {"text": text, "model": self.model, "engine": "ollama"}
