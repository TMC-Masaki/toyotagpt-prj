#!/usr/bin/env bash
set -euo pipefail

cd /mnt/vlm_data/vlm-platform

BASE_SCRIPT="vlm_eval/scripts/run_vlm_eval_full.sh"
MODELS_CSV="vlm_eval/models.csv"
TESTS_CSV="vlm_eval/tests.csv"
PROMPT_FILE="vlm_eval/prompts/prompt_event_keys.txt"
RAW_DIR="vlm_eval/raw_logs"

TS="$(date +%Y%m%d_%H%M%S)"
ARCHIVE_DIR="vlm_eval/archive/${TS}_model_first_warmup"
WARMUP_DIR="${ARCHIVE_DIR}/warmup_logs"
mkdir -p "$ARCHIVE_DIR" "$WARMUP_DIR" "$RAW_DIR"

# 現状退避
cp -a "$MODELS_CSV" "${ARCHIVE_DIR}/models.csv.bak" 2>/dev/null || true
cp -a "$TESTS_CSV" "${ARCHIVE_DIR}/tests.csv.bak" 2>/dev/null || true
cp -a "$PROMPT_FILE" "${ARCHIVE_DIR}/prompt_event_keys.txt.bak" 2>/dev/null || true
cp -a "$BASE_SCRIPT" "${ARCHIVE_DIR}/run_vlm_eval_full.sh.bak" 2>/dev/null || true

# 既存 raw_logs を退避
find "$RAW_DIR" -maxdepth 1 -name '*.log' -exec mv {} "$ARCHIVE_DIR"/ \; 2>/dev/null || true

# 今回の固定プロンプト
cat > "$PROMPT_FILE" <<'EOF'
目的：
現在の映像から、該当するイベントキーのみを抽出する。

使用可能なイベントキー：
road_depression
fallen_object
road_work
traffic_jam
accident
blind_spot
pedestrian_attention
intersection_complexity
none

各イベントキーの意味：
road_depression = 陥没 / 穴 / 路面損傷 / 路面の穴 / 道路陥没
fallen_object = 落下物 / 障害物 / 路上障害物 / 散乱物 / 荷物
road_work = 工事 / 工事中 / 車線規制 / 規制 / コーン / ポール
traffic_jam = 渋滞 / 混雑 / 車列 / 停滞 / 流れが悪い
accident = 事故 / 接触 / 追突 / 衝突事故 / 故障車
blind_spot = 死角 / 見通しが悪い / 見えにくい / 陰 / 遮られて / 遮蔽
pedestrian_attention = 歩行者 / 横断 / 飛び出し / 自転車 / 二輪
intersection_complexity = 交差点 / 合流 / 分岐 / 右左折 / 信号

判定ルール：
- 映像に該当するものだけを選ぶこと
- 該当がなければ none を返すこと
- 必ず上記キーだけを使うこと
- 説明文は禁止
- 日本語禁止
- 句読点禁止
- 出力は1行のみ
- 最大2件まで
- 重要度が高いものを優先すること

出力形式：
event_name1,event_name2

例：
road_work,traffic_jam
none
EOF

# 本番用 tests.csv
write_full_tests() {
cat > "$TESTS_CSV" <<'CSV'
test_id,video_path,scene_name,complexity,prompt_file
test2,/data/test2.mp4,test2,event,vlm_eval/prompts/prompt_event_keys.txt
test4,/data/test4.mp4,test4,event,vlm_eval/prompts/prompt_event_keys.txt
test6,/data/test6.mp4,test6,event,vlm_eval/prompts/prompt_event_keys.txt
test7,/data/test7.mp4,test7,event,vlm_eval/prompts/prompt_event_keys.txt
CSV
}

# ウォームアップ用 tests.csv
write_warmup_test() {
cat > "$TESTS_CSV" <<'CSV'
test_id,video_path,scene_name,complexity,prompt_file
warmup_test2,/data/test2.mp4,test2,event,vlm_eval/prompts/prompt_event_keys.txt
CSV
}

# モデル1件用 models.csv
write_one_model() {
  local model_key="$1"
  local model_name="$2"
  local family="$3"
  local size_class="$4"
  cat > "$MODELS_CSV" <<CSV
model_key,model_name,family,size_class
${model_key},${model_name},${family},${size_class}
CSV
}

echo "===== precheck ====="
grep -nE 'vlm_max_new_tokens|yolo|overlay' "$BASE_SCRIPT" || true
echo
echo "archive_dir=$ARCHIVE_DIR"
echo

# Jetson clocks 固定（失敗しても続行）
sudo jetson_clocks 2>/dev/null || true

run_model() {
  local model_key="$1"
  local model_name="$2"
  local family="$3"
  local size_class="$4"

  echo "=================================================="
  echo "MODEL START: $model_key"
  echo "=================================================="

  write_one_model "$model_key" "$model_name" "$family" "$size_class"

  echo "--- warmup: $model_key ---"
  write_warmup_test
  bash "$BASE_SCRIPT" || true

  # warmupログを退避して本番から除外
  find "$RAW_DIR" -maxdepth 1 -name "*warmup_test2*_${model_key}.log" -exec mv {} "$WARMUP_DIR"/ \; 2>/dev/null || true

  echo "--- main run: $model_key ---"
  write_full_tests
  bash "$BASE_SCRIPT"

  echo "--- done: $model_key ---"
  ls -1 "$RAW_DIR"/*_${model_key}.log 2>/dev/null | sed 's#^.*/##' | sort || true
  echo
}

run_model "qwen2vl_7b" "Qwen/Qwen2-VL-7B-Instruct" "Qwen" "7B"
run_model "qwen25_3b" "Qwen/Qwen2.5-VL-3B-Instruct" "Qwen" "3B"
run_model "qwen25_7b" "Qwen/Qwen2.5-VL-7B-Instruct" "Qwen" "7B"
run_model "smolvlm" "HuggingFaceTB/SmolVLM-Instruct" "SmolVLM" "Instruct"

# 最後に本番用CSVへ戻す
cat > "$MODELS_CSV" <<'CSV'
model_key,model_name,family,size_class
qwen2vl_7b,Qwen/Qwen2-VL-7B-Instruct,Qwen,7B
qwen25_3b,Qwen/Qwen2.5-VL-3B-Instruct,Qwen,3B
qwen25_7b,Qwen/Qwen2.5-VL-7B-Instruct,Qwen,7B
smolvlm,HuggingFaceTB/SmolVLM-Instruct,SmolVLM,Instruct
CSV

write_full_tests

echo "===== finished ====="
echo "archive_dir=$ARCHIVE_DIR"
echo "warmup_dir=$WARMUP_DIR"
echo
echo "raw_logs count:"
ls -1 "$RAW_DIR"/*.log | wc -l
echo
echo "warmup_logs:"
ls -1 "$WARMUP_DIR" 2>/dev/null || true
