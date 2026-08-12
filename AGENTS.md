# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Contribution policy — required checks before opening a PR

These rules are mandatory for AI coding agents (Claude Code, Codex, Cursor,
Devin, and similar) preparing contributions. Human contributors: see
[CONTRIBUTING.md](CONTRIBUTING.md). A deterministic gate enforces them.

1. **Tier check.** Does the account you are operating for have at least one
   merged non-trivial PR in this repository (trivial documentation fixes do
   not count)? If not, a PR requires a linked issue labeled `accepted`.
   Without one, your PR will be closed automatically. Do not open it.
2. **Self-filed issues need acceptance.** An issue filed by the same account
   the PR comes from does not by itself establish demand. Unless the account
   is a qualified contributor (recorded in `.github/qualified.yml`), a
   non-trivial PR addressing a self-filed issue requires that issue to be
   labeled `accepted` by a maintainer first — whatever the account's tier.
   If it isn't labeled yet: file your evidence on the issue and stop; open
   the PR only after a maintainer accepts it.
3. **Deferred check.** Is the issue you are addressing labeled `deferred`?
   The project has decided not to prioritize it. Do not open a PR against it
   (it will be closed automatically, whatever your account's tier). If you
   have new evidence or demand, comment on the issue and stop.
4. **Duplicate check.** Search open PRs (and the linked issue's existing
   PRs) for work addressing the same problem. If a PR already exists, do not
   open a competing one — review it or comment there instead. If you believe
   your approach is materially better, make that case in a comment on the
   existing PR and wait for a maintainer's direction; if invited to proceed,
   link the two PRs in your description.
5. **Trivial-fix exception.** Documentation-only fixes (typo, broken link;
   docs files only, under 25 changed lines) may be opened directly by anyone.
6. **New functionality defaults to an extension, not core.** Do not open
   unrequested PRs adding functionality — providers, tools, scorers, metrics,
   solvers, storage backends, example evals. Some of these do belong in core,
   but that is a maintainer decision made in an issue: if an accepted issue
   calls for it in core, build it there. Otherwise the path is a separate
   extension package (see https://inspect.aisi.org.uk/extensions.html),
   optionally with a one-line PR adding it to the extensions listing.
   Unrequested additions to core are closed without detailed review.
7. **Value re-evaluation.** Before opening any PR, objectively re-assess it:
   does it fix a demonstrated problem, with evidence (a reproduction or a
   failing test)? If the need is speculative or the fix unverified, do not
   proceed. File an issue with your evidence instead.

If you do open a PR: reference the accepted issue (`Fixes #NNN`); run
`make check` and `make test` and report results honestly; disclose agent
involvement in the PR description; one issue per PR — no bundled drive-by
changes; respect the open-PR limit (4 per account without write access).

As part of disclosing agent involvement, include an `### Agent review`
section in the PR description summarizing pre-PR review passes: what
model/tool reviewed and whether the review ran in a fresh context and/or
used a different model from the author, how many passes, and the findings
— issues found, which
were fixed, and which were dismissed with a one-line reason each. Multiple
passes, each in a fresh context, often catch issues a single pass misses —
prefer that for non-trivial changes. We'd also prefer review passes run on
a strong (frontier-class) model: in our experience, reviews from small
fast-tier models rarely surface real issues, and maintainers weight the
disclosed reviewer model and pass count when deciding how much independent
review a PR still needs. If no
review pass was run, say so explicitly. Never report a review that didn't
happen — a fabricated or content-free review claim ("reviewed, looks good")
is worse than disclosing none. Example:

```
### Agent review
- Reviewer: Claude Opus 5 via /code-review (fresh context), 2 passes
- Findings: 3 — 2 fixed, 1 dismissed (flagged a missing None check that is
  guarded upstream)
```

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
- **Comment length**: Sometimes comments in the code are useful to explain the rationale or context of a particular set of code. When this is necessary, be concise. Preserve the important concept and information but don't be pedantic or overly verbose. Especially avoid just replaying a commit description, PR description, or text used elsewhere into a comment.
- **Error Handling**: Use appropriate exception types; include context in error messages
- **Testing**: Write tests with pytest; maintain high coverage. See "Testing Async Code" below for async test conventions. Prefer adding tests to an existing test file covering the same area (e.g. eval-level behavior → `tests/test_eval.py`) rather than creating a new file; only add a new file when no existing one is a reasonable fit.

- **Async Concurrency**: Use `inspect_ai._util._async.tg_collect()` instead of `asyncio.gather()` for running concurrent async tasks. Use `inspect_ai.util.collect()` only inside sample subtasks (it adds transcript span grouping).

- **⚠️ Never `to_thread` (or run in a sync FastAPI `def` endpoint) `fsspec` work on a *remote* filesystem** (s3/gcs/azure — i.e. `filesystem(path).is_async()`). Their sync API runs on fsspec's own background event-loop thread, and nesting our threadpool over it can deadlock; use `inspect_ai._util.asyncfiles.AsyncFilesystem` instead. `to_thread` is fine when the path is known-local (`LocalFileSystem` is plain sync, no background loop) or fsspec-free (e.g. local `sqlite`).

- **No speculative locks**: Don't add `threading.Lock` around module-level state by default. Inspect runs on a single event loop thread (control-server handlers included — uvicorn runs as a task on the eval's loop), so async code doesn't interleave between `await` points, and a single dict/list operation is atomic under the GIL regardless. Add a lock only for demonstrated cross-thread access or a multi-operation invariant, and say in a comment/docstring what it protects; conversely, when omitting one where a reader might expect it, note why it isn't needed.

- **File Paths**: All code that handles file paths must support `s3://` URLs, `file://` URIs, and plain local paths. Use `filesystem()` from `inspect_ai._util.file` for filesystem operations and `local_path()` to resolve `file://` URIs to local paths before passing to APIs that only accept local paths (e.g. `ZipFile`).

- **Respect existing patterns**: Respect existing code patterns when modifying files. Run linting before committing changes.

## Testing Async Code

All async test functions automatically run under both asyncio and trio backends via anyio (applied by the `pytest_pycollect_makeitem` hook in `tests/conftest.py`). Trio variants are skipped by default; use `--runtrio` to enable them.

- **Do NOT use `@pytest.mark.asyncio`** — it conflicts with anyio and is blocked by conftest. Just write `async def test_...` and the hook handles the rest.
- **Use `anyio.sleep()` not `asyncio.sleep()`** in tests; `anyio.Event()` not `asyncio.Event()`; `tg_collect()` not `asyncio.gather()`.
- **Use `@skip_if_trio`** (from `test_helpers.utils`) for tests that cannot run under trio (e.g. they test asyncio-specific fallback paths).
- **`@pytest.mark.anyio`** is not required but harmless — use it to signal intentional dual-backend coverage.

## Subsystem Documentation

Additional files provide context when working in specific areas:

- [Sandbox tools: build process, container injection, RPC communication, design patterns](src/inspect_sandbox_tools/AGENTS.md)

## Design Documentation

`design/` contains architecture notes, subsystem internals, and documentation of repo/CI/development processes and workflows. Browse it before diving into an unfamiliar area.

## Pull requests

Write the PR description using the template at `.github/pull_request_template.md` (fill in its sections — the "This PR contains" checklist, current vs. new behavior, breaking changes, other info). Include the `### Agent review` section described in the contribution policy above (put it under "Other information"). Please include a sufficiently detailed description of the PR, including briefly noting the user facing experience that triggered the fix or change.

Title the PR with the user-facing outcome — the bug a user hit or the capability they gain — not the mechanism of the fix: "Fix eval hang when resuming with S3 logs", not "Add AsyncFilesystem to log recorder". A good test: would a user scanning titles recognize their problem or their feature request? PRs with no user-facing outcome (refactoring, dev tooling, docs) describe the change itself instead. CHANGELOG entries follow the same outcome-not-mechanism rule; only product-functionality changes get one (see below), so the carve-out doesn't arise there.

When asked to open a PR, don't stop at creation — monitor it afterward: watch its CI checks (e.g. `gh pr checks <number> --repo <owner>/<repo> --watch`) until they complete, report the outcome, and investigate/fix any failures. If the branch has fallen behind its base (out of date), update it — merge or rebase the base branch in and push — so CI runs against current code.

For changes to product functionality (not test-only or build-only changes), add a CHANGELOG entry: a single-line, single-sentence item in the `## Unreleased` section at the top of `CHANGELOG.md` (create that section if it doesn't exist), grouped with similar existing items when there are any, otherwise appended to the list. Keep it short (~25 words): state only the user-visible behavior change — what a user can now do or observe — not the mechanism, internal names, or design rationale (those belong in the PR description and `design/` docs). For example: "Fixed sample buffer database growing unboundedly during long evals", not "Add periodic vacuum to buffer SQLite db". Don't reference issue numbers in the entry (e.g. `(#123)` or `(owner/repo#123)`) — the PR description carries the issue link. A merge from the base can silently relocate the entry under a released heading — the merge resolves cleanly (the entry rides along with neighboring lines that the release commit moved), so nothing flags it. Verify placement mechanically after updating a branch against its base, and again before merging any PR — even when someone else updated the branch (e.g. via GitHub's "Update branch" button): run `git diff "$(git merge-base origin/main HEAD)" HEAD -- CHANGELOG.md` and confirm every added entry line sits under `## Unreleased`; move back any that don't.

Never change a submodule gitlink (e.g. `src/inspect_ai/_view/ts-mono`) unless the task is about that submodule. After any merge/rebase, check `git status`; if it shows the submodule modified, reset the pointer to the base and commit: `git checkout origin/main -- src/inspect_ai/_view/ts-mono`. (`git submodule update` will NOT fix this — it syncs the working tree to the already-recorded pointer, not the reverse.) When a change legitimately requires a coordinated ts-mono update (e.g. regenerated types), follow `.claude/skills/land-ts-mono/SKILL.md`.

### Opening an upstream PR from an org fork

Please open upstream PRs from a personal fork rather than an organization
fork, and leave "Allow edits by maintainers" enabled when creating the PR
(it's on by default in the GitHub UI and `gh pr create`). That setting gives
upstream maintainers push access to the PR branch, and they need it: upstream
`main` requires PR branches to be up to date before merging, so every push to
`main` blocks open PRs until their branches are updated. With maintainer
edits enabled, a maintainer can update the branch (or push small fixes) and
merge on their own schedule. GitHub does not support maintainer edits on
organization-owned forks, so a PR from an org fork can only be kept mergeable
by its author — it will sit approved but unmergeable whenever `main` moves
until the author syncs the branch again.

If you must open from an org fork, the following applies.

Before opening the PR, sync the branch with upstream `main` (`git fetch origin main && git merge origin/main`, resolving any conflicts) and push. Otherwise the PR can open with conflicts against its base, and CHANGELOG entries in particular almost always conflict.

Opening a PR from an organization fork to its upstream via the GitHub API/CLI needs an explicit `head_repo` — without it GitHub can't resolve the org fork as the PR head and rejects it with `{"field":"head","code":"invalid"}` (an org fork requires `head_repo`; a personal fork resolves without it). `gh pr create` has no `--head-repo` flag ([cli/cli#6462](https://github.com/cli/cli/issues/6462)), so use `gh api` — e.g. from the `meridianlabs-ai/inspect_ai` fork to upstream `UKGovernmentBEIS/inspect_ai`:

```bash
gh api repos/UKGovernmentBEIS/inspect_ai/pulls -X POST \
  -f title="<title>" -f base="main" \
  -f head="<branch>" -f head_repo="meridianlabs-ai/inspect_ai" \
  -F body=@<body.md>
```

Once the upstream PR is open it's the system of record: close the corresponding org-fork PR, with a close comment linking to the upstream PR.
