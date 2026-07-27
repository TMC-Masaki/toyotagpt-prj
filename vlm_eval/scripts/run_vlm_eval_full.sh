#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/mnt/vlm_data/vlm-platform/vlm_eval"
TESTS_CSV="$BASE_DIR/tests.csv"
MODELS_CSV="$BASE_DIR/models.csv"
RAW_DIR="$BASE_DIR/raw_logs"

mkdir -p "$RAW_DIR"

cleanup() {
  echo
  echo "[cleanup] stopping scheduler..."
  curl -sS -X POST http://127.0.0.1:8000/scheduler/stop >/dev/null || true
}
trap cleanup INT TERM EXIT

cd /mnt/vlm_data/vlm-platform

# tests.csv:
# test_id,video_path,scene_name,complexity,prompt_file
while IFS=, read -r test_id video_path scene_name complexity prompt_file; do
  if [[ "$test_id" == "test_id" ]]; then
    continue
  fi

  prompt_json="$(python3 - <<PY
import json
from pathlib import Path
print(json.dumps(Path("$prompt_file").read_text(encoding="utf-8")))
PY
)"

  # models.csv:
  # model_key,model_name,family,size_class
  while IFS=, read -r model_key model_name family size_class; do
    if [[ "$model_key" == "model_key" ]]; then
      continue
    fi

    stamp="$(date +%Y%m%d_%H%M%S)"
    out="$RAW_DIR/${stamp}_${test_id}_${complexity}_${model_key}.log"

    echo "=================================================="
    echo "RUN test_id=$test_id scene=$scene_name complexity=$complexity model_key=$model_key"
    echo "model_name=$model_name family=$family size=$size_class"
    echo "video=$video_path"
    echo "prompt=$prompt_file"
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
  "vlm_max_new_tokens": 8,
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
    if [[ "$actual_tokens" != "8" ]]; then
      echo "[ERROR] vlm.max_new_tokens is not 8"
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

    # wait until end-of-video or loop-back to head, with wall-clock timeout
    wait_start="$(date +%s)"
    max_wait_sec=240
    eof_margin_sec=0.7
    last_pos_sec="0"
    seen_progress="0"
    loop_back_threshold_sec="5.0"
    seen_progress_threshold_sec="30.0"

    while true; do
      now="$(date +%s)"
      elapsed="$((now - wait_start))"

      vs_json="$(curl -sS http://127.0.0.1:8000/video/status || true)"
      ready="$(printf '%s' "$vs_json" | jq -r '.ready // false' 2>/dev/null || echo false)"
      pos_sec="$(printf '%s' "$vs_json" | jq -r '.pos_sec // 0' 2>/dev/null || echo 0)"
      dur_sec="$(printf '%s' "$vs_json" | jq -r '.duration_sec // 0' 2>/dev/null || echo 0)"

      echo "[wait] elapsed=${elapsed}s ready=${ready} pos=${pos_sec} dur=${dur_sec}"

      if python3 - <<PY2
pos = float("${pos_sec}")
seen_th = float("${seen_progress_threshold_sec}")
import sys
sys.exit(0 if pos >= seen_th else 1)
PY2
      then
        seen_progress="1"
      fi

      if python3 - <<PY2
pos = float("${pos_sec}")
dur = float("${dur_sec}")
margin = float("${eof_margin_sec}")
import sys
sys.exit(0 if (dur > 0.0 and pos >= max(0.0, dur - margin)) else 1)
PY2
      then
        echo "[wait] reached end-of-video threshold"
        break
      fi

      if python3 - <<PY2
seen = int("${seen_progress}")
pos = float("${pos_sec}")
last = float("${last_pos_sec}")
loop_th = float("${loop_back_threshold_sec}")
import sys
# once we have clearly progressed, detect wraparound to head
sys.exit(0 if (seen == 1 and last > pos and pos <= loop_th) else 1)
PY2
      then
        echo "[wait] detected loop-back after EOF"
        break
      fi

      if [ "${elapsed}" -ge "${max_wait_sec}" ]; then
        echo "[wait] timeout reached: ${max_wait_sec}s"
        break
      fi

      last_pos_sec="${pos_sec}"
      sleep 2
    done

    curl -sS -X POST http://127.0.0.1:8000/scheduler/stop >/dev/null || true
    sleep 2

    sudo docker logs --since "$since_ts" vlm_platform 2>&1 | \
      grep -E 'VLM_SUBMIT|VLM_RESULT|VLM_DISABLED_SKIP|infer error' > "$out" || true

    echo "[saved] $out"
    tail -n 5 "$out" || true
  done < "$MODELS_CSV"
done < "$TESTS_CSV"

trap - INT TERM EXIT
cleanup
echo "DONE"
