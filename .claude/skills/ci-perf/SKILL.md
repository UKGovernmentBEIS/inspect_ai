---
name: ci-perf
description: Assess and improve CI performance for pull requests in this repo. Use whenever the user asks about CI speed, slow CI, how long checks take, queue/runner wait, slow or duplicate tests, CI cost, or asks to run the recurring CI performance report (/ci-perf). Also use when asked to make PR feedback faster or to review workflow efficiency.
---

# CI performance analysis and improvement

Recurring analysis of PR CI: measure where wall-clock time goes, track it
over time, and turn findings into concrete fixes. Designed to be run
manually today and on a schedule later — each run is self-contained.

## Objective and ground rules

- **Primary metric: PR wall-clock** — push to all-checks-green. That is
  what contributors feel. Total runner compute-minutes is tracked as a
  secondary metric (it drives queue contention and cost).
- **Queue time and execution time are separate numbers.** Runner-pool
  saturation has historically dominated wall clock here (batches of PRs
  land together; ~13 jobs fan out per PR). Never propose a test speedup to
  fix what is actually queue contention.
- **Two output buckets:**
  - *Safe fixes* — small, low-risk changes the skill prepares as PRs
    (see the fix phase for the category list).
  - *Structural proposals* — anything touching required-check names, job
    topology, or policy. Report-only; a maintainer decides.
- **Never propose trimming the Python version matrix** (e.g. PRs testing
  only 3.11). Explicitly ruled out.
- **Always ask before pushing.** Prepare branch + diff + PR body, show the
  user, push only on their OK. One fix per PR. Follow AGENTS.md PR rules
  (CI-only changes need no CHANGELOG entry; test-content changes are
  product-adjacent — judge per AGENTS.md).

## Phase 1 — Collect

Run the bundled collector (venv active; `gh` must be authenticated):

```bash
python .claude/skills/ci-perf/scripts/collect_ci_data.py \
  --out design/ci-perf/history/$(date +%F).json
```

It snapshots the last ~200 completed PR workflow runs with per-job
timings (execution seconds, wait-from-run-start) and mines recent Build
test-job logs for pytest `--durations` blocks.

- If `pytest_durations` comes back empty, CI likely doesn't pass
  `--durations` yet — proposing that one-line workflow change is the
  standing first safe fix.
- If a snapshot for today already exists, overwrite it (re-runs same day
  are fine); history keeps one file per day.

## Repo slow-test policy (context for analysis and fixes)

- **Definition:** any test that uses docker or hits a real (unmocked)
  external service is by definition slow and must carry
  `@pytest.mark.slow`. A fully-mocked test may also be marked slow when
  its cost is inherent (e.g. crossing the S3 1000-key page boundary means
  1001+ real HTTP PUTs to the in-process moto server) — say why in the
  test's docstring.
- **Where slow tests run:** they are skipped in the PR-gate `test` jobs
  (no `--runslow`) and run every ~2 hours by the scheduled suite in
  `meridianlabs-ai/actions` (`inspect-ai-scheduled-tests.yml`, runner
  label `slow_test_runner`, `pytest --runslow --runapi`). Marking a test
  slow moves its coverage there — it does not delete it. Prefer the PR
  gate for regression guards on core logic when the test can be made
  cheap; prefer slow for anything matching the definition above.
- **The docker trap:** docker is preinstalled and running on GitHub
  `ubuntu-latest`, so nothing technically stops a docker test running in
  the PR gate — `skip_if_no_docker` does not skip in CI. The slow mark is
  the only enforcement, by convention: `@skip_if_no_docker` and
  `@pytest.mark.slow` belong together. When durations data shows a
  multi-second test, check for this pairing violation first (two found so
  far: the 38s sandbox-init test, fixed in #4760, and
  `test_docker_read_file.py` at 42s of fixture setup). Aggregate `setup`
  and `teardown` phases as well as `call` — fixture-heavy offenders hide
  outside `call`.

## Phase 2 — Analyze

Read the fresh snapshot plus the previous few in `design/ci-perf/history/`
(trend needs at least one prior; on the first run, report absolute numbers
only). Compute:

1. **Queue vs execution split.** `wait_from_run_start_seconds` is true
   queue time only for jobs without `needs`; for dependent jobs, subtract
   the predecessor's `completed_at` first. Get the dependency map by
   reading `.github/workflows/*.yml` (`needs:` keys) — don't hardcode it;
   workflows change.
