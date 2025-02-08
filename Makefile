.PHONY: hooks
hooks:
	pre-commit install

.PHONY: check
check:
	ruff check --fix
	ruff format
	pylint src
	mypy --exclude tests/test_package src tests

.PHONY: test
test:
	pytest
