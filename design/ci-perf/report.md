# CI performance report — 2026-08-31

Data: 200 PR runs, 2026-08-28 21:25 .. 2026-08-31 02:01 UTC (**52.6h**, 3.8
runs/hour). Snapshot: `history/2026-08-31.json`. Previous: 2026-08-29 (200 runs
over 32.4h, ending 07:55 UTC), so the two windows **overlap by ~10.5h** at this
window's older edge — a slower weekend (3.8 runs/h against 6.2) means 200 runs
now reaches further back. The four gaps >3h inside the window (9.2h from 08-30
02:47, then 5.1h, 3.9h, 3.4h) are quiet periods, verified against run
timestamps, not collector staleness. Produced by the unattended scheduled run
([workflow run](https://github.com/meridianlabs-ai/actions/actions/runs/33377127128)).

## Summary

**This run ships a code fix — the first in eight runs.** An autouse fixture in
four test files calls `clear_model_info_cache()` before and after every test,
and that function dropped the *parsed built-in model database* along with the
per-test state. Nothing mutates that database (`set_model_info` and
`set_model_cost` both write to the custom registry, the latter via
`model_copy`), and nothing in `src/` calls the function at all — it exists for
tests — so the only effect was to make 191 tests re-read and re-parse the model
DB at ~0.19s a time. Keeping it: **49.9s → 31.9s** over the affected files
locally (205 tests, single process, 3.11), and those files cost **73.5s (3.10) /
55.5s (3.11)** of worker time in today's CI report logs. See "The shipped fix"
below.

**`docs` is now unambiguously the long pole, and the render cache is at its
worst.** `docs` executes at 391s, binds 13 of 49 successful Build runs, and when
it binds it does so by a **105s median margin** over the runner-up — every
docs-touching push sits at 401–405s of wall clock against 337s for a code-only
one. The cache from #297 hit **1 of 19 docs jobs (5%)**, against 14%, 11% and 8%
in the three previous windows. New evidence for why, from the repository's own
cache index: 53 `docs-render-*` entries over 39 distinct keys, **3 ever
re-read**, and **14 keys exist twice — once under a PR merge ref and once under
`refs/heads/main`**. The same input set is being rendered twice, ~328s a time,
because a PR-scoped entry is invisible to `main` and `main`'s entry arrives
after the PR has already paid. [#317](https://github.com/meridianlabs-ai/inspect_ai/issues/317)
stays proposal 1.

**`slow-tool-tests-release` executed for the first time in this series**, six
times, and in doing so closed the last unverified leg of #4935's `blob:none`
rollout: its checkout is **5–8s**. All six runs failed fast (31–49s) at `Fetch
and verify published non-dev sandbox-tools binaries` — the designed behaviour
for a PR that bumps the injectable source before binaries are published, not a
CI defect.

**Queue remains a non-issue — seventh window running.** Median 3s, p90 8s, p95
20s, max 63s over 847 independent-job records; exactly one wait above 60s.

**Two of the three scheduled-run blockers still stand** (proposal 2), both
re-probed with real attempts today. The one that did not bite is the reason this
run could ship code at all: the fix lives in `src/` and `tests/`, not in
`.github/workflows/**`.

## Queue vs execution

Median execution / queue over successful jobs, this window against the last.
Queue is measured from run start for independent jobs and from the predecessor's
completion for dependent ones (`needs` map read from `.github/workflows/build.yml`:
`docs`/`sandbox-tools-unit` ← `changes`; `check-version-bump`/`slow-tests` ←
`detect-slow`; `slow-tool-tests-{dev,release}` ← `detect-slow` +
`check-version-bump`). p90 is linear interpolation, as in every prior report.

| workflow | job | n | exec med | prev | exec p90 | queue med | queue p90 |
|---|---|---:|---:|---:|---:|---:|---:|
| Build | slow-tool-tests-dev | 8 | 826 | 754 | 901 | 2 | 3 |
| Build | **docs** | 19 | **391** | 392 | 416 | 3 | 3 |
| Build | test (3.11) | 55 | 324 | 330 | 338 | 3 | 17 |
| Build | test (3.10) | 55 | 321 | 324 | 336 | 3 | 18 |
| Build | sandbox-tools-unit | 6 | 129 | — | 132 | 2 | 3 |
| Build | mypy (3.10) | 61 | 89 | 90 | 96 | 3 | 20 |
| Build | mypy (3.11) | 61 | 88 | 88 | 94 | 3 | 16 |
| Viewer | viewer-tests | 61 | 67 | 69 | 71 | 3 | 4 |
| Viewer | check-schema-and-types | 61 | 55 | 59 | 62 | 3 | 4 |
| Viewer | dist-validation | 61 | 34 | 35 | 40 | 3 | 4 |
| Build | pre-commit | 60 | 32 | 33 | 36 | 3 | 20 |
| Build | package | 61 | 28 | 30 | 34 | 3 | 20 |
| Build | ruff | 61 | 10 | 11 | 12 | 3 | 20 |
| Build | check-version-bump | 9 | 10 | 7 | 10 | 3 | 6 |
| Viewer | submodule-on-main | 61 | 8 | 9 | 10 | 3 | 4 |
| Build | detect-slow | 61 | 8 | 9 | 10 | 3 | 19 |
| Changelog Lint | entries-under-unreleased | 49 | 7 | 7 | 8 | 3 | 3 |
| Build | changes | 61 | 7 | 8 | 9 | 3 | 20 |

`sandbox-tools-unit` is the one large mover: **260s in the 2026-08-27 window,
129s now** (it did not run at all last window). The saving is in its own
dependency install, not in anything this series changed.

Workflow wall clock, successful runs only (the 21 `action_required` runs that
sit unapproved record a 0s wall and would drag every median down):

| workflow | n | wall med | prev | wall p90 | prev p90 |
|---|---:|---:|---:|---:|---:|
| Build | 49 | 338 | 342 | 426 | 412 |
| Validate Embedded Viewer | 61 | 70 | 74 | 78 | 80 |
| Changelog Lint | 49 | 10 | 10 | 12 | 12 |

Split by what the push touched:

| class | n | wall med | p90 | Build runner-min/run |
|---|---:|---:|---:|---:|
| sandbox-tools | 2 | 820 | 834 | 35.0 |
| docs only (test legs no-op) | 5 | **405** | 412 | 10.8 |
| code + docs | 11 | **401** | 433 | 20.7 |
| code only | 29 | **337** | 346 | 15.0 |
| design/md only (test legs no-op) | 2 | 90 | 92 | 4.3 |

A push costs **17.6 runner-minutes** end to end (median over 71 pushes, all
three workflows).

### Critical path

Binding (last-finishing) job across the 49 successful Build runs:

| binding job | runs | wall median | median margin over runner-up |
|---|---:|---:|---:|
| `test (3.11)` | 18 | 337s | 12s |
| `test (3.10)` | 14 | 338s | 18s |
| **`docs`** | 13 | **405s** | **105s** |
| `slow-tool-tests-dev` | 2 | 820s | 373s |
| `mypy` (3.10/3.11) | 2 | 88–92s | 4–14s |

The two `test` legs bind by 12–18s, so shaving a further 15s off `test` moves
the median of those runs by 15s at best and then hits the other leg. `docs`
binds by 105s: it is the only place in the current topology where a single job
is decisively the critical path.

## The shipped fix: the model-info database was re-parsed once per test

Four test files carry an autouse fixture that calls `clear_model_info_cache()`
before and after every test — `tests/model/test_model_info.py` (47 tests),
`tests/model/test_canonical_names.py` (84), `tests/model/providers/test_model_family.py`
(26) and `tests/test_sample_limits.py` (34): **191 tests**. The function reset
four globals, two of which are per-test state (`_custom_models`, `_result_cache`)
and two of which are the immutable built-in database and its lookup index
(`_model_info_cache`, `_lookup_index`). Dropping the latter pair forced
`read_model_info()` on the next lookup.

Measured cost of one reload, locally: **0.185s** (mean of 5, clear + lookup),
against 0.0000s for a warm lookup.

Measured cost of the fixture, from today's CI `--report-log` artifacts
(run 33343746910, both legs):

| file | tests | 3.10 | 3.11 |
|---|---:|---:|---:|
| `tests/test_sample_limits.py` | 34 | 37.5s | 33.9s |
| `tests/model/test_model_info.py` | 47 | 23.6s | 11.8s |
| `tests/model/providers/test_model_family.py` | 26 | 7.4s | 6.0s |
| `tests/model/test_canonical_names.py` | 84 | 5.1s | 3.8s |
| **total** | **191** | **73.5s** | **55.5s** |

Local before/after, same commit, single process, Python 3.11, two reps each
(the four files above plus `test_sync_models.py` and `dataset/test_model_info.py`
as read-only controls — 205 tests):

| variant | pytest time |
|---|---:|
| baseline | 49.85s |
| DB kept across clears | **31.94s** |

`tests/model/test_model_info.py` alone goes **11.02s → 2.27s**. All 205 tests
pass either way, and the full local suite passes with the fix (see the PR).

Safety: `clear_model_info_cache` has no caller in `src/` — five test files are
its only users — so this cannot change product behaviour. `set_model_info` and
`set_model_cost` write only to `_custom_models` (the latter via
`info.model_copy(...)`, so the DB entry is not mutated), `_lookup_index` is
derived from the DB alone and was already never rebuilt on registration, and no
test patches `read_model_info` or the data files, so nothing depends on the
re-read.

Prediction was **−18s of worker time on the 3.11 leg and −25s on the 3.10 leg**
(the model-info file is twice as expensive there). Because that sits *below* the
±15s per-leg noise band this series measured on 2026-08-27, the check has to be a
per-file diff of the report-log artifacts rather than a wall-clock comparison —
and this run's own PR provided one within the hour, since the fix touches `src/`
and therefore actually runs the test legs:

| file | tests | 3.10 before → after | 3.11 before → after |
|---|---:|---|---|
| `tests/test_sample_limits.py` | 34 | 37.5 → 27.9s (−9.6) | 33.9 → 27.1s (−6.8) |
| `tests/model/test_model_info.py` | 47 | 23.6 → **0.7s** (−22.9) | 11.8 → **1.3s** (−10.5) |
| `tests/model/providers/test_model_family.py` | 26 | 7.4 → **0.2s** (−7.2) | 6.0 → **0.1s** (−5.9) |
| `tests/model/test_canonical_names.py` | 84 | 5.1 → **0.5s** (−4.6) | 3.8 → **0.3s** (−3.5) |
| **total** | **191** | **73.5 → 29.2s (−44.3)** | **55.5 → 28.9s (−26.6)** |

**Prediction beaten, by 1.8x on 3.10 and 1.5x on 3.11** — the local single-process
measurement understated the reload, which costs more on a CI runner than on this
sandbox. Three of the four files collapse to under 1.5s, which is the signature
of the fixture rather than of anything else moving. Whole-leg worker time went
892.2 → 839.1s (3.10) and 903.0 → 843.4s (3.11); the residual beyond the affected
files (−8.8s and −33.0s) is well inside the ±60s-of-worker-time noise band and
nothing should be read into it. Comparison is upstream run 33343746910 against
fork run 33379153161, 14,952 → 14,950 collected items (2 test IDs removed by
`main` in between, both sub-millisecond).

## Where the pytest step actually goes

Timestamps from the raw job log of `test (3.10)` in run 33343746910:

| phase | seconds | note |
|---|---:|---|
| `uv run` project re-sync | 5.2 | uninstalls 40 packages, reinstalls 42 (proposal 5) |
| startup + collection (5 interpreters) | 51.0 | `test session starts` at 56.1s into the step |
| test execution | 246.1 | 892.2 worker-seconds over 4 workers |
| reporting (durations, summary) | 0.2 | this is the phase `-ra` emptied; it was ~46s |
| **step total** | **294.8** | window median 294.0 |

Unchanged from last window (5.1 / 50.2 / 231.3 / 1.4). Startup is **19% of the
step** and remains the second-largest identified lever after `docs`; the
assertion-rewrite diagnosis and the two rejected fixes (`compileall`, `uv`'s
`compile-bytecode`) are in the 2026-08-29 report and are not re-measured here.
The raw log is **5,493 lines**, against ~31,000 before #5075 — `-ra` holding.

## Worker balance (`--dist worksteal`, #4948)

Seventh window holding, from both report-log artifacts of run 33343746910:

| leg | per-worker test seconds | imbalance | efficiency |
|---|---|---:|---:|
| 3.10 | 221.5 / 228.4 / 215.3 / 227.1 | +5.4s | 97.7% |
| 3.11 | 226.7 / 223.8 / 223.5 / 229.0 | +3.2s | 98.6% |

## Slowest tests

Median seconds per test across the 20 legs mined this window
(`--durations=50 --durations-min=1`, `call` + `setup` + `teardown` summed). 144
tests captured; per-leg tail total **214.3s** (median; 165.8–225.6), down from
last window.

| s | test | classification |
|---:|---|---|
| 11.2 | `test_eval_set_selection.py::test_eval_set_selection_concurrent_workers` | genuinely heavy — three real subprocesses |
| 10.5 | `test_eval_set_scanner.py::test_scout_scan_resume_reruns_failed_scans` | genuinely heavy |
| 10.5 | `test_eval_set.py::test_retry_attempt_killed_mid_sweep_leaves_completed_samples_reusable` | genuinely heavy — kills a live attempt mid-sweep |
| 9.9 | `_control/test_launch_handoff.py::test_eval_detach_hands_off_and_leaves_eval_running` | subprocess launch; pays `import inspect_ai` (#311) |
| 9.4 | `_control/test_launch_handoff.py::test_eval_detach_via_dotenv_detaches_exactly_once` | subprocess launch (#311) |
| 7.2 | `agent/test_agent_bridge.py::test_google_bridge_computer_use_incompatible_model` | ~3.9s is `traceback_ansi` rendering (#374) |
| 7.1 | `_control/test_launch_handoff.py::test_eval_json_redirects_subprocess_stdout_to_stderr` | subprocess launch (#311) |
| 7.0 | `test_eval_set_scanner.py::test_scanner_resume_accumulates_summary_…[s3]` | moto S3 + full eval-set resume |
| 6.5 | `agent/test_agent_bridge.py::test_google_bridge_streaming_not_supported` | ~3.9s is `traceback_ansi` rendering (#374) |
| 6.4 | `log/test_eval_log_config.py::test_eval_log_run_config_round_trip` | genuinely heavy |
| 6.3 | `test_eval_set.py::test_eval_set_previous_task_args` | ~5s real sleep around `keyboard_interrupt(2)` |
| 5.7 | `_control/test_launch_handoff.py::test_eval_detach_fails_when_control_bind_fails` | subprocess launch (#311) |
| 4.3 | `_control/test_pause.py::test_eval_hard_pause_time_limit_reap_reparks_grader` | timer-bound |
| 4.3 | `test_sample_shuffle.py::test_sample_shuffle` | duplicate-ish with `test_sample_shuffle_limit` |
| 4.3 | `test_sample_limits.py::test_working_limit` | timer-bound |

Same cast as the last three reports. Heaviest files in the tail:
`test_eval_set.py` 74.1s, `_control/test_launch_handoff.py` 42.9s,
`test_eval_set_scanner.py` 37.4s, `test_sample_limits.py` 28.8s,
`_control/test_eval_set_integration.py` 25.7s, `agent/test_agent_bridge.py` 19.5s.

### No per-test regression

Diffing per-test medians against the 2026-08-29 snapshot: largest increase
**+1.2s** (`test_scout_scan_resume_reruns_failed_scans`, 9.3 → 10.5s), largest
decrease **−2.4s** (`test_task_identifier_with_task_limits`, 5.0 → 2.7s), and the
sum of tail medians fell **454.3 → 427.7s**. Fifteen tests entered the tail and
ten left it, all in the 2.4–3.1s band — ranking-boundary churn, not new cost.

### A new finding: 6.6s of sleeping in `tests/util/test_display_counter.py`

`test_can_display_counter` is parametrized over all six `DisplayType` values and
each variant sleeps a real **1.1s** — "the footer is throttled at 1 Hz, so sleep
for longer than that" — inside an otherwise trivial mock-model eval. The file
costs **8.9s (3.10) / 10.5s (3.11)** of worker time, 1.45–1.78s per variant, for
a test whose own comment says it "doesn't actually verify the UI; it just
exercises the code path".

Two of the six sleeps provably buy nothing: under pytest stdout is not a tty, so
`full`, `rich`, `conversation` and `none` all resolve to `RichDisplay` (1 Hz
footer via `@throttle(1)` on `task_footer`), while `plain` and `log` resolve to
`PlainDisplay`/`LogDisplay`, whose status print is `@throttle(5)` — a 1.1s sleep
can never fire it. So 6 sleeps cover 2 distinct throttle paths, and 2 of them
cover nothing. Not shipped: the honest fix either drops the sleep for the params
that cannot use it (a coverage judgement about a test whose stated purpose is
smoke coverage) or makes the throttle window injectable (a product change).
Proposal 8.

### Docker-trap sweep

Unchanged for five runs: **6** test functions pair `skip_if_no_docker` with no
`@pytest.mark.slow` — `util/sandbox/test_docker_compose_config.py` ×3 (ungated,
never start a container), `tools/test_think_tool.py` ×2 and
`agent/test_agent_docs.py::test_agent_collect` (gated by `skip_if_no_anthropic` /
`skip_if_no_openai`). No new offenders; nothing in the durations tail touches
docker.

## Suite size

| snapshot | collected items | pytest wall (median leg) | Build wall (success) |
|---|---:|---:|---:|
| 2026-08-21 | 13,370 | 290.7 | 362.5 |
| 2026-08-23 | 13,410 | 299.3 | 354.0 |
| 2026-08-25 | 13,449 | 304.8 | 353.0 |
| 2026-08-27 | 14,123 | 328.7 | 390.0 |
| 2026-08-29 | 14,673 | 287.1 | 342.0 |
| 2026-08-31 | **14,950** | **290.3** | **338.0** |

+277 collected items in two days (+1.9%), the smallest two-day jump since
2026-08-25, and pytest wall is flat (+3.2s). Top-level test functions on `main`
at 12:00 UTC: 8,358 (08-29) → 8,371 (08-30) → **8,450** (08-31), i.e. **+92 in
two days** against +166 and +292 in the two windows before.

### Where the time sits (report log, 14,952 tests)

| band | tests | worker-s (3.10) | share | worker-s (3.11) | share |
|---|---:|---:|---:|---:|---:|
| ≥5s | 13 | 106.3 | 11.9% | 113.0 | 12.5% |
| 1–5s | 146 | 262.9 | 29.5% | 295.3 | 32.7% |
| 0.1–1s | 1,211 | 441.2 | 49.5% | 426.7 | 47.3% |
| <0.1s | 13,582 | 81.8 | 9.2% | 68.0 | 7.5% |

Total worker time 892.2s (3.10) / 903.0s (3.11); phases call 837.3 / 860.5,
setup 34.3 / 26.9, teardown 20.7 / 15.6. Median test 3.9ms / 2.7ms. 10,446
passed, **4,506 skipped** — 30% of collected items never run in the PR gate.

The picture the 2026-08-29 report established holds exactly: the ~91% of tests
under 0.1s are 8–9% of the time, and the **0.1–1s band is ~half of it**. This
window's shipped fix is a direct instance — 191 tests dragged into that band by
a fixture, not by what they test.

### Duplicate-coverage and low-value sampling

The AST sweep for identical decorators + signature + body finds **11 groups**,
unchanged in membership from the last two reports (largest is
`test_omitted_returns_none` across five `_cli/test_*_flag.py` files; the rest
are pairs, and `test_message_ids.py` / `test_stable_message_ids.py` remain the
only duplicated *subject*). Every one is sub-millisecond; combined value under
2s. Sampled this window's fastest-growing files
(`test_eval_set_overrides.py` 696 new lines, `test_eval_set_env.py` 708,
`model/providers/test_bedrock_prompt_cache.py` 467): all parametrized rather
than copy-pasted, per-test costs 0.1–0.5s in the eval-invoking cases and under
0.05s elsewhere. Nothing worth deleting.

## Regressions since last report

**None.** Every job is within 1–4s of last window except `sandbox-tools-unit`
(260 → 129s, an improvement) and `slow-tool-tests-dev` (754 → 826s, n=1 → n=8 —
the earlier figure was a single observation). Test worker time is flat (892/903s
against 846s last window on a *different* commit pair; matched per-test medians
fell 454 → 428s). `viewer-tests` continues its recovery (67s). No test crossed
the noise band in either direction.

Red checks a contributor actually sees, for context:
`slow-tool-tests-release` 6 (all the published-binary gate, by design),
`entries-under-unreleased` 5 (CHANGELOG placement), `pre-commit` 1. **Zero
`test`-leg failures in 200 runs**, second window running.

## Waste

- **Cancelled superseded jobs: 36.2 runner-minutes** across 6 cancelled runs,
  down from 97.2 (`test` 34.0, `slow-tool-tests-dev` 2.2). One cancelled
  `slow-tool-tests-dev` had already burned 92s of Docker build.
- **Failed jobs: 4.6 runner-minutes** (was 7.6) — the fail-fast design of the
  release gate is why 6 failures cost 3.6 min.
- **Duplicated Quarto renders:** 14 of 39 distinct `docs-render-*` keys exist
  under both a PR merge ref and `refs/heads/main`, i.e. **~14 × 328s ≈ 76
  runner-minutes** of provably identical renders over the 5 days the cache index
  covers. This is the sharpest evidence #317 has had.
- **Compute: 1,231 runner-minutes** per 200 runs (Build 1,059, Viewer 166,
  Changelog Lint 6) against 1,134 last window. The entire +97 is the
  sandbox-tools chain: 8 `slow-tool-tests-dev` executions at 826s (110 min)
  against 1 at 754s (13 min). Per-push cost is flat.
- **Runs that never ran: 21 `action_required`** (fork PRs awaiting maintainer
  approval) — no compute, but they record a 0s wall, so every statistic here
  filters on conclusion.
- **Overhead-dominated jobs:** `changes` 7s, `detect-slow` 8s,
  `submodule-on-main` 8s, `ruff` 10s (of which ~5s is checkout). ~33s of runner
  time per push, none of it on the critical path.
- **`uv run` re-sync:** 5.2s per `test` leg, ~9 runner-min per window
  (proposal 5).

## Impact verification (previous runs' changes)

- **This run's own fix — verified same-day, prediction beaten.** −44.3s (3.10) /
  −26.6s (3.11) of worker time on the four affected files against a predicted
  −25s / −18s; per-file table above. First time in this series a fix has been
  measured inside the run that shipped it, which is only possible because it
  touches `src/` and so the PR's own test legs execute.
- **#4935 (`blob:none` checkouts) — final leg closed, ten windows later.**
  `slow-tool-tests-release` had never executed in any snapshot, leaving one
  predicted checkout unverified indefinitely. It ran 6 times this window:
  checkout **5–8s**, against the 27–30s full-history checkouts measured before
  the change on its sibling jobs. Every leg of that PR is now confirmed.
- **#5075 (`-rA` → `-ra`) — holding.** pytest wall 287.1 → 290.3s across a
  window that added 277 collected items; the reporting phase is 0.2s and the raw
  test-leg log is 5,493 lines.
- **#297 (docs render cache) — fourth window, and the hit rate is falling.**
  1 hit in 19 docs jobs (5%), against 14%, 11%, 8%. Cache index: 53 entries, 39
  distinct keys, 3 ever re-read (all same-branch re-pushes 4–70 minutes apart),
  16 new keys/day at peak. New: the 14 main/PR duplicate keys above. Evidence
  posted to #317.
- **#299 (`design/**` excluded from the test filter) — holding, sixth and
  seventh observations.** Two design/md-only pushes ran at **90s** Build wall
  with `mypy` binding, against 337s code-only.
- **#4948 (`--dist worksteal`) — holding, seventh window** (+5.4s / +3.2s
  imbalance, 97.7% / 98.6% efficiency).
- **#4760 (`test_package` pre-installed) — holding**: no `test_extensions` test
  appears anywhere in the durations tail or above 0.3s in the report logs.
- **#374 (traceback rendering) — unchanged, still open.** The two Google bridge
  tests are still 7.2s and 6.5s.

## Proposals (ranked)

1. **Fix the docs render cache key so `main` churn stops invalidating it.**
   Top lever, and the case is now overdetermined. `docs` is 391s of exec, binds
   13 of 49 Build runs **by a 105s margin**, and sets a 401–405s floor on every
   docs-touching push against 337s for code-only. Fourth window of measurement
   and the hit rate is *falling*: 5% (1/19), after 14%, 11%, 8%. Cause unchanged:
   on `pull_request` the checkout is the merge ref, so
   `hashFiles('docs/**', 'requirements-doc.txt', 'src/inspect_ai/**')` hashes the
   PR merged into current `main`, and any push to `main` touching
   `src/inspect_ai/**` invalidates every open PR's key. New this window: **14 of
   39 keys exist twice, once under a PR merge ref and once under
   `refs/heads/main`** — ~76 runner-minutes of provably identical renders — which
   also shows the ceiling on the current design, since a PR-scoped entry can
   never be read by `main`. Proposed key: `docs/**` + `requirements-doc.txt` +
   the PR's *own* source delta, not the merged source tree. Est. ~360s of job
   exec per hit and ~27–65s of Build wall on the runs where `docs` binds.
   Structural (workflow change this run cannot push). Status: carried,
   [#317](https://github.com/meridianlabs-ai/inspect_ai/issues/317),
   re-evidenced today.

2. **Unblock the scheduled run.** Re-probed today with real attempts:
   - *No `workflow` scope* — pushed a probe branch carrying a one-byte
     `.github/workflows/build.yml` edit to the fork; rejected with `refusing to
     allow a Personal Access Token to create or update workflow
     .github/workflows/build.yml without workflow scope`. Probe branch never
     landed and was deleted. This blocks proposals 1, 4 and 5.
   - *`.claude/**`* — a plain write under `.claude/skills/ci-perf/` is refused by
     the agent's edit tooling as a sensitive file, asking for an approval no
     scheduled run can give. Harness policy, not a token. This blocks
     proposal 10.
   - *No upstream write* — `repos/UKGovernmentBEIS/inspect_ai` reports
     `push: false` for this token; PR creation attempted at the end of this run
     (result recorded in `prs.md`).

   Consequence, updated: the run *can* ship changes under `src/` and `tests/`,
   which is how this window's fix landed after seven empty runs. What stays
   unshippable is every workflow-level lever — including proposal 1, the largest
   one in the data. Structural (credentials + harness policy). Status: carried,
   re-evidenced on [#298](https://github.com/meridianlabs-ai/inspect_ai/issues/298).

3. **Stop rendering `traceback_ansi` eagerly (or stop syntax-highlighting it).**
   Unchanged: ~60s of worker time per `test` leg (~15s of leg wall, 5% of test
   execution) and 0.3–4s of CPU per distinct error for real users, spent in
   pygments lexing whole source files for `rich.traceback`. The two Google bridge
   tests still pay ~3.9s each and still sit 6th and 9th in the tail. Product
   change with a public field (`EvalError.traceback_ansi`) in play. Status:
   carried, [#374](https://github.com/meridianlabs-ai/inspect_ai/issues/374).

4. **Cache pytest's assertion-rewrite bytecode across runs.** Unchanged and
   re-confirmed at 51.0s of the 294.8s step (19%). Fix shape: restore
   `**/__pycache__` from `actions/cache` keyed on a hash of `src/**/*.py` +
   `tests/**/*.py`, and normalize source mtimes deterministically right after
   checkout in *both* the producing and consuming run, because pytest validates
   a rewritten pyc against source mtime + size. Est. ~30s off both `test` legs.
   Needs one CI experiment to confirm the restored cache validates. What does not
   work, both measured on 2026-08-29: `compileall` (writes the wrong cache
   entry) and `uv`'s `compile-bytecode` (+13.6s install for −3.5s collect).
   Structural (workflow change). Status: carried.

5. **`uv run` re-syncs the environment the previous step just installed.**
   Re-measured: **5.2s** per `test` leg, uninstalling 40 packages and
   reinstalling 42 before pytest starts, because `uv run` syncs the project
   environment while `Install dependencies` built it with `uv pip install`.
   `uv run --no-sync pytest` (or `.venv/bin/pytest`) removes it. ~9 runner-min
   per 200 runs. Workflow hygiene, same push blocker as 1 and 4 — fold into
   whichever workflow change lands first. Status: carried, low.

6. **Defer the `acp.schema` import.** Unchanged: 483ms of the 1.70s self-time of
   `import inspect_ai`, ~7x the next-largest module, reached through two eager
   edges. Paid by 5 interpreters per leg plus the four
   `_control/test_launch_handoff.py` tests that hold slots 4, 5, 7 and 12 of the
   tail. Product change with a public-API surface. Status: carried,
   [#311](https://github.com/meridianlabs-ai/inspect_ai/issues/311).

7. **Test-volume policy — it is the 0.1–1s band that matters.** Reconfirmed on a
   second window: 13,582 tests under 0.1s are 9% of test time; 1,211 tests
   between 0.1s and 1s are 50%. Growth slowed this window (+277 items, +92 test
   functions in two days). The question for a maintainer is not "how many tests"
   but "how many tests may call `eval()`", and whether the mid-band deserves a
   shared in-process fixture — and, as this window's fix shows, whether autouse
   fixtures that reset global caches are pricing themselves correctly.
   Structural. Status: carried.

8. **`tests/util/test_display_counter.py` sleeps 6 × 1.1s for 2 throttle paths.**
   NEW. 8.9s (3.10) / 10.5s (3.11) of worker time; the six `DisplayType` params
   resolve to only three display classes under pytest (no tty), and the two whose
   status print is `@throttle(5)` — `plain` and `log` — cannot be fired by a 1.1s
   sleep at all. Options: drop the sleep for the params that cannot use it; or
   make the throttle window injectable so the test can drive it to zero (product
   change). Est. ~7s of worker time, ~2s of leg wall. Not shipped: it is a
   coverage judgement on a deliberately-smoke test, which the skill's rules put
   in the report rather than in a PR. Status: **new**.

9. **Duplicate and near-duplicate test cleanups.** The strict AST sweep finds the
   same 11 groups as the last two reports; the real-sleep candidates are
   unchanged (`test_eval_set_previous_task_args` spends ~5s of its 6.3s sleeping
   around a `keyboard_interrupt(2)` that must land mid-eval;
   `test_sample_shuffle` / `test_sample_shuffle_limit` differ by `limit=20`).
   Combined value under 2s against a coverage risk on every item. Status:
   carried, low.

10. **Collector: validate the run window and refetch.** **Bit again today**, the
    fourth time in this series. Attempt 1 returned a 191h window with a 77h hole
    and a page-1 clump whose newest run was 2026-08-29 20:39, while a direct
    `gh api` call to the same endpoint moments later listed runs through
    2026-08-31 02:01; attempt 2 was clean and is the snapshot this report uses.
    Cost: one collection cycle per occurrence. The one-file fix — accumulate
    pages across attempts and treat "now" as the newest edge, so a stale *first*
    page is caught the same way a stale middle page is — is unchanged and still
    uncommittable (`.claude/**`, proposal 2). Status: carried, **blocked, and now
    the most frequently recurring operational cost of this skill**.

11. **Runner pool size for burst absorption.** Seventh consecutive window with no
    supporting evidence: median queue 3s, p90 8s, p95 20s, max 63s over 847
    independent-job records, one wait above 60s. Structural/cost. Status:
    carried, **recommend dropping** unless a burst window ever shows otherwise.

12. **Merge the 4 Viewer jobs into 1–2** — required-check rename. The Viewer
    workflow is 70s wall and 2.7 runner-min; nothing to win but job-count
    reduction. Structural. Status: carried, low.

13. **Policy consistency: docker tests without `@pytest.mark.slow`.** Still six,
    still ~0.05s combined; the right fix is probably to drop `skip_if_no_docker`
    from the three ungated ones rather than to mark them slow. Zero wall-clock
    impact. Status: carried.

Nothing dropped this report. The model-info fixture finding is not carried as a
proposal because it ships in this run's PR.

## PRs opened by this skill

See `prs.md`. This run's output — the snapshot, this report, the ledger update
and **one code fix** (the model-info cache reset) — ships on the branch of the
still-open previous PR
([meridianlabs-ai/inspect_ai#375](https://github.com/meridianlabs-ai/inspect_ai/pull/375)),
per the unattended rule that a run pushes onto an open predecessor rather than
opening a second PR. New evidence was posted to
[#317](https://github.com/meridianlabs-ai/inspect_ai/issues/317) and
[#298](https://github.com/meridianlabs-ai/inspect_ai/issues/298). No new issue
was filed: the one new finding (proposal 8) is a test-content judgement for a
maintainer, not a structural change ripe for its own issue.
