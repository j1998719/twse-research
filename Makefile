VENV := .venv/bin

# 跟 pre-push 跑的是同一組
check: lint format-check types test dead docs-check

fix:
	$(VENV)/ruff check --fix .
	$(VENV)/ruff format .
	$(VENV)/mdformat .

lint:          ## 規則檢查
	$(VENV)/ruff check .
format-check:  ## 排版有沒有跑掉
	$(VENV)/ruff format --check .
types:         ## 型別
	$(VENV)/mypy src
test:          ## 測試 + 覆蓋率門檻
	$(VENV)/pytest -q
dead:          ## 沒人用的程式碼
	$(VENV)/vulture
docs-check:    ## markdown 排版
	$(VENV)/mdformat --check .

.PHONY: check fix lint format-check types test dead docs-check
