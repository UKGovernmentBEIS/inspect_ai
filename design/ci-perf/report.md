# CI performance report — 2026-08-05

Data: 200 PR runs, 2026-08-04 18:32 .. 2026-08-05 12:47 UTC. Snapshot:
`history/2026-08-05.json`. Previous: 2026-08-04.

## Summary

Build median wall clock dropped **15.6 → 10.3 min** (p90 23.8 → 21.4).
Two effects: last run's fixes merged mid-window (#4747 at 11:16 UTC), and
this window has less batch-push queue contention than yesterday's. In the
post-merge slice the effect is unambiguous: **test jobs now start ~9 s
after run start (was 42 s median / 13 min p90 wait)**, and Build wall is
8.9 min median (n=6 — small sample, confirm next run). With the
serialization gone and queue quiet, the bottleneck is now **pytest
execution itself: 8.5 min median**, of which one test contributes 38 s.

## Queue vs execution

Median execution / median queue / p90 queue, successful runs. (Queue for
dependent jobs measured from predecessor completion.)

| Workflow | Job | n | exec med | queue med | queue p90 |
|---|---|---|---|---|---|
| Build | test (per matrix leg) | 100 | 510s | 10s | 461s |
| Build | docs (when docs change) | 16 | 392s | 210s | 470s |
| Build | mypy (per matrix leg) | 114 | 114s | 21s | 433s |
| Build | pre-commit | 57 | 57s | 18s | 519s |
| Build | package | 57 | 51s | 21s | 451s |
| Build | ruff | 57 | 34s | 20s | 395s |
| Viewer | check-schema-and-types | 87 | 78s | 39s | 424s |
| Viewer | viewer-tests | 87 | 62s | 26s | 305s |
| Viewer | dist-validation | 87 | 30s | 33s | 285s |

Queue medians collapsed vs yesterday (10–40s vs 130–200s) — partly less
contention in this window, partly 2 fewer serialized job-starts per Build.
p90s remain 5–8 min: batch pushes still saturate the pool.

## Impact verification (previous run's PRs)

- **#4747 (un-serialize `changes` → `test`): confirmed.** Post-merge, test
  jobs wait a median of **8 s** from run start (pre-merge in the same
  window: 42 s median, 804 s p90; the mechanism — a queue+run cycle of
  `changes` in front of `test` — is gone). Build wall median post-merge
  8.9 min vs 11.3 pre (n=6, contention-confounded; predicted −2.5 min
  median holds directionally).
- **#4746 (`--durations`): confirmed working** — per-test data captured
  from all 12 mined test jobs; table below exists because of it.

## Slowest tests

Median `call` seconds across 12 CI test jobs (2026-08-05). Sum of all 108
captured slow-test medians: 308 s of the ~510 s job execution (xdist
spreads these across workers; the longest single test bounds the tail).

