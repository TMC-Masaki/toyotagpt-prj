#!/usr/bin/env bash
set -euo pipefail

URL="${1:-http://localhost:8000/run_once}"
INTERVAL="${2:-2.0}"          # 叩く周期（秒）
MIN_SPEAK="${3:-5.0}"         # 最短読み上げ間隔（秒）
DETAIL="${4:-medium}"         # 今は未使用（将来用）

last_spoken=0

echo "[speak_loop] URL=$URL interval=$INTERVAL min_speak=$MIN_SPEAK"

while true; do
  # 推論実行（サーバはログ保存もしてくれる）
  json="$(curl -s -X POST "$URL" || true)"
  if [[ -z "${json}" ]]; then
    echo "[speak_loop] empty response"
    sleep "$INTERVAL"
    continue
  fi

  # textだけ抜く（pythonで堅牢に）
  text="$(python3 - <<'PY'
import sys, json
try:
  j = json.loads(sys.stdin.read())
  print(j.get("result", {}).get("text", ""))
except Exception:
  print("")
PY
<<<"$json")"

  # 読み上げ（最短間隔MIN_SPEAKで抑制）
  now="$(python3 - <<'PY'
import time
print(time.time())
PY
)"
  # bashで浮動小数比較が面倒なのでpythonで判定
  should="$(python3 - <<PY
import time
last=float("$last_spoken")
now=float("$now")
min_s=float("$MIN_SPEAK")
print("1" if now-last>=min_s else "0")
PY
)"
  if [[ -n "$text" && "$should" == "1" ]]; then
    echo "[speak_loop] speak: $text"
    say "$text" || true
    last_spoken="$now"
  fi

  sleep "$INTERVAL"
done
