from __future__ import annotations
from typing import Any, Dict, List
import torch

class YoloDetector:
  def __init__(self, model_name: str, conf: float = 0.25, iou: float = 0.45, imgsz: int = 640):
    from ultralytics import YOLO
    self.model_name = model_name
    self.conf = conf
    self.iou = iou
    self.imgsz = imgsz
    self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
    print(f"[yolo_detector] model={model_name} imgsz={imgsz} device={self.device}", flush=True)
    self._yolo = YOLO(model_name)

  def detect(self, frame_bgr) -> Dict[str, Any]:
    results = self._yolo.predict(
      source=frame_bgr,
      conf=self.conf,
      iou=self.iou,
      imgsz=self.imgsz,
      device=self.device,
      verbose=False
    )
    r0 = results[0]
    names = r0.names or {}
    dets: List[Dict[str, Any]] = []
    if r0.boxes is not None:
      for b in r0.boxes:
        xyxy = b.xyxy[0].tolist()
        cls_id = int(b.cls[0].item()) if b.cls is not None else -1
        conf = float(b.conf[0].item()) if b.conf is not None else 0.0
        dets.append({
          "cls": cls_id,
          "name": str(names.get(cls_id, cls_id)),
          "conf": conf,
          "xyxy": [float(x) for x in xyxy],
        })
    return {"model": self.model_name, "detections": dets}
