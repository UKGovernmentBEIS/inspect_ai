# CI performance report — 2026-08-12

Data: 200 PR runs, 2026-08-11 21:04 .. 2026-08-12 17:40 UTC. Snapshot:
`history/2026-08-12.json`. Previous: 2026-08-05 (200 runs / 18.3h; this
window is 200 runs / 20.6h, so throughput is comparable).

## Summary

Build median wall clock **10.3 → 7.7 min**, p90 **20.8 → 8.9 min**; Viewer
**2.8 → 1.4 min**. Queue time has essentially vanished — every job now
starts ~3 s after run start with a p90 of 9–17 s (previously 18–40 s
median, 285–520 s p90) — so the earlier queue-contention bottleneck is
gone in this window and **PR wall clock is now just the `test` job's
pytest run: 442 s exec, of which 412 s is pytest itself**. Last run's
fixes all landed and verified. The single largest remaining item in the
PR-gate suite is one docker test costing 43 s.

## Queue vs execution

Median execution / queue, successful runs. Queue for dependent jobs is
measured from predecessor completion (`needs` map read from the workflow
files).

| Workflow | Job | n | exec med | exec p90 | queue med | queue p90 |
|---|---|---|---|---|---|---|
| Build | slow-tool-tests-dev | 2 | 1028s | 1182s | 3s | 3s |
| Build | slow-tool-tests-release | 2 | 816s | 843s | 2s | 3s |
| Build | test (per matrix leg) | 102 | 442s | 489s | 3s | 10s |
| Build | docs (when docs change) | 22 | 369s | 392s | 2s | 9s |
| Build | mypy (per matrix leg) | 102 | 88s | 95s | 3s | 13s |
| Viewer | check-schema-and-types | 66 | 74s | 86s | 3s | 14s |
| Viewer | viewer-tests | 66 | 59s | 68s | 3s | 10s |
| Build | pre-commit | 51 | 32s | 37s | 3s | 17s |
| Build | package | 51 | 30s | 34s | 3s | 9s |
| Viewer | dist-validation | 66 | 28s | 35s | 3s | 11s |
| Build | ruff | 51 | 10s | 13s | 3s | 11s |
| Build | detect-slow | 51 | 9s | 10s | 3s | 10s |
| Build | changes | 51 | 8s | 9s | 3s | 13s |

Execution also dropped across the board vs 2026-08-05 (test 510→442s,
mypy 114→88s, pre-commit 57→32s, ruff 34→10s, package 51→30s) — that is
the `filter: blob:none` checkout change from #4760: checkout is now 4–5 s
median (max 14 s) in mypy/ruff/pre-commit/docs, where the previous report
measured 30 s–4 min of erratic full-pack fetching.

### Critical path

- **Ordinary PR:** `test` is the whole story — 3 s queue + 442 s exec, vs
  7.7 min Build wall. Nothing else comes close, and inside `test`, 412 s
  is the pytest step (10 s install, 4 s checkout).
- **Sandbox-tools PR:** a separate, much longer path —
  `detect-slow` → `check-version-bump` → `slow-tool-tests-dev` (1028 s) →
  `slow-tool-tests-release` (816 s), serialized by `needs`. Observed Build
  wall on those PRs: 29.5 and 33.7 min (the two longest runs in the
  window). See proposal 3.

## Slowest tests

Median seconds across 14 CI test jobs, `call` + `setup` + `teardown`
combined. 122 tests captured (`--durations-min=1`), 328 s total spread
across xdist workers.

| Median | Test | Classification |
|---|---|---|
| 42.9s | `test_docker_read_file.py::test_docker_read_file_contains_untrusted_sources` | **The docker trap**: 40.1 s of it is fixture setup starting a real container; `@skip_if_no_docker` without `@pytest.mark.slow`, so it runs in the PR gate. → **fixed in #4848 (proposal 1)** |
| 8.8s | `test_eval_set_scanner.py::test_scout_scan_resume_reruns_failed_scans` | genuinely heavy (multi-eval resume flow); grew 6.6→8.8s, see regressions |
| 6.6s | `test_eval_set_scanner.py::test_scanner_resume_...[s3]` | moto S3 + full eval-set resume |
| 6.5s | `test_launch_handoff.py::test_eval_detach_hands_off_and_leaves_eval_running` | real CLI subprocess + control-server handshake |
| 6.4s | `test_launch_handoff.py::test_eval_detach_via_dotenv_detaches_exactly_once` | (as above) |
| 6.0s | `test_eval_set.py::test_eval_set_previous_task_args` | not yet examined |
| 4.8s | `test_eval_log_config.py::test_eval_log_run_config_round_trip` | not yet examined |
| 4.8s | `test_launch_handoff.py::test_eval_json_redirects_subprocess_stdout_to_stderr` | real CLI subprocess (documented: needs real fds) |
| 4.5s | `test_agent_bridge.py::test_google_bridge_computer_use_incompatible_model` | not yet examined |
| 4.4s | `test_agent_bridge.py::test_google_bridge_streaming_not_supported` | not yet examined |
| 4.2s | `test_sample_limits.py::test_working_limit` | real waits inherent to limit tests |
| 3.9s | `test_launch_handoff.py::test_eval_detach_fails_when_control_bind_fails` | real CLI subprocess |
| 3.4s | `test_sample_limits.py::test_solver_timeout_not_scored` | real waits |
| 3.3s | `test_sample_shuffle.py::test_sample_shuffle` | not yet examined |
| 3.3s | `test_limit_working.py::test_working_limit_interrupts_local_sandbox_exec` | real waits |

