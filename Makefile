VENV := .venv/bin
# Node 釘在 22 —— npm 在 25 上會崩潰
NODE := PATH="$(HOME)/.nvm/versions/node/v22.23.2/bin:$(PATH)"

# 跟 pre-push 跑的是同一組
check: pyver lint format-check types test dead docs-check web-check e2e

fix:
	$(VENV)/ruff check --fix .
	$(VENV)/ruff format .
	$(VENV)/mdformat *.md
	$(NODE) npx biome check --write .

pyver:         ## .venv 的 Python 要跟 .python-version 同一版
	@want=$$(cat .python-version); got=$$($(VENV)/python -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")'); \
	if [ "$$want" != "$$got" ]; then echo ".venv 是 Python $$got,.python-version 要 $$want —— 用 uv venv 重建"; exit 1; fi
lint:          ## Python 規則
	$(VENV)/ruff check .
format-check:  ## Python 排版
	$(VENV)/ruff format --check .
types:         ## Python 型別
	$(VENV)/mypy src
test:          ## 測試 + 覆蓋率門檻
	$(VENV)/pytest -q
dead:          ## 沒人用的程式碼
	$(VENV)/vulture
docs-check:    ## markdown 排版
	$(VENV)/mdformat --check *.md
web-check:     ## 網頁的 lint 與型別
	$(NODE) npx biome check .
	$(NODE) npx tsc --noEmit

e2e:           ## 瀏覽器測試:假資料建頁面、無頭 Chromium 操作、截圖在 test-results/screens/
	$(NODE) npx playwright install chromium >/dev/null
	$(NODE) npm run -s e2e

report:        ## 重新產生 report.json 並建置網頁
	$(VENV)/python -m src.build_report
	$(NODE) npm run build

holders:       ## 重新產生 bigholders.json 並建置大戶持股頁
	$(VENV)/python -m src.build_bigholders
	$(NODE) npm run build:holders

PLIST := com.j1998719.twse-research.update.plist
schedule:      ## 安裝每天 08:00 的 launchd 排程(#37)
	mkdir -p $(HOME)/Library/LaunchAgents
	cp ops/$(PLIST) $(HOME)/Library/LaunchAgents/$(PLIST)
	launchctl bootout gui/$$(id -u)/$(basename $(PLIST)) 2>/dev/null || true
	launchctl bootstrap gui/$$(id -u) $(HOME)/Library/LaunchAgents/$(PLIST)

.PHONY: pyver check fix lint format-check types test dead docs-check web-check e2e report holders schedule
