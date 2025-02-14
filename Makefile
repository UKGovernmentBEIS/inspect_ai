.PHONY: hooks
hooks:
	pre-commit install

.PHONY: check
check: check-ruff check-pylint check-mypy

.PHONY: check-ruff
check-ruff:
	ruff check --fix
	ruff format

.PHONY: check-pylint
check-pylint:
	pylint src

.PHONY: check-mypy
check-mypy:
	mypy --exclude tests/test_package src tests

.PHONY: test
test:
	pytest
