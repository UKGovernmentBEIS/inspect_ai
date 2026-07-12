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
- **Testing**: Write tests with pytest; maintain high coverage. See "Testing Async Code" below for async test conventions. Prefer adding tests to an existing test file covering the same area (e.g. eval-level behavior → `tests/test_eval.py`) rather than creating a new file; only add a new file when no existing one is a reasonable fit.

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

For changes to product functionality (not test-only or build-only changes), add a CHANGELOG entry: a single-line, single-sentence item in the `## Unreleased` section at the top of `CHANGELOG.md` (create that section if it doesn't exist), grouped with similar existing items when there are any, otherwise appended to the list. Keep it short (~25 words): state only the user-visible behavior change — what a user can now do or observe — not the mechanism, internal names, or design rationale (those belong in the PR description and `design/` docs). After updating a branch against its base, re-check that the entry is still under `## Unreleased` — a merge can relocate it under a released heading; move it back if so.

Never change a submodule gitlink (e.g. `src/inspect_ai/_view/ts-mono`) unless the task is about that submodule. After any merge/rebase, check `git status`; if it shows the submodule modified, reset the pointer to the base and commit: `git checkout origin/main -- src/inspect_ai/_view/ts-mono`. (`git submodule update` will NOT fix this — it syncs the working tree to the already-recorded pointer, not the reverse.)

### Opening an upstream PR from an org fork

Before opening the PR, sync the branch with upstream `main` (`git fetch origin main && git merge origin/main`, resolving any conflicts) and push. Otherwise the PR can open with conflicts against its base, and CHANGELOG entries in particular almost always conflict.

Opening a PR from an organization fork to its upstream via the GitHub API/CLI needs an explicit `head_repo` — without it GitHub can't resolve the org fork as the PR head and rejects it with `{"field":"head","code":"invalid"}` (an org fork requires `head_repo`; a personal fork resolves without it). `gh pr create` has no `--head-repo` flag ([cli/cli#6462](https://github.com/cli/cli/issues/6462)), so use `gh api` — e.g. from the `meridianlabs-ai/inspect_ai` fork to upstream `UKGovernmentBEIS/inspect_ai`:

```bash
gh api repos/UKGovernmentBEIS/inspect_ai/pulls -X POST \
  -f title="<title>" -f base="main" \
  -f head="<branch>" -f head_repo="meridianlabs-ai/inspect_ai" \
  -F body=@<body.md>
```

Once the upstream PR is open it's the system of record: close the corresponding org-fork PR, with a close comment linking to the upstream PR.