#!/bin/bash
# 每日更新:抓資料 → 算統計 → 建置網頁。
#
# 設計成可以重複執行 —— 抓過的日子有快取,重跑很快。
# 任何一步失敗就中止,不要拿壞掉的資料蓋掉好的。
set -euo pipefail

cd "$(dirname "$0")"
export PATH="$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"

TODAY=$(date +%Y-%m-%d)
LOG="data/update.log"
mkdir -p data

say() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$1" | tee -a "$LOG"; }

say "=== 更新開始 $TODAY ==="

say "抓公告(注意股與處置)"
.venv/bin/python -m src.fetch_all 2020-01-01 "$TODAY" >>"$LOG" 2>&1

say "抓每日行情"
.venv/bin/python -m src.fetch_prices 2020-01-01 "$TODAY" >>"$LOG" 2>&1

say "抓三大法人"
.venv/bin/python -m src.fetch_chips 2020-01-01 "$TODAY" >>"$LOG" 2>&1

say "算統計"
.venv/bin/python -m src.build_report >>"$LOG" 2>&1

say "建置網頁"
npm run build >>"$LOG" 2>&1

BACKTESTED=$(.venv/bin/python -c "import json;print(json.load(open('data/out/report.json'))['coverage']['backtested'])")
say "=== 完成:$BACKTESTED 筆可回測事件,產出 data/out/index.html ==="
