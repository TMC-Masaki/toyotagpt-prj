#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/mnt/vlm_data/vlm-platform/yolo_eval"
TESTS_CSV="$BASE_DIR/tests.csv"
RAW_DIR="$BASE_DIR/raw_logs"

MODELS=("yolov8n.pt" "yolov8s.pt" "yolov8m.pt")

cleanup() {
  echo
  echo "[cleanup] stopping scheduler..."
  curl -sS -X POST http://127.0.0.1:8000/scheduler/stop >/dev/null || true
}
trap cleanup INT TERM EXIT

cd /mnt/vlm_data/vlm-platform

while IFS=, read -r test_id video_path scene_note; do
  if [[ "$test_id" == "test_id" ]]; then
    continue
  fi

  for model in "${MODELS[@]}"; do
    stamp=$(date +%Y%m%d_%H%M%S)
    safe_model="${model%.pt}"
    out="$RAW_DIR/${stamp}_${test_id}_${safe_model}.log"

    echo "=================================================="
    echo "RUN test=$test_id model=$model video=$video_path"
    echo "OUT $out"
    echo "=================================================="

    curl -sS -X POST http://127.0.0.1:8000/scheduler/stop >/dev/null || true
    sleep 2

    curl -sS -X POST http://127.0.0.1:8000/config \
      -H 'Content-Type: application/json' \
      -d "{
        \"input_type\": \"video_file\",
        \"input_path\": \"$video_path\",
        \"yolo_enabled\": true,
        \"yolo_model_name\": \"$model\",
        \"yolo_imgsz\": 416,
        \"yolo_conf\": 0.25,
        \"yolo_iou\": 0.45,
        \"yolo_preview_hz\": 2.5,
        \"vlm_engine\": \"stub\",
        \"evaluation_log_enabled\": true,
        \"evaluation_overlay_enabled\": false
      }" >/dev/null

    actual_path="$(curl -sS http://127.0.0.1:8000/config | jq -r '.input.path // ""')"
    actual_overlay="$(curl -sS http://127.0.0.1:8000/config | jq -r '.evaluation.overlay_enabled')"
    actual_vlm="$(curl -sS http://127.0.0.1:8000/config | jq -r '.vlm.engine // ""')"

    echo "[check] path=$actual_path overlay=$actual_overlay vlm_engine=$actual_vlm"

    if [[ "$actual_path" != "$video_path" ]]; then
      echo "[ERROR] input.path not applied expected=$video_path actual=$actual_path"
      exit 1
    fi
    if [[ "$actual_overlay" != "false" ]]; then
      echo "[ERROR] overlay is not false actual=$actual_overlay"
      exit 1
    fi
    if [[ "$actual_vlm" != "stub" ]]; then
      echo "[ERROR] vlm.engine is not stub actual=$actual_vlm"
      exit 1
    fi

    since_ts="$(date '+%Y-%m-%dT%H:%M:%S')"

    curl -sS -X POST http://127.0.0.1:8000/scheduler/start >/dev/null || true

    # 95秒だけ回す。Ctrl+Cなら trap で止まる
    sleep 95

    curl -sS -X POST http://127.0.0.1:8000/scheduler/stop >/dev/null || true
    sleep 2

    sudo docker logs --since "$since_ts" vlm_platform 2>&1 | grep 'event=YOLO_RESULT' > "$out" || true

    echo "[saved] $out"
  done
done < "$TESTS_CSV"

trap - INT TERM EXIT
cleanup
echo "DONE"
