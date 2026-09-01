# CI performance report — 2026-09-01

Data: 200 PR runs, 2026-08-31 19:17 .. 2026-09-01 05:30 UTC (**10.2h**, 19.6
runs/hour, 52 pushes). Snapshot: `history/2026-09-01.json`. Previous: 2026-08-31
(200 runs over 52.6h, ending 02:01 UTC). The two windows do **not** overlap and
do not abut: 17.3h between them is uncovered, because a 200-run snapshot now
spans ten hours rather than two days. No gap >3h inside this window. Produced by
the unattended scheduled run
([workflow run](https://github.com/meridianlabs-ai/actions/actions/runs/33491397614)).

## Summary

**The headline is new, and it is the largest lever this series has measured:
every `eval()` spends ~214ms starting and stopping a uvicorn control-channel
HTTP server.** A one-sample `mockllm` eval is **249ms** with it and **35ms**
without — the control server is 86% of a small eval. `eval()`/`eval_set()` is
called directly by **796 test functions across 153 files**, so the PR gate pays
it hundreds of times per matrix leg. A controlled A/B — the full suite on 4
workers, an autouse fixture forcing the server off as the only difference —
runs **725.8s → 529.0s of wall (−27%)** and **697.6s → 512.3s of test worker
time**, with **381 tests dropping out of the 0.1–1s band** that owns half of
CI's test time. The only 14 tests that fail without it are the ones whose
subject *is* the control channel. Filed as
[#393](https://github.com/meridianlabs-ai/inspect_ai/issues/393); not shipped,
because both candidate fixes are maintainer decisions rather than mechanical
ones (proposal 1).

**A new required check appeared: `Suppressions`.** The suppression-ledger gate
landed on `main` at 2026-08-31 15:32 UTC
([#5136](https://github.com/UKGovernmentBEIS/inspect_ai/pull/5136)), just before
this window opened, so it runs on every push here — a fourth workflow, 16s of
exec, 13 runner-minutes per 200 runs. Per-push job records went 17 → 21 and
per-push compute 17.6 → 18.5 runner-minutes. It is off the critical path (20s
wall against Build's 346s) and its 5 failures are all one WIP branch.

**`test` is the binding job again, because `docs` barely ran.** Only 5 of the 46
Build runs that reached the `docs` job actually rendered (40 skipped, 1
cancelled), so `test (3.10)`/`test (3.11)` bind 27 of
34 successful Build runs — by 10–14s, the margin that makes further `test`
savings self-limiting. Code-only Build wall is **341s**. When `docs` did bind (3
runs) it bound by 69s at 403s of wall.

**The docs render cache hit 0 of 5 jobs, and the duplicate-key evidence has
doubled.** The repository cache index now holds **107 `docs-render-*` entries
over 77 distinct keys with 4 ever re-read (3.7%)**, and **30 of the 77 keys
exist twice — once under a PR merge ref and once under `refs/heads/main`**,
created 5–8 minutes apart. That is ~30 × 330s ≈ 165 runner-minutes of provably
identical renders over the seven days the index covers, up from 14 keys / ~76
minutes last window. [#317](https://github.com/meridianlabs-ai/inspect_ai/issues/317)
stays proposal 2.

**Queue is a non-issue for the eighth consecutive window**, including the
densest hour this series has seen: 64 runs and 237 independent-job records in
one hour, median wait 3s.

## Queue vs execution

Median execution / queue over successful jobs, this window against the last.
Queue is measured from run start for independent jobs and from the predecessor's
completion for dependent ones (`needs` map read from `.github/workflows/build.yml`:
`docs`/`sandbox-tools-unit` ← `changes`; `check-version-bump`/`slow-tests` ←
`detect-slow`; `slow-tool-tests-{dev,release}` ← `detect-slow` +
`check-version-bump`). p90 is linear interpolation, as in every prior report.

| workflow | job | n | exec med | prev | exec p90 | queue med | queue p90 |
|---|---|---:|---:|---:|---:|---:|---:|
| Build | slow-tool-tests-dev | 4 | 794 | 826 | 937 | 2 | 3 |
| Build | **docs** | 5 | **399** | 391 | 420 | 2 | 3 |
| Build | test (3.11) | 39 | 331 | 324 | 347 | 3 | 25 |
| Build | test (3.10) | 39 | 328 | 321 | 339 | 3 | 26 |
| Build | slow-tests (checkpoint) | 2 | 274 | — | 277 | 3 | 4 |
| Build | mypy (3.10) | 39 | 89 | 89 | 98 | 3 | 25 |
| Build | mypy (3.11) | 39 | 87 | 88 | 95 | 3 | 29 |
| Viewer | viewer-tests | 44 | 65 | 67 | 73 | 3 | 15 |
| Viewer | check-schema-and-types | 44 | 54 | 55 | 70 | 3 | 15 |
| Viewer | dist-validation | 45 | 34 | 34 | 43 | 3 | 17 |
| Build | pre-commit | 43 | 31 | 32 | 36 | 3 | 29 |
| Build | package | 45 | 28 | 28 | 34 | 3 | 25 |
| **Suppressions** | **suppressions** | 41 | **16** | — | 20 | 3 | 4 |
| Build | ruff | 44 | 10 | 10 | 13 | 3 | 23 |
| Build | detect-slow | 46 | 9 | 8 | 11 | 3 | 24 |
| Build | check-version-bump | 6 | 9 | 10 | 10 | 2 | 12 |
| Viewer | submodule-on-main | 46 | 8 | 8 | 10 | 3 | 12 |
| Build | changes | 46 | 7 | 7 | 9 | 3 | 23 |
| Changelog Lint | entries-under-unreleased | 37 | 7 | 7 | 8 | 3 | 7 |

Every job is within 1–7s of last window. `slow-tests (checkpoint)` is a renamed
`slow-tests`; `package` is recorded as `Build & inspect the package.` in the
snapshot.

Workflow wall clock, successful runs only (`action_required` runs record a 0s
wall and would drag every median down):

| workflow | n | wall med | prev | wall p90 |
|---|---:|---:|---:|---:|
| Build | 34 | 346 | 338 | 670 |
| Validate Embedded Viewer | 44 | 74 | 70 | 88 |
| **Suppressions** | 41 | **20** | — | 24 |
| Changelog Lint | 37 | 11 | 10 | 16 |

Build's 670s p90 is the four sandbox-tools runs, not a tail on ordinary pushes.

Split by what the push touched:

| class | n | wall med | p90 | Build runner-min/run |
|---|---:|---:|---:|---:|
| sandbox-tools | 4 | 821 | 983 | 32.5 |
| code + docs | 3 | 403 | 413 | 21.6 |
| code only | 27 | **341** | 376 | 15.4 |

No docs-only and no design/md-only pushes landed in this window, so #299 gets no
observation (see impact verification). A push now costs **18.5 runner-minutes**
end to end (median over 52 pushes, all four workflows), against 17.6 last window
— the whole increase is the new `Suppressions` workflow.

### Critical path

Binding (last-finishing) job across the 34 successful Build runs:

| binding job | runs | wall median | median margin over runner-up |
|---|---:|---:|---:|
| `test (3.11)` | 15 | 341s | 14s |
| `test (3.10)` | 12 | 341s | 10s |
| `slow-tool-tests-dev` | 4 | 821s | 486s |
| `docs` | 3 | 403s | 69s |

The two `test` legs bind 27 of 34 runs but by only 10–14s, so removing 15s from
`test` moves those runs by ~14s and then hits the other leg. This is the
structural reason proposal 1 matters more than its per-leg number suggests:
**it is the only lever large enough to clear both legs at once.**

### Queue

656 independent-job samples: median **3s**, p90 23s, p95 33s, p99 61s, **max
69s**; 38 samples above 30s, 8 above 60s. Per hour:

| hour (UTC) | runs | job samples | queue med | queue p90 | max |
|---|---:|---:|---:|---:|---:|
| **08-31 20** | **64** | **237** | **3s** | 33s | 69s |
| 08-31 19 | 47 | 172 | 3s | 24s | 39s |
| 08-31 21 | 24 | 90 | 3s | 4s | 20s |
| 09-01 01 | 16 | 54 | 3s | 20s | 20s |
| everything else | ≤8 | ≤30 | 2–4s | 3–11s | ≤12s |

The densest hour in the series — 64 runs, 237 independent-job records — held a
3s median and a 69s worst case. Eighth window with no evidence of pool
saturation.

## The headline: the control channel costs 214ms of every `eval()`

Measured in this sandbox (Python 3.11, `uvicorn 0.52.4`, repo at `main`).
Per-eval cost is the median of 6 one-sample `mockllm/model` evals with
`display="none"` in a warm process:

| variant | per `eval()` |
|---|---:|
| default (`ctl_server` on) | **249ms** |
| `ctl_server=False` | **35ms** |
| difference | **214ms** |

Where the 214ms goes (median of 5 `ControlServer` start/stop cycles):

| phase | ms | what |
|---|---:|---|
| `_build_app()` | 30.0 | 28 FastAPI routes → 141 pydantic `TypeAdapter`s, rebuilt from scratch every eval |
| `start()` | 29.7 | discovery-dir prepare, AF_UNIX bind, uvicorn `serve()` launch |
| `stop()` | **100.8** | almost entirely waiting for uvicorn to notice `should_exit` |

`stop()` sets `should_exit = True` and awaits the serve task, but uvicorn only
re-reads that flag once per tick and its tick is a fixed `await
asyncio.sleep(0.1)` in `Server.main_loop`. So every eval's teardown blocks for
up to a full 100ms tick doing nothing. There is no uvicorn setting for the
interval.

The PR-gate cost, from a controlled A/B on this repo — same commit, same
machine, 4 xdist workers, an autouse fixture forcing `resolve_ctl_server` to
disabled as the only difference:

| arm | tests | wall | test worker time |
|---|---|---:|---:|
| **full suite**, baseline | 10,662 passed / 4,557 skipped | **725.8s** | **697.6s** |
| **full suite**, ctl server off | 10,648 passed / 14 failed / 4,557 skipped | **529.0s** | **512.3s** |
| delta | | **−196.8s (−27%)** | **−185.3s (−27%)** |
| eval-heavy 7-path subset, baseline | 1,134 passed / 271 skipped | 137.9s | — |
| eval-heavy 7-path subset, ctl off | 1,134 passed / 271 skipped | 76.1s | **−45%** |

(These are local numbers on a 4-core sandbox, and the tree carries this
branch's model-info fix, so the absolute worker time is below CI's 852.9s. The
ratio is the transferable part.)

The band shift is the crispest way to see it — the "Where the time sits"
banding below, recomputed on the two local arms:

| band | baseline tests | baseline worker-s | ctl-off tests | ctl-off worker-s |
|---|---:|---:|---:|---:|
| **0.1–1s** | 1,031 | 370.3 | **650** | **203.1** |
| <0.1s | 14,050 | 41.9 | 14,461 | 63.4 |

**381 tests leave the 0.1–1s band outright**, taking 167s of worker time with
them. That band is 49% of test time in CI, and this says a large part of it is
not what those tests assert — it is what `eval()` costs.

**The 14 failures are the whole coverage story, and they are narrow**: 8 in
`tests/_control/test_launch_handoff.py`, 5 in
`tests/_control/test_eval_set_integration.py`, and 1 in
`tests/test_eval_set_selection.py::test_eval_set_selection_parks_for_keep_alive`.
Every one has the control channel as its subject — a keep-alive park, a launch
handoff, a `ctl ls` against a live run. Nothing else in 10,662 tests depends on
the server being up, which is what makes the opt-out-marker shape workable.

`INSPECT_EVAL_CTL_SERVER=false` — which `docs/control-channel.qmd` recommends
"to disable it across a CI job" — does not reach this path: it is wired as a
click `envvar` on the CLI options only, so in-process `eval()` calls from pytest
ignore it.

Why this is filed rather than shipped: the two candidate fixes are both
maintainer decisions. The product-side one (cheaper start/stop) is bounded by
uvicorn's poll interval for half the cost; the test-side one (an autouse
fixture with a `@pytest.mark.real_ctl_server` opt-out, exactly the shape
`tests/conftest.py::fast_retry_waits` already uses for retry backoff) moves
"eval works with the control server on" — the *default* configuration — out of
the bulk of the suite and into the 14 tests that assert on it directly. That
trade-off belongs to a maintainer.
[#393](https://github.com/meridianlabs-ai/inspect_ai/issues/393).

## Where the pytest step actually goes

Timestamps from the raw job log of `test (3.10)` in upstream run 33473874133:

| phase | seconds | note |
|---|---:|---|
| `uv run` project re-sync | 5.2 | uninstalls 43 packages, reinstalls 45 (proposal 6) |
| startup + collection (5 interpreters) | 50.8 | `test session starts` at 56.0s into the step |
| test execution | 235.8 | 852.9 worker-seconds over 4 workers |
| reporting (durations, summary) | 1.1 | the phase `-ra` emptied; it was ~46s |
| **step total** | **292.9** | window median 300 (3.10) / 304 (3.11) |

Unchanged from last window (5.2 / 51.0 / 246.1 / 0.2). The raw log is **5,555
lines** against ~31,000 before #5075 — `-ra` holding.

## Worker balance (`--dist worksteal`, #4948)

Eighth window holding, from the `test (3.10)` report-log artifact of run
33473874133: per-worker test seconds 217.5 / 207.4 / 212.3 / 215.7 —
**imbalance +4.2s, efficiency 98.1%**, no stragglers.

## Slowest tests

Median seconds per test across the 20 legs mined this window
(`--durations=50 --durations-min=1`, `call` + `setup` + `teardown` summed). 149
tests captured; per-leg tail total **208.5s** (median; 167.1–228.4), against
214.3 last window.

| s | test | classification |
|---:|---|---|
| 11.0 | `test_eval_set_selection.py::test_eval_set_selection_concurrent_workers` | genuinely heavy — three real subprocesses |
| 10.1 | `test_eval_set_scanner.py::test_scout_scan_resume_reruns_failed_scans` | genuinely heavy |
| 10.0 | `test_eval_set.py::test_retry_attempt_killed_mid_sweep_leaves_completed_samples_reusable` | genuinely heavy — kills a live attempt mid-sweep |
| 9.8 | `_control/test_launch_handoff.py::test_eval_detach_hands_off_and_leaves_eval_running` | subprocess launch; pays `import inspect_ai` (#311) |
| 9.3 | `_control/test_launch_handoff.py::test_eval_detach_via_dotenv_detaches_exactly_once` | subprocess launch (#311) |
| 7.0 | `test_eval_set_scanner.py::test_scanner_resume_accumulates_summary_…[s3]` | moto S3 + full eval-set resume |
| 6.9 | `agent/test_agent_bridge.py::test_google_bridge_computer_use_incompatible_model` | ~3.9s is `traceback_ansi` rendering (#374) |
| 6.9 | `_control/test_launch_handoff.py::test_eval_json_redirects_subprocess_stdout_to_stderr` | subprocess launch (#311) |
| 6.7 | `agent/test_agent_bridge.py::test_google_bridge_streaming_not_supported` | ~3.9s is `traceback_ansi` rendering (#374) |
| 6.1 | `test_eval_set.py::test_eval_set_previous_task_args` | ~5s real sleep around `keyboard_interrupt(2)` |
| 6.0 | `_control/test_launch_handoff.py::test_eval_detach_fails_when_control_bind_fails` | subprocess launch (#311) |
| 5.9 | `log/test_eval_log_config.py::test_eval_log_run_config_round_trip` | genuinely heavy |
| 4.3 | `_control/test_pause.py::test_eval_hard_pause_time_limit_reap_reparks_grader` | timer-bound |
| 4.2 | `test_sample_limits.py::test_working_limit` | timer-bound |
| 4.1 | `test_sample_shuffle.py::test_sample_shuffle` | duplicate-ish with `test_sample_shuffle_limit` |

Same cast as the last four reports. Heaviest files by total worker time in the
report log (not just the tail): `test_eval_set_scanner.py` 61.5s,
`test_eval_set.py` 56.3s, `_control/test_launch_handoff.py` 50.4s,
`test_sample_limits.py` 37.9s, `_control/test_eval_set_integration.py` 32.6s,
`test_eval_set_selection.py` 21.5s, `_view/test_view_server.py` 19.6s,
`agent/deepagent/test_deepagent_background.py` 19.2s.

### No per-test regression

Diffing per-test medians against the 2026-08-31 snapshot over the 96 tests in
both tails: sum **319.5 → 323.2s**, largest increase **+1.5s**
(`test_time_limit_scorer`), largest decrease **−0.9s**
(`test_write_s3_eval_header_only_compacts_zip`). 53 tests entered the tail and
48 left it, all near the 1s cutoff — ranking-boundary churn, not new cost.

### Docker-trap sweep

Unchanged for six runs: **6** test functions pair `skip_if_no_docker` with no
`@pytest.mark.slow` — `util/sandbox/test_docker_compose_config.py` ×3 (ungated,
never start a container), `tools/test_think_tool.py` ×2 and
`agent/test_agent_docs.py::test_agent_collect` (gated by `skip_if_no_anthropic` /
`skip_if_no_openai`). No new offenders.

## Suite size

| snapshot | collected items | pytest wall (median leg) | Build wall (success) |
|---|---:|---:|---:|
| 2026-08-21 | 13,370 | 290.7 | 362.5 |
| 2026-08-23 | 13,410 | 299.3 | 354.0 |
| 2026-08-25 | 13,449 | 304.8 | 353.0 |
| 2026-08-27 | 14,123 | 328.7 | 390.0 |
| 2026-08-29 | 14,673 | 287.1 | 342.0 |
| 2026-08-31 | 14,950 | 290.3 | 338.0 |
| 2026-09-01 | **15,220** | **289.6** | **346.0** |

+270 collected items in one day, and pytest wall is flat (−0.7s). Top-level test
functions on `main` at 12:00 UTC (`^(async )?def test_` under `tests/`,
re-derived for every date with one metric):

| date | test functions | Δ |
|---|---:|---|
| 2026-08-25 | 7,883 | — |
| 2026-08-27 | 8,192 | +309 (2d) |
| 2026-08-29 | 8,358 | +166 (2d) |
| 2026-08-31 | 8,468 | +110 (2d) |
| 2026-09-01 | **8,656** | **+188 (1d)** |

### Where the time sits (report log, 15,226 tests, 852.9 worker-seconds)

| band | tests | worker-s | share |
|---|---:|---:|---:|
| ≥5s | 12 | 95.2 | 11.2% |
| 1–5s | 149 | 263.3 | 30.9% |
| **0.1–1s** | **1,208** | **419.4** | **49.2%** |
| <0.1s | 13,857 | 75.0 | 8.8% |

Phases: call 801.5s, setup 32.3s, teardown 19.2s. 10,664 passed, 4,556 skipped —
30% of collected items never run in the PR gate.

The picture is stable across four windows: the ~91% of tests under 0.1s are
under 9% of the time, and the 0.1–1s band is half of it. Proposal 1 is a direct
attack on that band — an unconditional 214ms is exactly what puts a test there.

### Duplicate-coverage and low-value sampling

The AST sweep for identical decorators + signature + body finds the same **11
groups** as the last three reports, membership unchanged; all sub-millisecond,
combined value under 2s. Sampled this window's fastest-growing test files: all
parametrized rather than copy-pasted. Nothing worth deleting.

## Regressions since last report

**None.** Every job is within 1–7s of last window. Test worker time is flat
(852.9s against 892.2s last window on a different commit, well inside the
±60s-of-worker-time noise band this series measured on 2026-08-27), and the
matched per-test tail moved +3.7s over 96 tests.

Red checks a contributor actually sees: `suppressions` 5, `entries-under-unreleased`
3, `mypy` 5, `ruff` 2, `pre-commit` 2, `test (3.11)` 2, `slow-tool-tests-dev` 1.
Every one is branch-specific — 9 of the 30 failures are a single WIP branch
(`feature/eval-set-selection-scanners`) pushing repeatedly. **Two `test`-leg
failures in 200 runs**, both on one branch.

## Waste

- **Cancelled superseded jobs: 71.2 runner-minutes** across 31 jobs / 8
  cancelled runs (was 36.2), led by `test (3.10)` 25.7 and `test (3.11)` 14.4.
  Twice last window's supersession, in a window with five times the push
  density — the expected shape.
- **Failed jobs: 30.3 runner-minutes** (was 4.6), led by `test (3.11)` 10.6 and
  `slow-tool-tests-dev` 9.6.
- **Duplicated Quarto renders: ~165 runner-minutes.** 30 of 77 distinct
  `docs-render-*` keys exist under both a PR merge ref and `refs/heads/main`,
  created 5–8 minutes apart, at ~330s a render, over the seven days the cache
  index covers. Up from 14 keys / ~76 minutes last window.
- **Compute: 942 runner-minutes** per 200 runs (Build 797, Viewer 128,
  Suppressions 13, Changelog Lint 5). Not comparable to last window's 1,231 —
  this window is 10.2h against 52.6h and has a different job mix.
- **Runs that never ran: 6 `action_required`** (was 21).
- **Overhead-dominated jobs:** `changes` 7s, `detect-slow` 9s,
  `submodule-on-main` 8s, `ruff` 10s, `suppressions` 16s. ~50s of runner time
  per push, none of it on the critical path — but now five jobs rather than
  four.
- **`uv run` re-sync:** 5.2s per `test` leg (proposal 6).

## Impact verification (previous runs' changes)

- **The model-info fixture fix (this branch, not yet upstream) — still
  unlanded, and still worth what it measured.** Upstream run 33473874133's
  report log shows `tests/model/test_model_info.py` at **17.4s of worker time
  over 47 tests (370ms mean)**, the pre-fix figure; the fix takes those tests to
  under 1.5s. It ships in PR #375, which is still open on the fork awaiting
  maintainer promotion.
- **#5075 (`-rA` → `-ra`) — holding, third window.** Reporting phase 1.1s, raw
  test-leg log 5,555 lines.
- **#297 (docs render cache) — fifth window, hit rate now 0.** 0 hits in 5 docs
  jobs, including two consecutive pushes on the same branch
  (`grep-extended-regexp`) where the second still rendered — the same-branch
  re-push case that produced every hit in earlier windows now misses too,
  because `main` moved in between. Cache-index evidence above; posted to #317.
- **#299 (`design/**` excluded from the test filter) — no observation.** No
  design/md-only push landed in this window.
- **#4948 (`--dist worksteal`) — holding, eighth window** (+4.2s imbalance,
  98.1% efficiency).
- **#4760 (`test_package` pre-installed) — holding**: no `test_extensions` test
  appears in the durations tail or above 0.3s in the report log.
- **#4935 (`blob:none` checkouts) — holding**: checkout is 3–5s median across
  every job; `test`-leg checkout p90 8s against a 3s median is the one
  always-run step whose p90 exceeds 2× its median, and at 5s of absolute spread
  it is not worth chasing.
- **#374 (traceback rendering) — unchanged, still open.** The two Google bridge
  tests are still 6.9s and 6.7s.

## Proposals (ranked)

1. **Stop paying 214ms of control-server startup on every `eval()`.** NEW, and
   the largest measured lever in this series. A one-sample `mockllm` eval is
   249ms with the control channel and 35ms without; the 214ms splits 30ms
   building an identical 28-route FastAPI app, 30ms binding, and **100ms waiting
   out uvicorn's fixed 0.1s `should_exit` poll**. 796 test functions across 153
   files call `eval()`/`eval_set()` directly, and a full-suite A/B on 4 workers
   runs **725.8s → 529.0s of wall (−27%)**, **697.6s → 512.3s of test worker
   time**, with **381 tests leaving the 0.1–1s band** — the band that is 49% of
   CI test time. Extrapolated to a CI leg (236s of execution over 4 workers,
   853 worker-seconds), that is on the order of **50–60s off both `test` legs**,
   which is the only lever in the current data large enough to clear the 10–14s
   margin on *both* at once. Two independent fixes — cheaper start/stop (helps
   real users too, but half the cost is uvicorn's poll interval) and a test-suite
   default with a `@pytest.mark.real_ctl_server` opt-out (the shape
   `fast_retry_waits` already uses; only 14 tests would need the marker). Not
   shipped: the test-side fix moves coverage of the *default* configuration out
   of the bulk of the suite, which is a maintainer call, and the product-side fix
   is a change to eval teardown semantics. Status: **new, filed as
   [#393](https://github.com/meridianlabs-ai/inspect_ai/issues/393)**.

2. **Fix the docs render cache key so `main` churn stops invalidating it.**
   Carried, and the evidence doubled. Hit rate by window: 14%, 11%, 8%, 5%,
   **now 0 of 5**. The cache index holds 107 entries over 77 distinct keys with
   **4 ever re-read**, and **30 keys exist twice — once under a PR merge ref,
   once under `refs/heads/main`**, 5–8 minutes apart: ~165 runner-minutes of
   provably identical renders in seven days. New this window: even the
   same-branch re-push case (the only case that ever hit) now misses. Cause
   unchanged — on `pull_request` the checkout is the merge ref, so
   `hashFiles('docs/**', 'requirements-doc.txt', 'src/inspect_ai/**')` hashes the
   PR merged into current `main`. Proposed key: `docs/**` +
   `requirements-doc.txt` + the PR's *own* source delta. Est. ~360s of job exec
   per hit and ~69s of Build wall on the runs where `docs` binds. Structural
   (workflow change this run cannot push). Status: carried,
   [#317](https://github.com/meridianlabs-ai/inspect_ai/issues/317),
   re-evidenced today.

3. **Unblock the scheduled run.** Re-probed today with real attempts:
   - *No upstream write* — `repos/UKGovernmentBEIS/inspect_ai` reports
     `{"admin":false,"maintain":false,"pull":true,"push":false,"triage":false}`
     for this token; PR creation attempted again at the end of this run (result
     recorded in `prs.md`). This is why every run's output lands as a fork PR
     needing maintainer promotion.
   - *No `workflow` scope* — blocks proposals 2, 5 and 6, which are all
     workflow-file changes.
   - *`.claude/**` unwritable by the agent's edit tooling* — blocks proposal 10.

   Consequence unchanged: the run can ship `src/` and `tests/` changes (as
   2026-08-31 did) but no workflow-level lever, including proposal 2. Structural
   (credentials + harness policy). Status: carried, re-evidenced on
   [#298](https://github.com/meridianlabs-ai/inspect_ai/issues/298).

4. **Stop rendering `traceback_ansi` eagerly (or stop syntax-highlighting it).**
   Unchanged: ~60s of worker time per `test` leg and 0.3–4s of CPU per distinct
   error for real users, spent in pygments lexing whole source files for
   `rich.traceback`. The two Google bridge tests still pay ~3.9s each and still
   sit 7th and 9th in the tail. Product change with a public field
   (`EvalError.traceback_ansi`) in play. Status: carried,
   [#374](https://github.com/meridianlabs-ai/inspect_ai/issues/374).

5. **Cache pytest's assertion-rewrite bytecode across runs.** Unchanged and
   re-confirmed at 50.8s of the 292.9s step (17%). Fix shape: restore
   `**/__pycache__` from `actions/cache` keyed on a hash of `src/**/*.py` +
   `tests/**/*.py`, normalizing source mtimes deterministically after checkout in
   both the producing and consuming run (pytest validates a rewritten pyc against
   source mtime + size). Est. ~30s off both `test` legs; needs one CI experiment.
   What does not work, both measured on 2026-08-29: `compileall` and `uv`'s
   `compile-bytecode`. Structural (workflow change). Status: carried.

6. **`uv run` re-syncs the environment the previous step just installed.**
   5.2s per `test` leg, uninstalling 43 packages and reinstalling 45 before
   pytest starts. `uv run --no-sync pytest` (or `.venv/bin/pytest`) removes it.
   Workflow hygiene, same push blocker as 2 and 5 — fold into whichever workflow
   change lands first. Status: carried, low.

7. **Defer the `acp.schema` import.** Unchanged: 483ms of the 1.70s self-time of
   `import inspect_ai`, ~7x the next-largest module, reached through two eager
   edges. Paid by 5 interpreters per leg plus the four
   `_control/test_launch_handoff.py` tests that hold slots 4, 5, 8 and 11 of the
   tail. Product change with a public-API surface. Status: carried,
   [#311](https://github.com/meridianlabs-ai/inspect_ai/issues/311).

8. **Test-volume policy — it is the 0.1–1s band that matters.** Fourth window
   confirming it: 13,857 tests under 0.1s are 8.8% of test time; 1,208 tests
   between 0.1s and 1s are 49.2%. Growth continues at ~+190 test functions/day
   this window. Proposal 1 reframes the question usefully: much of that band is
   not what the tests *assert*, it is what `eval()` *costs*. Structural. Status:
   carried, **sharpened by proposal 1**.

9. **`tests/util/test_display_counter.py` sleeps 6 × 1.1s for 2 throttle paths.**
   Carried from last window at 9.0s of worker time (measured again in this
   window's report log, n=6, 1.46–1.53s each). Re-examined for a mock-clock fix
   this run and rejected: `inspect_ai.util._throttle` reads `time.time()`
   directly *and* schedules a real `anyio.sleep(remaining)` trailing-edge fire in
   a background task, so faking the clock without also faking the sleep changes
   what the test exercises. The honest options remain a coverage judgement
   (drop the sleep for the params whose `@throttle(5)` a 1.1s sleep can never
   fire) or an injectable throttle window (product change). Status: carried.

10. **Collector: validate the run window, and fetch more than 200 runs.** Did
    *not* misfire this run — one attempt, contiguous, no gap over 3h. But a
    second problem surfaced: at 19.6 runs/hour a 200-run snapshot spans **10.2
    hours**, while the scheduled cadence is ~2 days, so **17.3h between this
    window and the last is uncovered by either snapshot** and the series is
    sampling a shrinking fraction of CI. Both fixes are one file
    (`.claude/skills/ci-perf/scripts/collect_ci_data.py`) and still
    uncommittable (proposal 3). Status: carried, **broadened**.

11. **Runner pool size for burst absorption.** Eighth consecutive window with no
    supporting evidence, and this one is the strongest counter-evidence yet: the
    densest hour in the series (64 runs, 237 independent-job records) held a 3s
    median, a 33s p90 and a 69s max. Structural/cost. Status: carried,
    **recommend dropping**.

12. **Merge the 4 Viewer jobs into 1–2** — required-check rename. The Viewer
    workflow is 74s wall and 2.9 runner-min. With `Suppressions` now a fifth
    per-push workflow-or-job, job-count reduction is marginally more interesting
    than last window, but still not a wall-clock lever. Structural. Status:
    carried, low.

13. **Duplicate and near-duplicate test cleanups.** The strict AST sweep finds
    the same 11 groups as the last three reports; the real-sleep candidates are
    unchanged. Combined value under 2s against a coverage risk on every item.
    Status: carried, low.

14. **Policy consistency: docker tests without `@pytest.mark.slow`.** Still six,
    still ~0.05s combined; the right fix is probably to drop `skip_if_no_docker`
    from the three ungated ones rather than to mark them slow. Zero wall-clock
    impact. Status: carried.

Nothing dropped this report.

## PRs opened by this skill

See `prs.md`. This run's output — the snapshot, this report and the ledger
update — ships on the branch of the still-open previous PR
([meridianlabs-ai/inspect_ai#375](https://github.com/meridianlabs-ai/inspect_ai/pull/375)),
per the unattended rule that a run pushes onto an open predecessor rather than
opening a second PR. **No code fix this run**: the window's one large finding is
proposal 1, and both of its candidate fixes are maintainer decisions rather than
mechanical ones, so it was filed as
[#393](https://github.com/meridianlabs-ai/inspect_ai/issues/393) with the full
measurement. New evidence was posted to
[#317](https://github.com/meridianlabs-ai/inspect_ai/issues/317).
