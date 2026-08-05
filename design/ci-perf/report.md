# CI performance report — 2026-08-04

Data: 200 PR runs, 2026-08-04 07:43..20:02 UTC (~12 hours — CI volume is
high enough that 200 runs is half a day). Snapshot: `history/2026-08-04.json`.

## Summary

Build (the slowest required workflow) has a median wall clock of **15.6 min,
p90 23.8 min**; Validate Embedded Viewer 4.2/9.1 min; Changelog Lint is
negligible. The dominant costs on Build's critical path are (1) the pytest
job itself (median 8.0 min execution), (2) runner queue time (median ~2.5
min per job, **p90 ~8 min** when PR batches saturate the pool), and (3) the
`changes` → `test` serialization, which puts a full queue+run cycle
(~2.5 min median, ~8 min p90) in front of the longest job. Setup overhead
is not a problem: uv caching works (dependency install ~9 s) and checkout
is ~30 s.

## Queue vs execution

Median execution / median queue / p90 queue, successful runs. Queue for
dependent jobs is measured from predecessor completion, not run start.

| Workflow | Job | n | exec med | queue med | queue p90 |
|---|---|---|---|---|---|
| Build | test (per matrix leg) | 84 | 480s | 149s | 466s |
| Build | docs (when docs change) | 27 | 390s | 196s | 470s |
| Build | mypy (per matrix leg) | 98 | 114s | 194s | 456s |
| Build | pre-commit | 49 | 57s | 128s | 533s |
| Build | package | 49 | 52s | 154s | 473s |
| Build | ruff | 49 | 34s | 152s | 485s |
| Build | changes | 49 | 8s | 143s | 490s |
| Build | detect-slow | 49 | 9s | 136s | 464s |
| Viewer | check-schema-and-types | 85 | 79s | 116s | 424s |
| Viewer | viewer-tests | 85 | 64s | 100s | 332s |
| Viewer | dist-validation | 85 | 31s | 73s | 319s |
| Viewer | submodule-on-main | 85 | 9s | 85s | 350s |

Read: most jobs finish in under 2 min of execution but wait 2–8 min for a
runner. ~13 jobs fan out per PR push across 3 workflows; queue time is
runner-pool contention, not job dependencies.

Build critical path (median): queue `changes` 143s → exec 8s → queue
`test` 149s → exec 480s ≈ 13 min, matching the 15.6 min median wall.

## Slowest tests

(no data — `--durations` not in CI; proposal 1 adds it)

Static scan for real sleeps in tests (candidates to size once durations
data exists): `tests/test_task_cancel.py` (9 sleep calls),
`tests/agent/test_acp/test_react_integration.py` (7),
`tests/util/test_limit_time.py`, `tests/test_cancellation_logging.py`,
`tests/model/test_parallel_tools.py`, `tests/agent/test_agent_human.py`,
`tests/agent/deepagent/test_deepagent_background.py` (4 each).

## Regressions since last report

First run — no baseline.

## Waste

- **Cancelled superseded runs:** 29/200 runs (14.5%) cancelled, burning
  **526 runner-minutes in ~12 h**. Cancellation itself is prompt (~30 s
  after the superseding push); the waste is work already done before the
  next push in a rapid push sequence.
- **Compute:** Build consumed 1,986 runner-min in the window (~4,000/day);
  Viewer 271; Changelog Lint 4.
- **Job-count pressure:** 4 Viewer jobs each execute ≤ 79 s median but each
  occupies a runner slot and pays its own queue+checkout; they contribute
  to the very contention that delays Build's `test`.
- `docs` job executes 6.5 min (Quarto render, no caching of the render).
- `fetch-depth: 0` is justified on jobs that install the package
  (setuptools_scm needs tags); only `ruff` fetches full history without
  needing it (~seconds — not worth a PR alone).

## Proposals (ranked)

1. **Add `--durations=50 --durations-min=1` to the Build pytest invocation**
   — impact: none directly; unlocks all per-test analysis for future runs.
   Safe fix. Status: **PR opened #4746**.
2. **Remove the `changes` → `test` serialization** by running the
   docs-only paths-filter as a step inside the `test` job (steps
   short-circuit when only docs changed; job names/required checks
   unchanged; `changes` job stays for `docs`/`sandbox-tools-unit`) —
   impact: ~2.5 min median, ~8 min p90 off Build wall clock. Safe fix.
   Status: **PR opened #4747**.
3. **Merge the 4 Viewer jobs into 1–2** — impact: frees 2–3 runner slots
   per PR push, reducing pool contention for everything (queue med 2–3
   min, p90 5–8 min across all jobs); renames required checks →
   maintainer decision. Structural. Status: new.
4. **Increase runner pool / larger runners for `test`** — queue p90 ~8 min
   is contention; also `-n auto` on a bigger runner would cut the 8 min
   pytest exec roughly linearly. Cost/policy decision. Structural.
   Status: new.
5. **Cache the Quarto render (freeze) for the `docs` job** — impact:
   most of 6.5 min on docs-touching PRs; needs care that freeze data
   stays fresh. Structural (build-behavior change). Status: new.
6. **Speed up slow tests (sleeps → mock clocks/events, dedupe)** —
   blocked on durations data from proposal 1. Trivial fixes are safe-fix
   eligible. Status: blocked on 1.

## PRs opened by this skill

- #4746 — add `--durations=50` to Build pytest (2026-08-04, open)
- #4747 — remove `changes` → `test` serialization (2026-08-04, open)
