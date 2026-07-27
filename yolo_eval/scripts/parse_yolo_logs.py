import csv
import glob
import os
import re
from collections import Counter, defaultdict
from statistics import mean

RAW_DIR = "/mnt/vlm_data/vlm-platform/yolo_eval/raw_logs"
CSV_DIR = "/mnt/vlm_data/vlm-platform/yolo_eval/csv"

os.makedirs(CSV_DIR, exist_ok=True)

line_pat = re.compile(
    r"video_sec=(?P<video_sec>[0-9.\-]+).*?"
    r"frame_id=(?P<frame_id>[0-9]+).*?"
    r"yolo_fps=(?P<yolo_fps>[0-9.\-]+).*?"
    r"yolo_latency_ms=(?P<yolo_latency_ms>[0-9.\-]+).*?"
    r"event=YOLO_RESULT.*?"
    r"payload=(?P<payload>.*)$"
)

obj_pat = re.compile(r"([^,\[]+)\[(\d+)\]")

detail_rows = []
summary_map = defaultdict(list)

for path in sorted(glob.glob(os.path.join(RAW_DIR, "*.log"))):
    base = os.path.basename(path).replace(".log", "")
    m = re.match(r"(\d{8}_\d{6})_(test\d+)_(yolov8[snm])$", base)
    if not m:
        continue

    _, test_id, model = m.groups()

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            mm = line_pat.search(line)
            if not mm:
                continue

            payload = mm.group("payload").strip()
            counts = Counter()

            for name, cnt in obj_pat.findall(payload):
                counts[name.strip()] += int(cnt)

            row = {
                "test_id": test_id,
                "model": model,
                "video_sec": float(mm.group("video_sec")) if mm.group("video_sec") not in ("-", "") else None,
                "frame_id": int(mm.group("frame_id")),
                "yolo_latency_ms": float(mm.group("yolo_latency_ms")) if mm.group("yolo_latency_ms") not in ("-", "") else None,
                "yolo_fps": float(mm.group("yolo_fps")) if mm.group("yolo_fps") not in ("-", "") else None,
                "payload": payload,
                "person_count": counts.get("person", 0),
                "car_count": counts.get("car", 0),
                "bus_count": counts.get("bus", 0),
                "truck_count": counts.get("truck", 0),
                "bicycle_count": counts.get("bicycle", 0),
                "motorcycle_count": counts.get("motorcycle", 0),
                "traffic_light_count": counts.get("traffic light", 0),
                "stop_sign_count": counts.get("stop sign", 0),
                "backpack_count": counts.get("backpack", 0),
                "handbag_count": counts.get("handbag", 0),
                "chair_count": counts.get("chair", 0),
            }
            detail_rows.append(row)
            summary_map[(test_id, model)].append(row)

detail_csv = os.path.join(CSV_DIR, "yolo_eval_timeseries.csv")
with open(detail_csv, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "test_id", "model", "video_sec", "frame_id",
        "yolo_latency_ms", "yolo_fps", "payload",
        "person_count", "car_count", "bus_count", "truck_count",
        "bicycle_count", "motorcycle_count",
        "traffic_light_count", "stop_sign_count",
        "backpack_count", "handbag_count", "chair_count",
    ])
    writer.writeheader()
    writer.writerows(detail_rows)

def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    idx = int(round((len(values) - 1) * q))
    return values[idx]

summary_rows = []
for (test_id, model), rows in sorted(summary_map.items()):
    lat = [r["yolo_latency_ms"] for r in rows if r["yolo_latency_ms"] is not None]
    fps = [r["yolo_fps"] for r in rows if r["yolo_fps"] is not None]

    total = Counter()
    for r in rows:
        total["person"] += r["person_count"]
        total["car"] += r["car_count"]
        total["bus"] += r["bus_count"]
        total["truck"] += r["truck_count"]
        total["bicycle"] += r["bicycle_count"]
        total["motorcycle"] += r["motorcycle_count"]
        total["traffic light"] += r["traffic_light_count"]
        total["stop sign"] += r["stop_sign_count"]
        total["backpack"] += r["backpack_count"]
        total["handbag"] += r["handbag_count"]
        total["chair"] += r["chair_count"]

    dominant_objects = ",".join([k for k, v in total.most_common(5) if v > 0])

    summary_rows.append({
        "test_id": test_id,
        "model": model,
        "samples": len(rows),
        "latency_ms_mean": round(mean(lat), 1) if lat else None,
        "latency_ms_p50": percentile(lat, 0.50),
        "latency_ms_p95": percentile(lat, 0.95),
        "fps_mean": round(mean(fps), 3) if fps else None,
        "person_total": total["person"],
        "car_total": total["car"],
        "bus_total": total["bus"],
        "truck_total": total["truck"],
        "bicycle_total": total["bicycle"],
        "motorcycle_total": total["motorcycle"],
        "traffic_light_total": total["traffic light"],
        "stop_sign_total": total["stop sign"],
        "backpack_total": total["backpack"],
        "handbag_total": total["handbag"],
        "chair_total": total["chair"],
        "dominant_objects": dominant_objects,
        "subjective_note": "",
    })

summary_csv = os.path.join(CSV_DIR, "yolo_eval_summary.csv")
with open(summary_csv, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "test_id", "model", "samples",
        "latency_ms_mean", "latency_ms_p50", "latency_ms_p95", "fps_mean",
        "person_total", "car_total", "bus_total", "truck_total",
        "bicycle_total", "motorcycle_total",
        "traffic_light_total", "stop_sign_total",
        "backpack_total", "handbag_total", "chair_total",
        "dominant_objects", "subjective_note"
    ])
    writer.writeheader()
    writer.writerows(summary_rows)

print("created:", detail_csv)
print("created:", summary_csv)