2. **Critical path per workflow.** Which chain of jobs determines wall
   clock, and how much of it is waiting? (Historically: `changes` → `test`
   serialization in build.yml put a full queue+start cycle in front of the
   longest job.)
3. **Trends and regressions.** Median/p90 wall clock per workflow vs prior
   snapshots; tests newly appearing in the slowest list or significantly
   slower than before.
4. **Slowest tests** from `pytest_durations` (aggregate across runs;
   median per test). For top offenders, read the test source and classify:
   genuinely heavy, real sleeps/timers that a mock clock or event would
   remove, duplicate coverage, or a candidate for `@pytest.mark.slow`.
5. **Waste.** Cancelled superseded runs and how long they held runners
   before dying; jobs whose checkout/setup overhead exceeds their useful
   work; unconditional `fetch-depth: 0` where history/tags are unused;
   cache effectiveness.
6. **Step-level breakdown of the heavy jobs — always at p90, not just
   median.** The snapshot carries per-step timings; sum each step name's
   median AND p90 across runs. A step can look fine in one sample and be
   the wall-clock lottery across many: `fetch-depth: 0` checkouts fetch
   every branch and tag at full history (a ~400MB pack here), taking 30s
   or 4min depending on GitHub's server-side pack cache. Rule of thumb:
   any always-run step whose p90 exceeds ~2x its median is a variance
   problem, not a size problem — hunt for the erratic dependency
   (pack cache, registry, external download). For checkouts specifically,
   `filter: "blob:none"` keeps setuptools_scm working (refs + commit
   graph) while skipping historical file contents; only jobs that read
   old blob contents (e.g. `git diff main -- <paths>` over sources) need
   care, and even those lazy-fetch on demand.

## Phase 3 — Report

Rewrite `design/ci-perf/report.md` (full replacement each run; history
lives in the snapshots and git). Structure:

```markdown
# CI performance report — YYYY-MM-DD
Data: N runs, DATE..DATE. Snapshot: history/YYYY-MM-DD.json

## Summary
2–4 sentences: wall-clock medians per workflow, trend arrow, the one
dominant bottleneck right now.

## Queue vs execution
Table per workflow/job: median exec, median queue, p90 wall.

## Slowest tests
Top ~15 with median seconds and classification. "(no data — --durations
not in CI)" if empty.

## Regressions since last report
Or "none".

## Waste
Cancelled-run runner-minutes, overhead-dominated jobs, etc.

## Proposals (ranked)
Each: what / est. wall-clock impact / disruption (safe-fix vs structural)
/ status (new, PR opened #N, done, declined).
Carry forward prior proposals with updated status — don't drop them.

## PRs opened by this skill
Running list with outcomes.
```

Leave report + snapshot as uncommitted working-tree changes; ask the user
whether to commit them at the end of the run.

## Phase 4 — Fix

From the ranked proposals, prepare the top safe fixes (typically 1–3 per
run, one PR each):

**Safe-fix categories** (auto-PR eligible, still ask-first):
- Workflow hygiene: add `--durations=50` to pytest, drop unneeded
  `fetch-depth: 0` / `fetch-tags`, cache tuning, merging trivially small
  jobs, removing needless `needs:` serialization.
- Trivial test fixes: real `sleep(...)` waits replaced by mock clocks or
  events, removal of exact-duplicate tests, marking genuinely slow tests
  `@pytest.mark.slow` where an equivalent fast path exists.

**Structural proposals** (report-only, never a PR from this skill):
renaming/merging required checks (branch protection), moving checks
between workflows, retry/concurrency policy changes, anything a reviewer
could reasonably object to on grounds other than correctness.

Procedure per fix: branch off `main`, make the single change, run the
relevant local validation (`ruff check`, `mypy` for touched Python; the
affected tests for test fixes), write the PR body per
`.github/pull_request_template.md`, then **show the user the diff and PR
body and wait for their OK before any push**. After opening, watch CI per
AGENTS.md. Record the PR number in the report.

## Verifying impact

Each run, check the proposals marked "PR opened/done" in the previous
report against the new snapshot: did the metric move as predicted? Say so
in the report — honest misses are how estimates get better.
