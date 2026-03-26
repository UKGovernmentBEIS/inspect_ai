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

.PHONY: test
test:
	pytest
