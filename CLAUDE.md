# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build/Lint/Test Commands
- Run all tests: `pytest`
- Run a single test: `pytest tests/path/to/test_file.py::test_function_name -v`
- Format code: `ruff format`
- Lint code: `ruff check --fix`
- Type check: `mypy --exclude tests/test_package src tests`

## Code Style Guidelines
- **Formatting**: Follow Google style convention. Use ruff for formatting
- **Imports**: Use isort order (enforced by ruff)
- **Types**: Strict typing is required. All functions must have type annotations
- **Naming**: Use snake_case for variables, functions, methods; PascalCase for classes
- **Docstrings**: Google-style docstrings required for public APIs
- **Error Handling**: Use appropriate exception types; include context in error messages
- **Testing**: Write tests with pytest; maintain high coverage. See "Testing Async Code" below for async test conventions.

- **Async Concurrency**: Use `inspect_ai._util._async.tg_collect()` instead of `asyncio.gather()` for running concurrent async tasks. Use `inspect_ai.util.collect()` only inside sample subtasks (it adds transcript span grouping).

## Testing Async Code

All async test functions automatically run under both asyncio and trio backends via anyio (applied by the `pytest_pycollect_makeitem` hook in `tests/conftest.py`). Trio variants are skipped by default; use `--runtrio` to enable them.

- **Do NOT use `@pytest.mark.asyncio`** — it conflicts with anyio and is blocked by conftest. Just write `async def test_...` and the hook handles the rest.
- **Use `anyio.sleep()` not `asyncio.sleep()`** in tests; `anyio.Event()` not `asyncio.Event()`; `tg_collect()` not `asyncio.gather()`.
- **Use `@skip_if_trio`** (from `test_helpers.utils`) for tests that cannot run under trio (e.g. they test asyncio-specific fallback paths).
- **`@pytest.mark.anyio`** is not required but harmless — use it to signal intentional dual-backend coverage.

Respect existing code patterns when modifying files. Run linting before committing changes.

## Subsystem Documentation

Additional files provide context when working in specific areas:

- [Sandbox tools: build process, container injection, RPC communication, design patterns](src/inspect_sandbox_tools/CLAUDE.md)
- [View UI (TypeScript): build/lint/test commands for the frontend](src/inspect_ai/_view/www/CLAUDE.md)

## Design Documentation

- [Model Proxy Lifecycle: startup, communication, and termination flow](design/model-proxy-lifecycle.md)
- [Timezone Handling Architecture: principles and patterns for temporal data](design/temporal-data-handling.md)