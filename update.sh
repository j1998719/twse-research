#!/bin/bash
# 每日更新:抓資料 → 算統計 → 建置網頁。
#
# 設計成可以重複執行 —— 抓過的日子有快取,重跑很快。
# 任何一步失敗就中止,不要拿壞掉的資料蓋掉好的。
set -uo pipefail

cd "$(dirname "$0")"
export PATH="$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"

TODAY=$(date +%Y-%m-%d)
LOG="data/update.log"
#: 上次成功的時間戳。排程靜默死亡時,這是唯一看得出來的東西
STAMP="data/last_success"
mkdir -p data

say() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$1" | tee -a "$LOG"; }

# 抓取失敗只記錄、不中斷。每一段抓取都是獨立的,而且都有快取 ——
# 一個來源掛掉不該讓其他來源也跳過,尤其集保快照錯過就永遠補不回來。
# 真正該擋的是 build_report:資料不齊時不要拿它蓋掉好的報告。
step() {
  local what="$1"; shift
  say "$what"
  if ! "$@" >>"$LOG" 2>&1; then
    say "  !! $what 失敗,繼續跑其他步驟"
    FAILED="$FAILED $what"
  fi
}
FAILED=""

# 上次成功是什麼時候。排程在睡著的機器上會整天不觸發,而失敗完全沒有痕跡
# —— 2026-09-24 的排程掛掉之後四天沒人發現,資料就停在那裡
if [[ -f "$STAMP" ]]; then
  LAST=$(cat "$STAMP")
  AGE=$(( ($(date +%s) - $(date -j -f "%Y-%m-%dT%H:%M:%S" "$LAST" +%s 2>/dev/null || echo 0)) / 86400 ))
  say "=== 更新開始 $TODAY(上次成功 $LAST,$AGE 天前)==="
else
  say "=== 更新開始 $TODAY(沒有成功紀錄)==="
fi

step "抓公告(注意股與處置)" .venv/bin/python -m src.fetch_all 2020-01-01 "$TODAY"
step "抓每日行情" .venv/bin/python -m src.fetch_prices 2020-01-01 "$TODAY"
step "抓三大法人" .venv/bin/python -m src.fetch_chips 2020-01-01 "$TODAY"

# 集保快照只有最新一週,錯過就永遠補不回來,所以放在算統計之前 ——
# 就算後面的步驟壞了,這一週的股權分散還是存下來了。
step "存集保股權分散快照" .venv/bin/python -m src.fetch_tdcc

# 上櫃佔了可回測事件的 58%(1,314 / 2,265)。漏掉它的話 build_report 會拿
# 舊的上櫃資料去算,而且不會有任何跡象 —— 抓過的日子有快取,所以每天跑只會
# 真的去抓新的那一天
step "抓上櫃行情與處置公告" .venv/bin/python -m src.fetch_tpex 2020-01-01 "$TODAY"

# 這兩步要擋:資料不齊時不要拿壞掉的結果蓋掉好的報告
say "算統計"
if ! .venv/bin/python -m src.build_report >>"$LOG" 2>&1; then
  say "!! 算統計失敗,保留上一份報告不覆蓋。失敗的抓取:${FAILED:-無}"
  exit 1
fi

say "建置網頁"
if ! npm run build >>"$LOG" 2>&1; then
  say "!! 建置網頁失敗。失敗的抓取:${FAILED:-無}"
  exit 1
fi

SUMMARY=$(.venv/bin/python -c "
import json
c = json.load(open('data/out/report.json'))['coverage']
by = c.get('markets') or {}
parts = ' '.join(f\"{k}:{v['backtested']}\" for k, v in sorted(by.items()))
print(f\"{c['backtested']} 筆可回測事件({parts})、{c.get('codes')} 檔\")
")
if [[ -n "$FAILED" ]]; then
  say "!! 有抓取失敗:$FAILED —— 報告是用現有資料算的"
fi
date +%Y-%m-%dT%H:%M:%S > "$STAMP"
say "=== 完成:$SUMMARY,產出 data/out/index.html ==="
