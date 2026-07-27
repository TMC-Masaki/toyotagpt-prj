import csv
import glob
import os
import re
from collections import defaultdict
from statistics import mean

RAW_DIR = "/mnt/vlm_data/vlm-platform/vlm_eval/raw_logs"
CSV_DIR = "/mnt/vlm_data/vlm-platform/vlm_eval/csv"

os.makedirs(CSV_DIR, exist_ok=True)

pat = re.compile(
    r"video_sec=(?P<video_sec>[0-9.\-]+).*?"
    r"frame_id=(?P<frame_id>[0-9\-]+).*?"
    r"yolo_fps=(?P<yolo_fps>[0-9.\-]+|-).*?"
    r"yolo_latency_ms=(?P<yolo_latency_ms>[0-9.\-]+|-).*?"
    r"vlm_ttft_ms=(?P<vlm_ttft_ms>[0-9.\-]+|-).*?"
    r"vlm_latency_ms=(?P<vlm_latency_ms>[0-9.\-]+|-).*?"
    r"event=(?P<event>VLM_SUBMIT|VLM_RESULT|VLM_DISABLED_SKIP).*?"
    r"payload=(?P<payload>.*)$"
)

rows = []
summary = defaultdict(list)

for path in sorted(glob.glob(os.path.join(RAW_DIR, "*.log"))):
    base = os.path.basename(path).replace(".log", "")
    m = re.match(r"(\d{8}_\d{6})_(test\d+)_(low|mid)_(.+)$", base)
    if not m:
        continue
    _, test_id, complexity, model_key = m.groups()

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            mm = pat.search(line)
            if not mm:
                continue

            def conv_float(x):
                return None if x in ("", "-", None) else float(x)

            row = {
                "test_id": test_id,
                "complexity": complexity,
                "model_key": model_key,
                "event": mm.group("event"),
                "video_sec": conv_float(mm.group("video_sec")),
                "frame_id": None if mm.group("frame_id") in ("", "-", None) else int(mm.group("frame_id")),
                "vlm_ttft_ms": conv_float(mm.group("vlm_ttft_ms")),
                "vlm_latency_ms": conv_float(mm.group("vlm_latency_ms")),
                "payload": mm.group("payload").strip(),
            }
            rows.append(row)
            if row["event"] == "VLM_RESULT":
                summary[(test_id, complexity, model_key)].append(row)

detail_csv = os.path.join(CSV_DIR, "vlm_eval_test5_timeseries.csv")
with open(detail_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=[
        "test_id", "complexity", "model_key", "event",
        "video_sec", "frame_id", "vlm_ttft_ms", "vlm_latency_ms", "payload"
    ])
    w.writeheader()
    w.writerows(rows)

def pct(vals, q):
    if not vals:
        return None
    vals = sorted(vals)
    idx = int(round((len(vals) - 1) * q))
    return vals[idx]

summary_rows = []
for key, vals in sorted(summary.items()):
    test_id, complexity, model_key = key
    lat = [v["vlm_latency_ms"] for v in vals if v["vlm_latency_ms"] is not None]
    ttft = [v["vlm_ttft_ms"] for v in vals if v["vlm_ttft_ms"] is not None]
    summary_rows.append({
        "test_id": test_id,
        "complexity": complexity,
        "model_key": model_key,
        "samples": len(vals),
        "vlm_latency_ms_mean": round(mean(lat), 1) if lat else None,
        "vlm_latency_ms_p50": pct(lat, 0.50),
        "vlm_latency_ms_p95": pct(lat, 0.95),
        "vlm_ttft_ms_mean": round(mean(ttft), 1) if ttft else None,
        "vlm_ttft_ms_p50": pct(ttft, 0.50),
        "vlm_ttft_ms_p95": pct(ttft, 0.95),
        "last_output": vals[-1]["payload"] if vals else "",
    })

summary_csv = os.path.join(CSV_DIR, "vlm_eval_test5_summary.csv")
with open(summary_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=[
        "test_id", "complexity", "model_key", "samples",
        "vlm_latency_ms_mean", "vlm_latency_ms_p50", "vlm_latency_ms_p95",
        "vlm_ttft_ms_mean", "vlm_ttft_ms_p50", "vlm_ttft_ms_p95",
        "last_output"
    ])
    w.writeheader()
    w.writerows(summary_rows)

print("created:", detail_csv)
print("created:", summary_csv)
