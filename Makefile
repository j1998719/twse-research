VENV := .venv/bin
# Node 釘在 22 —— npm 在 25 上會崩潰
NODE := PATH="$(HOME)/.nvm/versions/node/v22.23.2/bin:$(PATH)"

# 跟 pre-push 跑的是同一組
check: pyver lint format-check types test dead docs-check web-check

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

report:        ## 重新產生 report.json 並建置網頁
	$(VENV)/python -m src.build_report
	$(NODE) npm run build

holders:       ## 重新產生 bigholders.json 並建置大戶持股頁
	$(VENV)/python -m src.build_bigholders
	$(NODE) npm run build:holders

.PHONY: pyver check fix lint format-check types test dead docs-check web-check report holders
