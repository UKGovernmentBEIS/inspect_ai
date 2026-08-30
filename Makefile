.PHONY: hooks
hooks:
	pre-commit install

.PHONY: ruff
ruff:
	ruff check --fix
	ruff format
	cd src/inspect_tool_support/src && ruff check --fix
	cd src/inspect_tool_support/src && ruff format

.PHONY: mypy
mypy:
	mypy --exclude tests/test_package src tests

.PHONY: check
check: ruff mypy

.PHONY: suppressions-check
suppressions-check:
	python3 .github/scripts/check_suppressions.py

.PHONY: suppressions-update
suppressions-update:
	python3 .github/scripts/check_suppressions.py --update

.PHONY: test
test:
	pytest

.PHONY: test-parallel
test-parallel:
	pytest -n auto

include docs/evals/inspect-evals.mk
