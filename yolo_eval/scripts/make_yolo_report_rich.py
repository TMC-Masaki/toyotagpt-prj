import csv
from collections import defaultdict, Counter
from pathlib import Path

BASE = Path("/mnt/vlm_data/vlm-platform/yolo_eval")
TIMESERIES = BASE / "csv" / "yolo_eval_timeseries.csv"
OUT = BASE / "csv" / "yolo_eval_report_rich.txt"

scene_map = {
    "test1": ("車の多い高速道路（大井松田付近）", "/data/test1.mp4"),
    "test2": ("見通しの悪い住宅街（自宅付近）", "/data/test2.mp4"),
    "test3": ("歩行者の多いエリア（東海大）", "/data/test3.mp4"),
    "test4": ("右折待ちバスによる死角（秦野駅付近）", "/data/test4.mp4"),
    "test5": ("認知負荷の高い場所（近所のスーパー）", "/data/test5.mp4"),
    "test6": ("夜間工事＆混雑（秦野246）", "/data/test6.mp4"),
    "test7": ("夜間路面陥没（平塚施設駐車場）", "/data/test7.mp4"),
    "test8": ("夜間何もない道（平塚農道）", "/data/test8.mp4"),
    "test9": ("夜間大通り（厚木インター通り）", "/data/test9.mp4"),
}
model_map = {
    "yolov8n": "yolov8n.pt",
    "yolov8s": "yolov8s.pt",
    "yolov8m": "yolov8m.pt",
}

def to_float(x):
    return None if x in ("", None, "None") else float(x)

def percentile(sorted_vals, q):
    if not sorted_vals:
        return None
    idx = int(round((len(sorted_vals) - 1) * q))
    return sorted_vals[idx]

def nearest_row(rows, key, target):
    if target is None:
        return None
    best = None
    best_diff = None
    for r in rows:
        v = r.get(key)
        if v is None:
            continue
        d = abs(v - target)
        if best is None or d < best_diff:
            best = r
            best_diff = d
    return best

groups = defaultdict(list)

