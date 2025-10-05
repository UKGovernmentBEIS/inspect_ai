.PHONY: hooks
hooks:
	pre-commit install

.PHONY: ruff
ruff:
	ruff check --fix
	ruff format

.PHONY: mypy
mypy:
	mypy --exclude tests/test_package src tests

.PHONY: check
check: ruff mypy
	pylint src

.PHONY: test
test:
	pytest
