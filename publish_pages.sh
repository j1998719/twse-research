#!/bin/bash
# 把大戶持股頁推到 gh-pages,由 GitHub Pages 對外提供:
#   https://j1998719.github.io/twse-research/
#
# gh-pages 只放 index.html,不放任何原始碼。每次都 amend 成同一個 commit
# 再 force push —— 這是部署用的分支,不需要歷史,每天一個 540 KB 的版本
# 累積下來只會讓 clone 變慢。
#
# 用 data/pages 當 worktree(data/ 不進版控),不碰 main 的工作目錄。
set -euo pipefail

cd "$(dirname "$0")"
PAGE="data/out/holders.html"
SITE="data/pages"

[[ -f "$PAGE" ]] || { echo "沒有 $PAGE,先跑 make holders" >&2; exit 1; }

git fetch -q origin gh-pages
if [[ ! -e "$SITE/.git" ]]; then
  git worktree prune
  git worktree add -q -B gh-pages "$SITE" origin/gh-pages
fi

# 單一檔案的 artifact 由平台補上 doctype;直接當網頁用要自己加,
# 否則瀏覽器會用怪異模式排版
{ echo '<!doctype html>'; cat "$PAGE"; } > "$SITE/index.html"
touch "$SITE/.nojekyll"

cd "$SITE"
git reset -q --soft origin/gh-pages
if git diff --quiet origin/gh-pages -- index.html; then
  echo "網頁沒有變,不用推"
  exit 0
fi
git add index.html .nojekyll
git commit -q --amend -m "Publish the big-holder page ($(date +%F))"
# pre-push 的檢查是給原始碼的:這個 worktree 裡沒有 lefthook.yml,所以 hook 直接放行;
# lefthook.yml 也設了 gh-pages 一律跳過,從 main 的目錄推這個分支時也一樣
git push -q --force origin gh-pages
echo "已推到 gh-pages,約一兩分鐘後上線"
