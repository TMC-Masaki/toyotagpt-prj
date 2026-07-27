import csv
import math
from collections import defaultdict, Counter
from pathlib import Path

BASE = Path("/mnt/vlm_data/vlm-platform/yolo_eval")
TIMESERIES = BASE / "csv" / "yolo_eval_timeseries.csv"
OUT = BASE / "csv" / "yolo_eval_report.txt"

if not TIMESERIES.exists():
    raise SystemExit(f"not found: {TIMESERIES}")

def pct(sorted_vals, q):
    if not sorted_vals:
        return None
    idx = int(round((len(sorted_vals) - 1) * q))
    return sorted_vals[idx]

def nearest_row(rows, key, value):
    if value is None or not rows:
        return None
    best = None
    best_diff = None
    for r in rows:
        v = r.get(key)
        if v is None:
            continue
        d = abs(v - value)
        if best is None or d < best_diff:
            best = r
            best_diff = d
    return best

groups = defaultdict(list)

with TIMESERIES.open("r", encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        test_id = row["test_id"]
        model = row["model"]

        def to_float(x):
            return None if x in ("", None, "None") else float(x)

        def to_int(x):
            return None if x in ("", None, "None") else int(float(x))

        parsed = {
            "test_id": test_id,
            "model": model,
            "video_sec": to_float(row.get("video_sec")),
            "frame_id": to_int(row.get("frame_id")),
            "yolo_latency_ms": to_float(row.get("yolo_latency_ms")),
            "yolo_fps": to_float(row.get("yolo_fps")),
            "payload": row.get("payload", ""),
        }

        class_counts = {}
        total_det = 0
        for k, v in row.items():
            if k.endswith("_count"):
                cnt = to_int(v) or 0
                class_counts[k[:-6]] = cnt
                total_det += cnt

        parsed["class_counts"] = class_counts
        parsed["total_det"] = total_det
        groups[(test_id, model)].append(parsed)

scene_map = {
    "test1": "車の多い高速道路（大井松田付近）",
    "test2": "見通しの悪い住宅街（自宅付近）",
    "test3": "歩行者の多いエリア（東海大）",
    "test4": "右折待ちバスによる死角（秦野駅付近）",
    "test5": "認知負荷の高い場所（近所のスーパー）",
    "test6": "夜間工事＆混雑（秦野246）",
    "test7": "夜間路面陥没（平塚施設駐車場）",
    "test8": "夜間何もない道（平塚農道）",
    "test9": "夜間大通り（厚木インター通り）",
}

model_map = {
    "yolov8n": "yolov8n.pt",
    "yolov8s": "yolov8s.pt",
    "yolov8m": "yolov8m.pt",
}

def subjective_note(test_id, model, class_totals, lat_mean, fps_mean):
    objs = [k for k, v in class_totals.most_common() if v > 0]
    top = "、".join(objs[:3]) if objs else "検出少"
    speed = f"平均{lat_mean:.1f}ms / {fps_mean:.3f}fps" if lat_mean is not None and fps_mean is not None else "速度情報不足"

    if test_id == "test1":
        return f"高速道路シーン。主に車両系（{top}）を安定検出。{speed}。"
    if test_id == "test2":
        return f"住宅街シーン。車両に加え歩行者の出方を確認しやすい。{speed}。"
    if test_id == "test3":
        return f"歩行者多シーン。person 検出傾向の比較に有効。{speed}。"
    if test_id == "test4":
        return f"死角シーン。bus/person/car の拾い方差を見やすい。{speed}。"
    if test_id == "test5":
        return f"認知負荷高シーン。多物標環境での検出量差を確認しやすい。{speed}。"
    if test_id == "test6":
        return f"夜間工事・混雑シーン。夜間かつ複雑環境でのクラス傾向差が出やすい。{speed}。"
    if test_id == "test7":
        return f"夜間特殊シーン。速度差が小さいかを見やすい。{speed}。"
    if test_id == "test8":
        return f"夜間何もない道。誤検出傾向を観察しやすい。{speed}。"
    if test_id == "test9":
        return f"夜間大通り。夜間車両系のバランス比較に向く。{speed}。"
    return f"{top} が中心。{speed}。"

order_tests = [f"test{i}" for i in range(1, 10)]
order_models = ["yolov8n", "yolov8s", "yolov8m"]

lines = []

for test_id in order_tests:
    for model in order_models:
        rows = groups.get((test_id, model), [])
        if not rows:
            lines.append(f"使用映像：{scene_map.get(test_id, test_id)}")
            lines.append(f"使用モデル：{model_map.get(model, model)}")
            lines.append("データ数：0")
            lines.append("最大レイテンシ：-")
            lines.append("最小レイテンシ：-")
            lines.append("レイテンシ中央値：-")
            lines.append("レイテンシ平均値：-")
            lines.append("P95：-")
            lines.append("")
            lines.append("最大FPS：-")
            lines.append("最小FPS：-")
            lines.append("FPS中央値：-")
            lines.append("FPS平均値：-")
            lines.append("P95：-")
            lines.append("")
            lines.append("総検出数：0")
            lines.append("検出種別数：0")
            lines.append("検出物：-")
            lines.append("")
            lines.append("主観的特徴、傾向：データなし")
            lines.append("")
            lines.append("-" * 72)
            lines.append("")
            continue

        lat_rows = [r for r in rows if r["yolo_latency_ms"] is not None and r["video_sec"] is not None]
        fps_rows = [r for r in rows if r["yolo_fps"] is not None and r["video_sec"] is not None]

        lat_vals = sorted(r["yolo_latency_ms"] for r in lat_rows)
        fps_vals = sorted(r["yolo_fps"] for r in fps_rows)

        lat_max_row = max(lat_rows, key=lambda r: r["yolo_latency_ms"]) if lat_rows else None
        lat_min_row = min(lat_rows, key=lambda r: r["yolo_latency_ms"]) if lat_rows else None
        lat_p50 = pct(lat_vals, 0.50)
        lat_p95 = pct(lat_vals, 0.95)
        lat_p50_row = nearest_row(lat_rows, "yolo_latency_ms", lat_p50)
        lat_mean = sum(lat_vals) / len(lat_vals) if lat_vals else None

        fps_max_row = max(fps_rows, key=lambda r: r["yolo_fps"]) if fps_rows else None
        fps_min_row = min(fps_rows, key=lambda r: r["yolo_fps"]) if fps_rows else None
        fps_p50 = pct(fps_vals, 0.50)
        fps_p95 = pct(fps_vals, 0.95)
        fps_p50_row = nearest_row(fps_rows, "yolo_fps", fps_p50)
        fps_mean = sum(fps_vals) / len(fps_vals) if fps_vals else None

        class_totals = Counter()
        total_det = 0
        for r in rows:
            for cls, cnt in r["class_counts"].items():
                if cnt > 0:
                    class_totals[cls] += cnt
                    total_det += cnt

        detected_objects = [cls for cls, cnt in class_totals.most_common() if cnt > 0]
        detected_label = "、".join(detected_objects) if detected_objects else "-"

        def ts(row):
            return "-" if not row else f"{row['video_sec']:.3f} sec"

        def val_ms(row):
            return "-" if not row else f"{row['yolo_latency_ms']:.1f} ms"

        def val_fps(row):
            return "-" if not row else f"{row['yolo_fps']:.3f} fps"

        lines.append(f"使用映像：{scene_map.get(test_id, test_id)}")
        lines.append(f"使用モデル：{model_map.get(model, model)}")
        lines.append(f"データ数：{len(rows)}")
        lines.append(f"最大レイテンシ：{val_ms(lat_max_row)}：{ts(lat_max_row)}")
        lines.append(f"最小レイテンシ：{val_ms(lat_min_row)}：{ts(lat_min_row)}")
        lines.append(f"レイテンシ中央値：{'-' if lat_p50 is None else f'{lat_p50:.1f} ms'}：{ts(lat_p50_row)}")
        lines.append(f"レイテンシ平均値：{'-' if lat_mean is None else f'{lat_mean:.1f} ms'}")
        lines.append(f"P95：{'-' if lat_p95 is None else f'{lat_p95:.1f} ms'}")
        lines.append("")
        lines.append(f"最大FPS：{val_fps(fps_max_row)}：{ts(fps_max_row)}")
        lines.append(f"最小FPS：{val_fps(fps_min_row)}：{ts(fps_min_row)}")
        lines.append(f"FPS中央値：{'-' if fps_p50 is None else f'{fps_p50:.3f} fps'}：{ts(fps_p50_row)}")
        lines.append(f"FPS平均値：{'-' if fps_mean is None else f'{fps_mean:.3f} fps'}")
        lines.append(f"P95：{'-' if fps_p95 is None else f'{fps_p95:.3f} fps'}")
        lines.append("")
        lines.append(f"総検出数：{total_det}")
        lines.append(f"検出種別数：{len(detected_objects)}")
        lines.append(f"検出物：{detected_label}")
        lines.append("")
        lines.append(f"主観的特徴、傾向：{subjective_note(test_id, model, class_totals, lat_mean, fps_mean)}")
        lines.append("")
        lines.append("-" * 72)
        lines.append("")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"created: {OUT}")
