#!/usr/bin/env python3
import csv
import json
import sys
from pathlib import Path

DEFAULT_IN = Path("/mnt/vlm_data/logs/eval_events.jsonl")
DEFAULT_OUT = Path("/mnt/vlm_data/logs/eval_events.csv")

FIELDNAMES = [
    "ts",
    "app_ms",
    "video_sec",
    "frame_id",
    "yolo_fps",
    "yolo_latency_ms",
    "vlm_ttft_ms",
    "vlm_latency_ms",
    "event",
    "payload",
]

def normalize_row(obj: dict) -> dict:
    row = {}
    for k in FIELDNAMES:
        v = obj.get(k)
        row[k] = "" if v is None else v
    return row

def main():
    in_path = Path(sys.argv[1]) if len(sys.argv) >= 2 else DEFAULT_IN
    out_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else DEFAULT_OUT

    if not in_path.exists():
        print(f"input not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    rows = []
    with in_path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception as e:
                print(f"skip line {lineno}: invalid json: {e}", file=sys.stderr)
                continue
            if not isinstance(obj, dict):
                print(f"skip line {lineno}: not an object", file=sys.stderr)
                continue
            rows.append(normalize_row(obj))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote: {out_path}")
    print(f"rows : {len(rows)}")

if __name__ == "__main__":
    main()
