#!/bin/bash
# 每日更新:抓資料 → 算統計 → 建置網頁(處置股觀測、大戶持股排行)。
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

# 同時只跑一份。第一次補資料要好幾個小時,可能跨過下一次 cron;兩份同時寫
# 同一批 CSV 會互相蓋掉。鎖裡記 PID —— 被 kill -9 時 trap 不會執行,留下的
# 鎖要能認出是死的,不然之後每天都會被它擋住
LOCK="data/update.lock"
if [[ -f "$LOCK" ]] && kill -0 "$(cat "$LOCK")" 2>/dev/null; then
  say "另一份 update.sh(PID $(cat "$LOCK"))還在跑,這次跳過"
  exit 0
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

# 發布放在最後,處置股報告建好之後才推;報告那一步失敗時大戶頁照樣發布。
# 集保快照的備份(#40)也在最後:它推 main 時會跑 pre-push 的測試,其中有比對
# report.json 和最新資料的,報告重建之前推一定不過。報告失敗時照樣備份 ——
# 快照是唯一拿不回來的資料;那次推不上去的話,下一次執行會補推
publish() {
  step "發布網頁到 GitHub Pages" ./publish_pages.sh
  step "備份集保快照" ./backup_tdcc.sh
}

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
# 往回補集保的單檔歷史(#49:過去 n 週大戶增加、股價沒動)。一檔一週兩個請求,
# 一次補不完,每天只花 20 分鐘,下一次從還缺的地方接著補,最新的週先補
step "往回補集保單檔歷史" .venv/bin/python -m src.fetch_tdcc_history --weeks 8 --minutes 20

# 上櫃佔了可回測事件的 58%(1,314 / 2,265)。漏掉它的話 build_report 會拿
# 舊的上櫃資料去算,而且不會有任何跡象 —— 抓過的日子有快取,所以每天跑只會
# 真的去抓新的那一天
step "抓上櫃行情與處置公告" .venv/bin/python -m src.fetch_tpex 2020-01-01 "$TODAY"

# 大戶持股頁跟處置股報告互不相干,所以放在會中止的那兩步之前,
# 而且失敗只記錄 —— 處置股報告壞掉不該讓大戶頁也停在舊的那一天
# 長期均線:2016 起的日線和還原因子。第一次跑要補 2016-2019 約一千個交易日,
# 之後只抓新的那一天。fetch_actions 有任何一段失敗就不寫檔,保留上一份
step "抓長期日線" .venv/bin/python -m src.fetch_history 2016-01-01 "$TODAY"
step "抓除權息、減資、變更面額" .venv/bin/python -m src.fetch_actions 2016-01-01 "$TODAY"
# 籌碼:融資融券(上市 + 上櫃)、上櫃三大法人。上市三大法人在上面「抓三大法人」
step "抓融資融券" .venv/bin/python -m src.fetch_margin 2020-01-01 "$TODAY"
step "抓上櫃三大法人" .venv/bin/python -m src.fetch_otc_chips 2020-01-01 "$TODAY"
step "算大戶持股" .venv/bin/python -m src.build_bigholders
step "建置大戶持股頁" npm run build:holders

# 這兩步要擋:資料不齊時不要拿壞掉的結果蓋掉好的報告
say "算統計"
if ! .venv/bin/python -m src.build_report >>"$LOG" 2>&1; then
  say "!! 算統計失敗,保留上一份報告不覆蓋。失敗的抓取:${FAILED:-無}"
  publish
  exit 1
fi

say "建置網頁"
if ! npm run build >>"$LOG" 2>&1; then
  say "!! 建置網頁失敗。失敗的抓取:${FAILED:-無}"
  publish
  exit 1
fi

SUMMARY=$(.venv/bin/python -c "
import json
c = json.load(open('data/out/report.json'))['coverage']
by = c.get('markets') or {}
parts = ' '.join(f\"{k}:{v['studied']}\" for k, v in sorted(by.items()))
print(f\"{c['studied']} 筆納入研究的事件({parts})、{c.get('codes')} 檔\")
")
if [[ -n "$FAILED" ]]; then
  say "!! 有抓取失敗:$FAILED —— 報告是用現有資料算的"
fi
publish
date +%Y-%m-%dT%H:%M:%S > "$STAMP"
say "=== 完成:$SUMMARY,產出 data/out/index.html ==="
