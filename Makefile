VENV := .venv/bin

check:
	$(VENV)/ruff check .
	$(VENV)/ruff format --check .
	$(VENV)/mypy src
	$(VENV)/pytest -q

fix:
	$(VENV)/ruff check --fix .
	$(VENV)/ruff format .

lint:
	$(VENV)/ruff check .
test:
	$(VENV)/pytest -q
types:
	$(VENV)/mypy src

.PHONY: check fix lint test types
