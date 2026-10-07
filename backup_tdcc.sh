#!/bin/bash
# 把集保股權分散快照備份進 repo 的 snapshots/tdcc/(#40)。
#
# 集保只提供最新一週,錯過就永遠拿不回來 —— 而 data/ 不進版控,快照原本只存在
# 一台 Mac 上。每份快照壓縮後 commit 到 main(Jordan 2026-10-07:直接放 main):
#   * 只 commit snapshots/tdcc/ —— 工作目錄裡其他沒 commit 的改動不會被帶進去
#   * 只增不改:已經備份過的日期不會再寫
#   * push 會跑 main 的 pre-push 檢查;沒過的話 commit 留在本機,下一次執行再推
# 換機器時:把 snapshots/tdcc/*.csv.gz 解壓到 data/raw/tdcc/。
set -euo pipefail

cd "$(dirname "$0")"
SRC="data/raw/tdcc"
DEST="snapshots/tdcc"

ls "$SRC"/dispersion_*.csv >/dev/null 2>&1 || { echo "$SRC 裡沒有快照" >&2; exit 1; }
mkdir -p "$DEST"
added=0
for f in "$SRC"/dispersion_*.csv; do
  out="$DEST/$(basename "$f").gz"
  [[ -e "$out" ]] && continue
  # -n:不寫時間戳,同一份快照壓出來的位元組永遠一樣
  gzip -n -c "$f" > "$out"
  added=$((added + 1))
done

git add "$DEST"
if [[ $added -gt 0 ]]; then
  git commit -q -m "Back up $added TDCC snapshot(s) ($(date +%F))" -- "$DEST"
  echo "備份了 $added 份快照"
else
  echo "沒有新的快照"
fi
# 上一次推不上去的備份 commit 也在這裡補推
if [[ -n "$(git log --oneline origin/main..HEAD -- "$DEST" 2>/dev/null)" ]]; then
  git push -q origin HEAD:main
fi
