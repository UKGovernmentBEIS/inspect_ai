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
- **Typed returns**: When a function returns multiple values, prefer a `NamedTuple` (or small dataclass) over a bare tuple. Adjacent same-typed slots (and `bool`/`int` adjacency) make positional mistakes invisible to the type checker; named fields keep construction sites keyword-checked and give call sites self-documenting attribute access.
- **Naming**: Use snake_case for variables, functions, methods; PascalCase for classes
- **Docstrings**: Google-style docstrings required for public APIs
- **Comments at call sites**: Don't describe what a function does at the call site — the function's name and docstring already document that, and the comment will drift if the function evolves. Document rationale in the function's docstring instead. A call-site comment is appropriate only when the *reason this caller specifically invokes it* isn't obvious from surrounding context (eg. an unusual ordering constraint, a workaround for a known bug in this code path). When in doubt, write the docstring and leave the call site uncommented.
- **Error Handling**: Use appropriate exception types; include context in error messages
- **Testing**: Write tests with pytest; maintain high coverage. See "Testing Async Code" below for async test conventions.

- **Async Concurrency**: Use `inspect_ai._util._async.tg_collect()` instead of `asyncio.gather()` for running concurrent async tasks. Use `inspect_ai.util.collect()` only inside sample subtasks (it adds transcript span grouping).

- **File Paths**: All code that handles file paths must support `s3://` URLs, `file://` URIs, and plain local paths. Use `filesystem()` from `inspect_ai._util.file` for filesystem operations and `local_path()` to resolve `file://` URIs to local paths before passing to APIs that only accept local paths (e.g. `ZipFile`).

- **Respect existing code patterns when modifying files. Run linting before committing changes.

## Testing Async Code

All async test functions automatically run under both asyncio and trio backends via anyio (applied by the `pytest_pycollect_makeitem` hook in `tests/conftest.py`). Trio variants are skipped by default; use `--runtrio` to enable them.

- **Do NOT use `@pytest.mark.asyncio`** — it conflicts with anyio and is blocked by conftest. Just write `async def test_...` and the hook handles the rest.
- **Use `anyio.sleep()` not `asyncio.sleep()`** in tests; `anyio.Event()` not `asyncio.Event()`; `tg_collect()` not `asyncio.gather()`.
- **Use `@skip_if_trio`** (from `test_helpers.utils`) for tests that cannot run under trio (e.g. they test asyncio-specific fallback paths).
- **`@pytest.mark.anyio`** is not required but harmless — use it to signal intentional dual-backend coverage.

## Subsystem Documentation

Additional files provide context when working in specific areas:

- [Sandbox tools: build process, container injection, RPC communication, design patterns](src/inspect_sandbox_tools/CLAUDE.md)

## Design Documentation

`design/` contains architecture notes, subsystem internals, and documentation of repo/CI/development processes and workflows. Browse it before diving into an unfamiliar area.

## Pull requests

Write the PR description using the template at `.github/pull_request_template.md` (fill in its sections — the "This PR contains" checklist, current vs. new behavior, breaking changes, other info).

When asked to open a PR, don't stop at creation — monitor it afterward: watch its CI checks (e.g. `gh pr checks <number> --repo <owner>/<repo> --watch`) until they complete, report the outcome, and investigate/fix any failures. If the branch has fallen behind its base (out of date), update it — merge or rebase the base branch in and push — so CI runs against current code.

### Opening upstream PRs from the meridian fork

This repo is the `meridianlabs-ai/inspect_ai` fork of upstream `UKGovernmentBEIS/inspect_ai` (the `origin` remote). Day-to-day work and PRs target the meridian fork; occasionally a change is also sent upstream.

Opening a PR to upstream from a meridian branch via the GitHub API/CLI needs an explicit `head_repo` — without it GitHub can't resolve the org fork as the PR head and rejects it with `{"field":"head","code":"invalid"}` (or, via `gh pr create`, "Head ref must be a branch / Head sha can't be blank"):

```bash
gh api repos/UKGovernmentBEIS/inspect_ai/pulls -X POST \
  -f title="<title>" -f base="main" \
  -f head="<branch>" -f head_repo="meridianlabs-ai/inspect_ai" \
  -F body=@<body.md>
```

`gh pr create` has no `--head-repo` flag ([cli/cli#6462](https://github.com/cli/cli/issues/6462)), so use the `gh api` form above for fork→upstream PRs. (A personal fork as head resolves without `head_repo`; the org fork requires it.)

When a change is also sent upstream, the upstream PR becomes the system of record: once it's open, close the corresponding PR in the meridian repo, with a close comment linking to the upstream PR.