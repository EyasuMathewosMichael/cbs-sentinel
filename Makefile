.PHONY: install test lint typecheck check

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	ruff check .

typecheck:
	mypy src

check: test lint typecheck
