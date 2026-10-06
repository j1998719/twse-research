#!/bin/bash
# 把兩個網頁推到 gh-pages,由 GitHub Pages 對外提供:
#   https://j1998719.github.io/twse-research/                  大戶持股(holders.html)
#   https://j1998719.github.io/twse-research/disposition.html  處置股觀測(index.html)
#
# gh-pages 只放這兩個 HTML,不放任何原始碼。每次都 amend 成同一個 commit
# 再 force push —— 這是部署用的分支,不需要歷史,每天一個 540 KB 的版本
# 累積下來只會讓 clone 變慢。
#
# 用 data/pages 當 worktree(data/ 不進版控),不碰 main 的工作目錄。
set -euo pipefail

cd "$(dirname "$0")"
SITE="data/pages"
#: 建好的檔案 → 網站上的檔名。大戶頁當首頁
PAGES=("data/out/holders.html:index.html" "data/out/index.html:disposition.html")

[[ -f data/out/holders.html ]] || { echo "沒有 data/out/holders.html,先跑 make holders" >&2; exit 1; }

git fetch -q origin gh-pages
if [[ ! -e "$SITE/.git" ]]; then
  git worktree prune
  git worktree add -q -B gh-pages "$SITE" origin/gh-pages
fi

# 單一檔案的 artifact 由平台補上 doctype;直接當網頁用要自己加,
# 否則瀏覽器會用怪異模式排版
FILES=(.nojekyll)
for pair in "${PAGES[@]}"; do
  src="${pair%%:*}" dst="${pair##*:}"
  # 處置股報告要等 build_report 跑過才有;沒有就保留網站上原本那份
  if [[ -f "$src" ]]; then
    { echo '<!doctype html>'; cat "$src"; } > "$SITE/$dst"
    FILES+=("$dst")
  fi
done
touch "$SITE/.nojekyll"

cd "$SITE"
git reset -q --soft origin/gh-pages
git add "${FILES[@]}"
if git diff --cached --quiet origin/gh-pages; then
  echo "網頁沒有變,不用推"
  exit 0
fi
git commit -q --amend -m "Publish the pages ($(date +%F))"
# pre-push 的檢查是給原始碼的:這個 worktree 裡沒有 lefthook.yml,所以 hook 直接放行;
# lefthook.yml 也設了 gh-pages 一律跳過,從 main 的目錄推這個分支時也一樣
git push -q --force origin gh-pages
echo "已推到 gh-pages,約一兩分鐘後上線"
