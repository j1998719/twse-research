VENV := .venv/bin
# Node 釘在 22 —— npm 在 25 上會崩潰
NODE := PATH="$(HOME)/.nvm/versions/node/v22.23.2/bin:$(PATH)"

# 跟 pre-push 跑的是同一組
check: lint format-check types test dead docs-check web-check

fix:
	$(VENV)/ruff check --fix .
	$(VENV)/ruff format .
	$(VENV)/mdformat *.md
	$(NODE) npx biome check --write .

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

.PHONY: check fix lint format-check types test dead docs-check web-check report
