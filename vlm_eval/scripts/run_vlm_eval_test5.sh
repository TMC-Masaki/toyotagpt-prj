#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/mnt/vlm_data/vlm-platform/vlm_eval"
TESTS_CSV="$BASE_DIR/tests.csv"
MODELS_CSV="$BASE_DIR/models.csv"
RAW_DIR="$BASE_DIR/raw_logs"

cleanup() {
  echo
  echo "[cleanup] stopping scheduler..."
  curl -sS -X POST http://127.0.0.1:8000/scheduler/stop >/dev/null || true
}
trap cleanup INT TERM EXIT

cd /mnt/vlm_data/vlm-platform

while IFS=, read -r test_id video_path complexity prompt_file scene_note; do
  if [[ "$test_id" == "test_id" ]]; then
    continue
  fi

  prompt_json="$(python3 - <<PY
import json
from pathlib import Path
print(json.dumps(Path("$prompt_file").read_text(encoding="utf-8")))
PY
)"

  while IFS=, read -r model_key model_name model_label; do
    if [[ "$model_key" == "model_key" ]]; then
      continue
    fi

    stamp="$(date +%Y%m%d_%H%M%S)"
    out="$RAW_DIR/${stamp}_${test_id}_${complexity}_${model_key}.log"

    echo "=================================================="
    echo "RUN test=$test_id complexity=$complexity model=$model_key"
    echo "model_name=$model_name"
    echo "video=$video_path"
    echo "out=$out"
    echo "=================================================="

    curl -sS -X POST http://127.0.0.1:8000/scheduler/stop >/dev/null || true
    sleep 2

    curl -sS -X POST http://127.0.0.1:8000/config \
      -H 'Content-Type: application/json' \
      --data-binary @- <<JSON >/dev/null
{
  "input_type": "video_file",
  "input_path": "$video_path",
  "yolo_enabled": false,
  "evaluation_overlay_enabled": false,
  "evaluation_log_enabled": true,
  "vlm_engine": "hf",
  "vlm_model_name": "$model_name",
  "vlm_max_new_tokens": 40,
  "vlm_emit_interval_sec": 8.0,
  "prompt": $prompt_json
}
JSON

    actual_path="$(curl -sS http://127.0.0.1:8000/config | jq -r '.input.path // ""')"
    actual_engine="$(curl -sS http://127.0.0.1:8000/config | jq -r '.vlm.engine // ""')"
    actual_model="$(curl -sS http://127.0.0.1:8000/config | jq -r '.vlm.model_name // ""')"
    actual_tokens="$(curl -sS http://127.0.0.1:8000/config | jq -r '.vlm.max_new_tokens // ""')"
    actual_overlay="$(curl -sS http://127.0.0.1:8000/config | jq -r '.evaluation.overlay_enabled')"
    actual_yolo="$(curl -sS http://127.0.0.1:8000/config | jq -r '.yolo.enabled')"

    echo "[check] path=$actual_path engine=$actual_engine model=$actual_model max_new_tokens=$actual_tokens overlay=$actual_overlay yolo=$actual_yolo"

    if [[ "$actual_path" != "$video_path" ]]; then
      echo "[ERROR] input.path not applied"
      exit 1
    fi
    if [[ "$actual_engine" != "hf" ]]; then
      echo "[ERROR] vlm.engine is not hf"
      exit 1
    fi
    if [[ "$actual_model" != "$model_name" ]]; then
      echo "[ERROR] vlm.model_name not applied"
      exit 1
    fi
    if [[ "$actual_tokens" != "40" ]]; then
      echo "[ERROR] vlm.max_new_tokens is not 40"
      exit 1
    fi
    if [[ "$actual_overlay" != "false" ]]; then
      echo "[ERROR] overlay is not false"
      exit 1
    fi
    if [[ "$actual_yolo" != "false" ]]; then
      echo "[ERROR] yolo.enabled is not false"
      exit 1
    fi

    since_ts="$(date '+%Y-%m-%dT%H:%M:%S')"

    curl -sS -X POST http://127.0.0.1:8000/scheduler/start >/dev/null || true
    sleep 70
    curl -sS -X POST http://127.0.0.1:8000/scheduler/stop >/dev/null || true
    sleep 2

    sudo docker logs --since "$since_ts" vlm_platform 2>&1 | grep -E 'VLM_SUBMIT|VLM_RESULT|VLM_DISABLED_SKIP|infer error' > "$out" || true

    echo "[saved] $out"
    tail -n 5 "$out" || true
  done < "$MODELS_CSV"
done < "$TESTS_CSV"

trap - INT TERM EXIT
cleanup
echo "DONE"
