.PHONY: test lint check-sources init-db
test:
	python -m pytest -q
lint:
	python -m ruff check .
	python -m ruff format --check .
check-sources:
	python -m scripts.data_source_check
init-db:
	python -m scripts.init_db