with TIMESERIES.open("r", encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        parsed = {
            "test_id": row["test_id"],
            "model": row["model"],
            "video_sec": to_float(row.get("video_sec")),
            "frame_id": int(float(row["frame_id"])) if row.get("frame_id") else None,
            "yolo_latency_ms": to_float(row.get("yolo_latency_ms")),
            "yolo_fps": to_float(row.get("yolo_fps")),
            "payload": row.get("payload", ""),
        }
        class_counts = {}
        for k, v in row.items():
            if k.endswith("_count"):
                class_counts[k[:-6]] = int(float(v or 0))
        parsed["class_counts"] = class_counts
        groups[(parsed["test_id"], parsed["model"])].append(parsed)

def fmt_ms(v):
    return "-" if v is None else f"{v:.1f} ms"

def fmt_fps(v):
    return "-" if v is None else f"{v:.3f} fps"

def fmt_ts(r):
    return "-" if not r or r.get("video_sec") is None else f"{r['video_sec']:.3f} sec"

def mean(vals):
    return None if not vals else sum(vals) / len(vals)

lines = []

for test_id in [f"test{i}" for i in range(1, 10)]:
    for model in ["yolov8n", "yolov8s", "yolov8m"]:
        rows = groups.get((test_id, model), [])
        scene_note, video_path = scene_map[test_id]

        lat_rows = [r for r in rows if r["yolo_latency_ms"] is not None]
        fps_rows = [r for r in rows if r["yolo_fps"] is not None]

        lat_vals = sorted(r["yolo_latency_ms"] for r in lat_rows)
        fps_vals = sorted(r["yolo_fps"] for r in fps_rows)

        lat_max = max(lat_rows, key=lambda r: r["yolo_latency_ms"]) if lat_rows else None
        lat_min = min(lat_rows, key=lambda r: r["yolo_latency_ms"]) if lat_rows else None
        lat_p50 = percentile(lat_vals, 0.50)
        lat_p95 = percentile(lat_vals, 0.95)
        lat_p50_row = nearest_row(lat_rows, "yolo_latency_ms", lat_p50)
        lat_p95_row = nearest_row(lat_rows, "yolo_latency_ms", lat_p95)
        lat_mean = mean(lat_vals)

        fps_max = max(fps_rows, key=lambda r: r["yolo_fps"]) if fps_rows else None
        fps_min = min(fps_rows, key=lambda r: r["yolo_fps"]) if fps_rows else None
        fps_p50 = percentile(fps_vals, 0.50)
        fps_p95 = percentile(fps_vals, 0.95)
        fps_p50_row = nearest_row(fps_rows, "yolo_fps", fps_p50)
        fps_p95_row = nearest_row(fps_rows, "yolo_fps", fps_p95)
        fps_mean = mean(fps_vals)

        class_totals = Counter()
        for r in rows:
            for cls, cnt in r["class_counts"].items():
                class_totals[cls] += cnt

        total_dets = sum(class_totals.values())
        detected_classes = [k for k, v in class_totals.items() if v > 0]
        detected_classes_sorted = [k for k, _ in class_totals.most_common() if class_totals[k] > 0]
        detected_label = "、".join(detected_classes_sorted) if detected_classes_sorted else "-"
        class_breakdown = "、".join(f"{k}={v}" for k, v in class_totals.most_common() if v > 0)

        warmup_note = ""
        if lat_max and lat_max["video_sec"] is not None and lat_max["video_sec"] < 15:
            warmup_note = " ※最大レイテンシは初期ウォームアップ影響の可能性あり"

        lines.append(f"使用映像：{test_id} / {scene_note}")
        lines.append(f"使用映像パス：{video_path}")
        lines.append(f"使用モデル：{model_map[model]}")
        lines.append(f"データ数：{len(rows)}")
        lines.append(f"最大レイテンシ：{fmt_ms(lat_max['yolo_latency_ms']) if lat_max else '-'}：{fmt_ts(lat_max)}{warmup_note}")
        lines.append(f"最小レイテンシ：{fmt_ms(lat_min['yolo_latency_ms']) if lat_min else '-'}：{fmt_ts(lat_min)}")
        lines.append(f"レイテンシ中央値：{fmt_ms(lat_p50)}：{fmt_ts(lat_p50_row)}")
        lines.append(f"レイテンシ平均値：{fmt_ms(lat_mean)}")
        lines.append(f"P95：{fmt_ms(lat_p95)}：{fmt_ts(lat_p95_row)}")
        lines.append("")
        lines.append(f"最大FPS：{fmt_fps(fps_max['yolo_fps']) if fps_max else '-'}：{fmt_ts(fps_max)}")
        lines.append(f"最小FPS：{fmt_fps(fps_min['yolo_fps']) if fps_min else '-'}：{fmt_ts(fps_min)}")
        lines.append(f"FPS中央値：{fmt_fps(fps_p50)}：{fmt_ts(fps_p50_row)}")
        lines.append(f"FPS平均値：{fmt_fps(fps_mean)}")
        lines.append(f"P95：{fmt_fps(fps_p95)}：{fmt_ts(fps_p95_row)}")
        lines.append("")
        lines.append(f"総検出数：{total_dets}")
        lines.append(f"検出種別数：{len(detected_classes)}")
        lines.append(f"検出物：{detected_label}")
        lines.append(f"検出物内訳：{class_breakdown if class_breakdown else '-'}")
        lines.append("")
        tops = [k for k, _ in class_totals.most_common(3) if class_totals[k] > 0]
        top_text = "、".join(tops) if tops else "検出少"
        if test_id == "test1":
            note = f"高速道路シーン。主に {top_text} を検出。車両中心の傾向確認に適する。"
        elif test_id == "test2":
            note = f"住宅街シーン。遮蔽や見通しの悪さの中で {top_text} の出方を確認しやすい。"
        elif test_id == "test3":
            note = f"歩行者多シーン。person を含む {top_text} の比較に有効。"
        elif test_id == "test4":
            note = f"死角シーン。bus / person / car 系の拾い方差を見やすい。"
        elif test_id == "test5":
            note = f"多物標シーン。{top_text} を中心に検出量差が出やすい。"
        elif test_id == "test6":
            note = f"夜間工事・混雑シーン。夜間かつ複雑環境でのクラス傾向差が見える。"
        elif test_id == "test7":
            note = f"夜間特殊シーン。夜間環境での車両中心検出傾向を確認しやすい。"
        elif test_id == "test8":
            note = f"夜間何もない道。誤検出傾向の観察に向く。"
        else:
            note = f"夜間大通り。夜間車両系シーンでのバランス比較に向く。"

        lines.append(f"主観的特徴、傾向：{note}")
        lines.append("")
        lines.append("-" * 88)
        lines.append("")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"created: {OUT}")