| Median | Test | Classification |
|---|---|---|
| 38.4s | `test_eval.py::test_eval_sandbox_init_when_first_task_has_no_sandbox` | docker container lifecycle for a sandbox-type-agnostic gating check → **fix prepared: spy on `SandboxManager.start` + local sandbox, 38s → ~2s** |
| 9.7s | `test_asyncfiles.py::test_iter_files_s3_pagination` | 1001+ keys are inherent (S3 default page size), each a real HTTP PUT to the moto server → **fix: writes parallelized and test marked `slow` — leaves the PR gate, runs in the 2-hourly slow suite** |
| 9.4s | `test_solver_spec.py::test_solver_extension` | not the test: `ensure_test_package_installed()` pip-installs `tests/test_package` mid-run; first caller pays (hence n=6) → **fix: pre-install in the CI install step (#4760)** |
| 6.6s | `test_eval_set_scanner.py::test_scout_scan_resume_reruns_failed_scans` | not yet examined |
| 6.4s | `test_launch_handoff.py::test_eval_detach_hands_off_and_leaves_eval_running` | real subprocess + control-server handshake; file totals ~21s over 4 tests — next candidate |
| 6.3s | `test_launch_handoff.py::test_eval_detach_via_dotenv_detaches_exactly_once` | (as above) |
| 6.2s | `test_eval_set_scanner.py::test_scanner_resume_...[s3]` | not yet examined |
| 5.9s | `test_eval_set.py::test_eval_set_previous_task_args` | not yet examined |
| 5.1s | `test_agent_bridge.py::test_google_bridge_computer_use_incompatible_model` | not yet examined |
| 4.8s | `test_launch_handoff.py::test_eval_json_redirects_subprocess_stdout_to_stderr` | (launch_handoff) |
| 4.7s | `test_agent_bridge.py::test_google_bridge_streaming_not_supported` | not yet examined |
| 4.7s | `test_eval_log_config.py::test_eval_log_run_config_round_trip` | not yet examined |
| 4.3s | `test_sample_limits.py::test_working_limit` | likely real waits (limit tests) |
| 4.2s | `test_sample_shuffle.py::test_sample_shuffle` | not yet examined |
| 3.8s | `test_launch_handoff.py::test_eval_detach_fails_when_control_bind_fails` | (launch_handoff) |

## Regressions since last report

None — first run with per-test data establishes the baseline.

## Waste

- Cancelled superseded runs: 29/200, 417 runner-min burned (yesterday:
  526). Steady-state cost of rapid push sequences.
- Compute: Build 1,947 runner-min in the window; Viewer 277.
- `docs` job: 6.5 min Quarto render, no render caching (proposal 5).

## Proposals (ranked)

1. ~~Add `--durations` to Build pytest~~ — **done, #4746 merged, verified.**
2. ~~Remove `changes` → `test` serialization~~ — **done, #4747 merged,
   verified (test-job start wait 42s+ → 8s median).**
3. **Replace docker with spied local sandbox in the 38s
   `test_eval_sandbox_init_...` test** — impact: −38s from the longest
   test (bounds the xdist tail); coverage verified preserved (test fails
   when the original `next()` bug is reintroduced; a plain local-sandbox
   swap without the spy does NOT fail and was rejected). Safe fix (trivial
   test fix). Status: **PR opened #4760**.
4. **`test_iter_files_s3_pagination`: parallelize writes and mark `slow`** —
   impact: ~−10s median off the PR-gate suite (moved to the 2-hourly slow
   run; also ~2x faster there). Safe fix. Status: **PR opened #4760**.
5. **Merge the 4 Viewer jobs into 1–2** — structural (required-check
   rename); still the biggest queue-pressure lever for batch pushes
   (p90 queue 5–8 min). Status: carried, awaiting maintainer decision.
6. **Runner pool size / larger runners for `test`** — structural/cost.
   Status: carried.
7. **Cache the Quarto render for `docs`** — structural. Status: carried.
8. **Pre-install `tests/test_package` in the CI install step** — impact:
   ~−9s off the xdist critical path per test job plus a ~3.5s lock echo;
   also removes install noise from the durations data. Safe fix. Status:
   **PR opened #4760** (same change proposed to the meridian scheduled
   workflow separately).
9. **`filter: blob:none` on the always-run jobs' checkouts** (ruff,
   mypy, pre-commit, docs, test, package) — impact: caps the erratic
   30s–4min full-pack fetch at tens of MB; slow-tool jobs keep full
   blobs (they `git diff main` over sources). Not applied to the
   meridian scheduled workflow: its self-hosted runner reuses the
   workspace (checkouts measured 16–50s incremental). Safe fix. Status:
   **PR opened #4760**.
10. **Remaining slow tests** (`test_launch_handoff.py` cluster ~21s,
   `test_solver_extension` 9.4s, eval-set scanner tests) — examine next
   run with a second day of durations data. Status: new.

## PRs opened by this skill

- #4746 — add `--durations=50` to Build pytest (2026-08-04, **merged**,
  impact verified)
- #4747 — remove `changes` → `test` serialization (2026-08-04, **merged**,
  impact verified)
- #4748 — the ci-perf skill itself (2026-08-04, **merged**)
- #4760 — combined: both slow-test fixes + this report/snapshot (2026-08-05, open)