The `test_launch_handoff.py` cluster is ~25 s across 5 tests, each running
the real CLI in a subprocess. That cost is inherent to what they assert
(fd/stdout behavior, SIGTERM handling, detached-child lifetime) — not
worth converting, and none is individually large.

## Impact verification (previous run's PRs)

All of #4760 confirmed:

- **38.4 s `test_eval_sandbox_init_when_first_task_has_no_sandbox`** — no
  longer in the durations data at all (below the 1 s cutoff).
- **9.7 s `test_iter_files_s3_pagination`** — gone from the PR gate
  (marked slow).
- **9.4 s `test_solver_extension`** — gone; pre-installing
  `tests/test_package` in the CI install step removed the mid-run pip.
- **`filter: blob:none`** — checkout in the Build jobs is 4–5 s median,
  max 14 s across 292 samples; the erratic 30 s–4 min fetch is gone. Job
  exec dropped 10–25 s each accordingly.

Predicted −60 s median on the PR gate; measured −68 s on `test` exec plus
20–25 s on each of the shorter jobs. Held.

## Regressions since last report

- `test_scout_scan_resume_reruns_failed_scans` 6.6 → 8.8 s (+33%). Small
  in absolute terms; worth a look if it grows again.
- Nothing else moved more than ~1 s.

## Waste

- Cancelled superseded runs: 4/200, 24 runner-min (previous: 29/200,
  417 min) — this window had far less rapid-push churn, not a fix.
- Compute: 1,353 runner-min total (Build 1,141; Viewer 205; Changelog
  Lint 7), down from 2,226.
- `check-schema-and-types` checkout: 30 s median, 216 s max — the one
  remaining unfiltered `fetch-depth: 0` checkout (proposal 2).
- `docs` job: 309 s Quarto render, still uncached (proposal 6).

## Proposals (ranked)

1. **Mark the 43 s docker `read_file` test `@pytest.mark.slow`** — it
   starts a real container in fixture setup (40 s) and runs on every PR
   because `@skip_if_no_docker` doesn't skip in CI. Coverage moves to the
   2-hourly slow suite, which is where the policy puts docker tests.
   Impact: up to −43 s off the critical xdist worker (−15 to −40 s on
   `test` exec, so on Build wall clock). Safe fix. Status: **PR opened
   #4848**.
2. **`filter: blob:none` on the `check-schema-and-types` checkout** — the
   only `fetch-depth: 0` checkout still fetching the full ~400 MB pack; no
   step in that job reads historical blobs (the `git diff`/`git status`
   checks are working-tree only). Impact: −25 s median on the Viewer
   critical path (74 → ~50 s), and removes the 216 s tail. Safe fix.
   Status: **PR opened #4848**.
3. **Un-serialize `slow-tool-tests-release` from `slow-tool-tests-dev`** —
   release consumes no output from dev (it downloads the published
   artifact and re-runs the same suite), so the `needs` edge is pure
   ordering. Dropping it would cut ~13 min of the 29–34 min wall clock on
   sandbox-tools PRs. Cost: when dev fails, release burns ~14 runner-min
   instead of being skipped. The sequence is deliberate and documented in
   `design/sandbox-tools-ci-gates.md`, so this is a maintainer call.
   Structural. Status: new.
4. **Merge the 4 Viewer jobs into 1–2** — required-check rename. Much less
   valuable now that queue time is ~3 s; the argument is compute and
   batch-push resilience, not current wall clock. Structural. Status:
   carried, downgraded.
5. **Runner pool size / larger runners for `test`** — with queue at 3 s the
   only remaining lever on `test` is more cores for xdist. Structural/cost.
   Status: carried.
6. **Cache the Quarto render for `docs`** — 309 s render on docs PRs; below
   the `test` job's 442 s, so it is not on the critical path today.
   Structural. Status: carried, low priority.
7. **Policy consistency: 3 more docker tests lack `@pytest.mark.slow`** —
   `test_docker_compose_config.py` (3 tests). They only shell out to
   `docker compose config` and each costs <1 s (below the durations
   cutoff), so there is no measurable win; flagging only because the
   convention is what enforces the gate. Status: new, report-only.
8. **Collector hardening** — the GitHub runs endpoint served a stale page
   during this run, producing a snapshot whose 200 runs had a 3.5-week
   hole in the middle and zero `--durations` data (the older clump
   predated the flag). Fixed in
   `.claude/skills/ci-perf/scripts/collect_ci_data.py`: dedupe by run id,
   sort by start time, and warn when the window isn't contiguous. Status:
   **PR opened #4848**.

## PRs opened by this skill

- #4746 — add `--durations=50` to Build pytest (2026-08-04, **merged**,
  impact verified)
- #4747 — remove `changes` → `test` serialization (2026-08-04, **merged**,
  impact verified)
- #4748 — the ci-perf skill itself (2026-08-04, **merged**)
- #4760 — two slow-test fixes + `blob:none` checkouts + slow-test policy
  docs (2026-08-05, **merged**, impact verified above)
- #4848 — mark the 43 s docker test slow, `blob:none` on the Viewer
  checkout, collector hardening + this report/snapshot (2026-08-12, open)
