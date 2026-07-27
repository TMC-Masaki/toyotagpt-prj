import cv2

def draw_detections(frame_bgr, dets, max_labels=30):
  """
  dets: [{"xyxy":[x1,y1,x2,y2], "name":str, "conf":float}, ...]
  """
  if frame_bgr is None or not dets:
    return frame_bgr

  h, w = frame_bgr.shape[:2]
  n = 0
  for d in dets:
    if n >= max_labels:
      break
    xyxy = d.get("xyxy") or []
    if len(xyxy) != 4:
      continue
    x1, y1, x2, y2 = [int(max(0, min(v, w if i % 2 == 0 else h))) for i, v in enumerate(xyxy)]
    name = str(d.get("name", "obj"))
    conf = float(d.get("conf", 0.0))
    label = f"{name} {conf:.2f}"

    cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), (0, 255, 0), 2)
    cv2.putText(frame_bgr, label, (x1, max(0, y1 - 5)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 3, cv2.LINE_AA)
    n += 1
  return frame_bgr
