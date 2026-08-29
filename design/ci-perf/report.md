# CI performance report — 2026-08-27

Data: 200 PR runs, 2026-08-26 14:44 .. 2026-08-27 10:51 UTC (**20.1h**). Snapshot:
`history/2026-08-27.json`. Previous: 2026-08-25 (200 runs over 90h). The windows
do **not** overlap this time — the repo merged 30 commits to `main` in those 20
hours, so 200 runs now covers less than a day and every day-over-day comparison
below is clean. The flip side is that this window is a burst, not a typical day:
10 runs/hour against 2.2 last window. Produced by the unattended scheduled run
([workflow run](https://github.com/meridianlabs-ai/actions/actions/runs/33070349336)).

## Summary

**A new and large finding: `-rA` costs ~46s of every `test` leg — 14% of the
pytest step — printing captured stdout for tests that passed.** Measured
directly from the GitHub job logs of 16 test legs: the `==== PASSES ====`
section runs 32.6–87.7s (median **46.2s**) and emits ~31,000 lines each time.
That is a one-flag change (`-rA` → `-ra`, "all except passed") with the failure
and skip reporting fully preserved. Filed as
[meridianlabs-ai/inspect_ai#342](https://github.com/meridianlabs-ai/inspect_ai/issues/342).
It is the biggest single lever this report series has found since `-n logical`,
and it is a safe-fix category the scheduled run still cannot push (proposal 2).

**The `test`-leg creep resolves to suite growth, not a regression.** Last report
flagged +10s of unattributed creep and asked for a second window. This window
gives it: `test` exec 335 → 356s, pytest step 310 → 324s, and the suite grew
**13,449 → 14,123 collected items in two days (+674, +5%)** — the largest
two-day jump in this series. Diffing report-log artifacts across the two
windows, the 877 new test IDs account for +27–34s of worker time (≈ +7–9s of leg
wall), and the residual sits inside a **±60s of worker time (±8%) run-to-run
noise band** that this report quantifies for the first time from seven
same-run 3.10/3.11 pairs. Proposal 6 closes.

**The viewer regression (#318) is gone, and the fix is identifiable.**
`Run inspect-components tests` went **54s → 40s median** and Viewer wall **90s →
71s**, a step change at 2026-08-26 20:44:58Z — exactly the `ts-mono` pointer bump
(`125db36a5` → `f2057d95f`) that rode in with #4629. Pre/post split: n=32 median
54s vs n=29 median 40s, no overlap in the branch mix.

**This run ships no code fix — the sixth in a row, same three blockers, all
re-probed today** (a real push probe for `workflow` scope, a real write attempt
for `.claude/**`, and upstream PR creation). The collector's stale-page bug
(proposal 4) fired twice, costing two full collection cycles.

## Queue vs execution

Median execution / queue over successful jobs. Queue for dependent jobs is
measured from predecessor completion (`needs` map read from the workflow files:
`docs`/`sandbox-tools-unit` ← `changes`; `check-version-bump`/`slow-tests` ←
`detect-slow`; `slow-tool-tests-{dev,release}` ← `detect-slow` +
`check-version-bump`). p90 is linear-interpolation, as in prior reports.

| Workflow | Job | n | exec med | exec p90 | queue med | queue p90 |
|---|---|---|---|---|---|---|
| Build | slow-tool-tests-dev | 5 | 895s | 947s | 3s | 3s |
| Build | docs (when docs change) | 19 | 384s | 408s | 2s | 3s |
| Build | test (per matrix leg) | 108 | 356s | 394s | 3s | 26s |
| Build | sandbox-tools-unit | 3 | 260s | 270s | 2s | 3s |
| Build | slow-tests (checkpoint) | 11 | 223s | 236s | 3s | 4s |
| Build | mypy (per matrix leg) | 113 | 87s | 97s | 3s | 24s |
| Validate Embedded Viewer | viewer-tests | 61 | 75s | 91s | 3s | 11s |
| Validate Embedded Viewer | check-schema-and-types | 58 | 58s | 66s | 3s | 6s |
| Validate Embedded Viewer | dist-validation | 62 | 37s | 45s | 3s | 10s |
| Build | pre-commit | 61 | 34s | 39s | 3s | 19s |
| Build | package | 61 | 31s | 35s | 3s | 21s |
| Build | ruff | 61 | 11s | 18s | 3s | 13s |
| Build | check-version-bump | 6 | 10s | 11s | 2s | 3s |
| Validate Embedded Viewer | submodule-on-main | 53 | 9s | 11s | 3s | 6s |
| Build | detect-slow | 61 | 9s | 12s | 3s | 26s |
| Build | changes | 62 | 8s | 14s | 3s | 21s |
| Changelog Lint | entries-under-unreleased | 55 | 7s | 9s | 3s | 4s |

Workflow wall clock over successful runs: Build **390s median / 436s p90** (was
363 / 445); Validate Embedded Viewer **80s / 96s** (was 84 / 93 — and see the
pre/post split below, the median hides a step change); Changelog Lint 11s / 13s.

By PR shape (successful Build runs):

| PR shape | n | wall median | prev window |
|---|---|---|---|
| code-only | 26 | 368s | 349s |
| docs-touching | 18 | 401s | 390s |
| docs/design-only (test legs no-op) | 3 | 122s | 398s* |
| sandbox-tools | 2 | 813s | 803s |

\* last window's "docs-only" row was two runs that still ran full test legs; this
window's three are genuine no-ops under the #299 `design/**` exclusion.

### Queue: still absorbed, but the burst is visible

867 independent-job samples: median 3s, p75 4s, **p90 17s, p95 33s, p99 73s, max
306s**; 46 jobs above 30s, 2 above 120s. p90 is up from 5s, which is what a
4.5x denser window looks like. Per hour:

| Hour (UTC) | runs | job samples | queue med | queue p90 | max |
|---|---|---|---|---|---|
| 08-26 19 | 23 | 111 | 3s | 5s | 22s |
| 08-26 20 | 29 | 139 | 3s | 4s | 20s |
| **08-26 21** | **50** | **237** | **3s** | **35s** | **306s** |
| 08-26 17 | 15 | 70 | 3s | 56s | 71s |
| everything else | ≤14 | — | 2–13s | 3–33s | ≤34s |

The busiest hour of this series — 50 runs, ~1,000 job records — still held a **3s
median**. Both >120s outliers are the runner-assignment stall the 2026-08-23
report dissected, not saturation: in run `33016504371` `test (3.10)` waited 306s
while all eight sibling jobs started in 3s, and in `33026148725` `detect-slow`
waited 303s with the same eight-siblings-at-3s pattern.

### Critical path

Last-finishing job across the 49 successful Build runs:

| Last job | runs | median margin over the runner-up |
|---|---|---|
| `test` | 33 | 11s |
| `docs` | 12 | 27s |
| `slow-tool-tests-dev` | 2 | 400s |
| `mypy` | 2 | 12s |

`docs` finishes last in **12 of the 18 docs-touching runs** — unchanged premise
behind #297/#317.

## Where the pytest step actually goes

New this run, and the reason for proposal 1. Measured from the raw GitHub job
logs of 16 test legs (the 8 most recent Build runs, both matrix legs), by
timestamp between pytest's own section markers:

| Phase | median | range | share |
|---|---|---|---|
| `uv run` project re-sync (uninstall 27–28 / install 28–29 pkgs) | 4.3s | 3.3–5.4s | 1% |
| interpreter start + plugin load + collection (controller + 4 workers) | 50.0s | 47.4–57.3s | 15% |
| test execution | 236.1s | 220.8–264.1s | 70% |
| **`==== PASSES ====` section (`-rA`)** | **46.2s** | **32.6–87.7s** | **14%** |
| durations block + short summary + report-log flush | 0.6s | 0.5–0.9s | <1% |
| **step total** | **336.3s** | 310.8–415.2s | |

The `PASSES` section is ~31,000 lines per leg: with `-rA`, pytest prints a
`Captured stdout call` / `Captured log call` block for every passed test that
produced output, and these tests print full Inspect task dashboards. The cost is
the runner's log ingestion at ~1.5ms/line, reproduced locally at ~1.2ms/line
(`tests/test_fail_on_error.py` + `tests/test_retry.py`, 26 tests: 1,626 lines of
output under `-rA` against **15** under `-ra`, with the skip reason and the
`short test summary info` section identical).

The remaining 50s of startup+collection is consistent with a local measurement:
`pytest --collect-only` over the same 14,300 items takes **35.9s cold** and
**11.2s warm** (the difference is `__pycache__` bytecode compilation), and
`--doctest-modules` accounts for ~1.4s of it.

## Worker balance (`--dist worksteal`, #4948)

From `test-report-log.jsonl` artifacts of six Build runs (12 legs):

| imbalance | worker efficiency | test-phase wall |
|---|---|---|
| +3s .. +9s | 96–99% | 207–238s |

Five windows after the fix landed, still exactly as designed, with no
stragglers in any of the 12 legs.

## Slowest tests

Median seconds across 20 CI test jobs, `call` + `setup` + `teardown` combined.
165 tests captured (`--durations=50 --durations-min=1`), **207.0s total per job**
(mean of per-job totals, the series prior reports published; 198.4s last window).

| Median | Test | Classification |
|---|---|---|
| 10.7s | `test_eval_set_selection.py::test_eval_set_selection_concurrent_workers` | three real `inspect_ai` subprocesses; documented in its docstring. Inherent |
| 10.4s | `test_eval_set.py::test_retry_attempt_killed_mid_sweep_leaves_completed_samples_reusable` | genuinely heavy — two real harness subprocesses, one SIGKILLed |
| 9.8s | `test_eval_set_scanner.py::test_scout_scan_resume_reruns_failed_scans` | genuinely heavy (eval_set + scout scan resume) |
| 9.5s | `_control/test_launch_handoff.py::test_eval_detach_hands_off_and_leaves_eval_running` | real CLI subprocess |
| 9.3s | `_control/test_launch_handoff.py::test_eval_detach_via_dotenv_detaches_exactly_once` | real CLI subprocess + control-server handshake |
| 8.2s | `test_eval_set_scanner.py::test_scanner_resume_…[s3]` | moto S3 + full eval-set resume |
| 7.0s | `agent/test_agent_bridge.py::test_google_bridge_computer_use_incompatible_model` | full `eval()`; cost is bridge/SDK import + eval startup |
| 7.0s | `_control/test_launch_handoff.py::test_eval_json_redirects_subprocess_stdout_to_stderr` | real CLI subprocess (documented: needs real fds) |
| 6.7s | `agent/test_agent_bridge.py::test_google_bridge_streaming_not_supported` | (as above) |
| 6.2s | `test_eval_set.py::test_eval_set_previous_task_args` | **real sleeps**: ~5s is `sleep_for_3_task` plus a `keyboard_interrupt(2)` timer that must land mid-eval |
| 6.0s | `log/test_eval_log_config.py::test_eval_log_run_config_round_trip` | round-trips a full run config through eval |
| 5.5s | `_control/test_launch_handoff.py::test_eval_detach_fails_when_control_bind_fails` | real CLI subprocess |
| 4.3s | `_control/test_pause.py::test_eval_hard_pause_time_limit_reap_reparks_grader` | real timers inherent to pause/limit semantics |
| 4.3s | `test_sample_limits.py::test_working_limit` | real waits inherent to limit tests |
| 4.2s | `test_sample_shuffle.py::test_sample_shuffle` | two full evals; overlaps `test_sample_shuffle_limit` (proposal 8) |

Same cast, same order as the last two reports; the subprocess-spawning cluster
still owns most of it, which is what keeps the `import inspect_ai` cost
([#311](https://github.com/meridianlabs-ai/inspect_ai/issues/311)) a test-suite
problem and not only a CLI one.

### No per-test regression

Comparing mean per-test durations across two 2026-08-25 legs and six 2026-08-27
legs, the movers are symmetric and concentrated in the moto/subprocess cluster:
largest increase +2.4s (`test_scanner_resume_…[s3]`, 6.5 → 9.0s), largest
decrease −2.0s (`test_enqueue_task_does_not_leak_active_model`, 3.2 → 1.2s), with
20 tests above +0.5s and 10 below −0.5s. Nothing here is a regression; it is the
noise band quantified below.

### Docker-trap sweep

An AST sweep of every `tests/**` test function decorated with
`skip_if_no_docker` but not `@pytest.mark.slow` finds **6**, unchanged for three
runs: `util/sandbox/test_docker_compose_config.py` ×3 (ungated, 0.05s combined
against a live daemon — they never start a container), `tools/test_think_tool.py`
×2 and `agent/test_agent_docs.py::test_agent_collect` (gated by
`skip_if_no_anthropic` / `skip_if_no_openai`). No new offenders. The 352 new
sandbox self-check tests (#4265) are correctly marked — all 352 skip in the PR
gate, for **0.56s** of combined worker time.

## Suite size

Per matrix leg (pytest summary line, 20 CI jobs): the window straddles #4265, so
report both ends — **13,872–13,949 collected before it, 14,297–14,315 after**,
in **328.7s median pytest wall**.

| Snapshot | legs | pytest wall (median) | collected | ≥1s tail (mean/job) |
|---|---|---|---|---|
| 2026-08-19 (2 workers) | 20 | 393s | 13,247 | 160s |
| 2026-08-21 (4w worksteal) | 18 | 291s | 13,370 | 177s |
| 2026-08-23 (4w worksteal) | 20 | 299s | 13,410 | 195s |
| 2026-08-25 (4w worksteal) | 24 | 305s | 13,449 | 198s |
| 2026-08-27 (4w worksteal) | 20 | **329s** | **14,123** | **207s** |

**+674 collected items in two days is the largest jump in this series**, and 352
of them are one commit: #4265 turned the sandbox `self_check` into a portable
pytest suite (`tests/tools/test_sandbox_docker_and_local.py`, 8 → 352 items).
They are all skipped in the PR gate and cost **0.56s of worker time between
them** — a useful data point on its own: a skipped test costs ~1.4–1.9ms at
runtime, so skipped-test growth is nearly free in execution and shows up only in
collection.

From the six report-log artifact pairs:

- **Test-phase work 799–903s per leg**, of which call 790–863s, setup 25–31s,
  teardown 15–19s.
- **Tail vs body:** 13–15 tests ≥5s = 103–122s (12–14%); 149–180 tests ≥1s =
  344–429s (41–48%); the remaining **~14,150 tests = 467–496s (52–59%)** at a
  **33–35ms mean**.
- **Heaviest files:** `test_eval_set.py` 61–79s, `test_eval_set_scanner.py`
  64–71s, `_control/test_eval_set_integration.py` 34–62s,
  `_control/test_launch_handoff.py` 46–50s, `test_sample_limits.py` 34–38s,
  `test_eval_set_selection.py` 20–26s, `_view/test_view_server.py` 17–21s.

### The noise floor, measured

Seven runs where both matrix legs produced a report log give seven paired
measurements of the same commit on two runners. Total test-phase worker time
differs between the legs by **+48, +63, −18, −55, +75, −5, +2 seconds** — i.e.
**±60s (±8%) of worker time, ±15s of leg wall, with no systematic 3.10/3.11
bias**. Any single-window "creep" smaller than that is not evidence of anything.
This is the number the last two reports were missing.

### Growth

Top-level test functions at `origin/main`, at the last commit before 12:00 UTC
on each date (`^(async )?def test_` under `tests/`, re-derived here for every
date with one metric — the 2026-08-25 row reads 7,883 rather than the 7,862 the
last report printed):

| Date | test functions | Δ |
|---|---|---|
| 2026-08-12 | 7,423 | — |
| 2026-08-18 | 7,716 | +293 (6d) |
| 2026-08-21 | 7,786 | +70 (3d) |
| 2026-08-23 | 7,843 | +57 (2d) |
| 2026-08-25 | 7,883 | +40 (2d) |
| 2026-08-26 | 7,900 | +17 |
| 2026-08-27 | **8,192** | **+292 (1d)** |

The +292 in a single day is not one commit — 30 commits landed in that window and
the increase is spread across ~20 of them (largest single step +41). At ~+200
test functions/week and this window's ~34ms mean cost per body test, growth is
now worth roughly **+7–9s of leg wall per two-day window**, which is the first
time in this series that growth is large enough to see above the ±15s noise
floor over a single window.

### Duplicate-coverage and low-value sampling

An AST sweep for byte-identical test bodies (normalising away names and
docstrings) finds **11 groups of exact duplicates**, all pairs:

- `model/test_message_ids.py::test_same_content_same_id` ≡ `::test_reuse_across_conversations`
- `model/test_stable_message_ids.py::test_stable_ids_same_content_same_id` ≡ `::test_stable_ids_reuse_across_conversations` (and the two files cover the same `stable_message_ids` subject)
- `model/test_canonical_names.py` ×2 pairs (`test_extract_model_name_single_part` ≡ `test_single_component`; `test_normalize_for_fuzzy_underscores` ≡ `test_underscore_to_hyphen`)
- plus 7 more in `hooks/test_hooks.py`, `tools/test_web_search.py`, `scorer/test_math.py`, `model/test_reasoning_effort.py`, `agent/test_acp/test_router_phase2.py`, `agent/test_acp/test_tui/test_state.py`

Every one is a sub-millisecond test, so the combined wall-clock value of deleting
all 11 is unmeasurable. Recorded as a finding, not shipped: AGENTS.md rule 7 asks
for a demonstrated problem, and "22 redundant assertions costing 0ms" is not one.
The one place it might matter is `test_message_ids.py` / `test_stable_message_ids.py`
being two files on one subject — a maintainer call (proposal 8).

## Regressions since last report

- **None on the critical path that survive the noise floor.** `test` exec 335 →
  356s and the pytest step 310 → 324s are accounted for by +674 collected items
  (+7–9s) plus a ±15s per-leg noise band; the shared-test totals across the two
  windows move +9s (3.10) and +48s (3.11), straddling zero.
- **Queue p90 5s → 17s** — density, not capacity: 10 runs/hour against 2.2, with
  the median flat at 3s in every hour including the 50-run 21:00 burst.
- **`submodule-on-main` is the new most-failed check: 10 failures**, but 9 of them
  are one branch (`claude/issue-143-…`) pushing a modified `ts-mono` gitlink
  repeatedly — precisely the trap AGENTS.md warns about. Cheap (8–23s), a
  contributor-side problem, not a CI one.
- **`entries-under-unreleased` failures 11 → 2** — the thing the last report
  called the most common red check a contributor sees has mostly gone away.
- **`sandbox-tools-unit` is green again**: 3 successful runs at 260s against 3
  failures and 0 successes last window. The `mcp<2` signature of
  [#308](https://github.com/meridianlabs-ai/inspect_ai/issues/308) does not appear
  in this window.
- Everything else within noise: `mypy` 86 → 87s, `pre-commit` 32 → 34s, `package`
  28 → 31s, `check-schema-and-types` 57 → 58s, `docs` 375 → 384s.
- `action_required` runs 23 → 18 of 200 (~1 in 11 runs starts behind a human
  approval gate).

## Waste

- **Cancelled jobs: 76.7 runner-min** across 10 cancelled runs (was 48.8 / 6) —
  `test` 52.5, `mypy` 7.3, `docs` 5.4, `slow-tests` 3.5. More supersession because
  more pushes, in a window with 4.5x the push density.
- **Failed jobs: 15.3 runner-min** (was 27.6), led by `test` 6.0 and
  `check-schema-and-types` 2.4. Exactly **one** `test`-leg failure in 200 runs.
- Compute: **1,386 runner-min** per 200 runs (Build 1,190; Validate Embedded
  Viewer 189; Changelog Lint 7), against 1,305 last window. Per unit time this is
  4.5x the last window's burn rate, which is what the merge burst costs.
- Run conclusions: 153 success, 19 failure, 18 `action_required`, 10 cancelled.
- `docs`: 317s Quarto render; **cache hit 2 of 19 (11%)**, both hits back-to-back
  pushes on the same branch minutes apart, exactly the pattern
  [#317](https://github.com/meridianlabs-ai/inspect_ai/issues/317) predicts. On a
  hit the job is 10–13s against a 384s median.
- **`-rA` is 46s × 108 test job records = ~83 runner-min per 200 runs**, 6% of
  the window's total compute, for output nobody reads (proposal 1).
- `uv run pytest` re-syncs the environment the previous step just built —
  "Uninstalled 27–28 packages / Installed 28–29 packages", 4.3s median per leg,
  ~8 runner-min per window. It does *not* undo the `tests/test_package`
  pre-install from #4760 (checked: `test_extensions` tests are all ≤0.3s), so this
  is pure overhead rather than a correctness problem.
- Six job records per PR remain overhead-dominated (`ruff` 11s, `changes` 8s,
  `detect-slow` 9s, `check-version-bump` 10s, `submodule-on-main` 9s). Irrelevant
  to wall clock, relevant to burst load.

## Impact verification (previous runs' changes)

**#318 (viewer component tests +42%) — resolved, and the fix located.** The last
report measured `Run inspect-components tests` at 39 → 55s since the #4934
`ts-mono` bump. This window it is back down: splitting the 61 legs at
2026-08-26 20:44:58Z (the `ts-mono` pointer bump `125db36a5` → `f2057d95f` that
rode in with #4629), **pre: n=32, median 54s; post: n=29, median 40s**, and Viewer
wall **90s → 71s**. The regression cost ~16 runner-min per window and it is gone;
the causal range for anyone who wants the actual commit is
`125db36a5..f2057d95f` in `meridianlabs-ai/ts-mono`.

**#297 (Quarto render cache) — second measurement, hit rate confirmed low.**
2 of 19 docs jobs hit (11%), against 1 of 13 (8%) last window. Both hits are the
same shape as last window's single hit: a second push to a branch that had
already rendered, with no intervening `main` push. Per-hit value is unchanged and
large (10–13s against 384s). The key-design fix is
[#317](https://github.com/meridianlabs-ai/inspect_ai/issues/317).

**#299 (`design/**` excluded from the `test` filter) — holding.** Three
docs/design-only Build runs this window came in at a 122s median wall against a
368s code-only median, with the test legs no-ops. This report's own PR
([#343](https://github.com/meridianlabs-ai/inspect_ai/pull/343)) is the fourth
observation and the cleanest: `test (3.10)` **6s**, `test (3.11)` **3s**, Build
wall **102s**, Viewer wall 78s, **7.2 runner-min** for the whole push. `mypy` at
87s/89s is now the entire long pole of a design-only push.

**#4948 (`--dist worksteal`) — holding at five windows.** +3..+9s imbalance,
96–99% efficiency, zero stragglers across 12 legs.

**#4935 (`-n logical`) and #4760 (`blob:none`, test_package pre-install) —
still holding.** Checkout steps are 5–8s median across every job; the
`test_package` pre-install survives `uv run`'s re-sync (all `test_extensions`
tests ≤0.3s, against the ~9s a mid-run install would cost).

## Proposals (ranked)

1. **Drop `-rA` from the pytest invocation.** NEW, and the largest measured
   lever in the current data. `-rA` makes pytest print a `Captured stdout call` /
   `Captured log call` block for every *passed* test that produced output —
   ~31,000 lines and **46.2s median (32.6–87.7s) per test leg, 14% of the pytest
   step**, measured across 16 legs from the job logs. `-ra` ("all except passed")
   keeps failures, errors, skips and xfails and drops only the passed-test dump;
   verified locally on a 26-test subset (1,626 lines → 15, identical skip
   reporting). Estimated impact: **~46s off Build wall clock on the 26 of 49
   code-only runs** (where `test` binds at 356s and the runner-up `mypy` is 87s),
   less on docs-touching runs (`docs` at 384s becomes the binding job), and **~83
   runner-min per 200 runs**. Two places carry the flag: the `Test with pytest`
   step in `.github/workflows/build.yml` and `addopts` in `pyproject.toml`. Safe-fix
   category (workflow hygiene) but unshippable by this run — the token cannot push
   `.github/workflows/**` (proposal 2). Status: **new, filed as
   [#342](https://github.com/meridianlabs-ai/inspect_ai/issues/342)**.

2. **Unblock the scheduled run.** Three blockers, all re-probed today with real
   attempts rather than inference:
   - *No `workflow` scope* — pushed a probe branch carrying a one-byte
     `.github/workflows/build.yml` edit to the fork; rejected with `refusing to
     allow a Personal Access Token to create or update workflow
     .github/workflows/build.yml without workflow scope`. Branch never landed.
   - *`.claude/**`* — attempted a plain file write under
     `.claude/skills/ci-perf/`; the agent's edit tooling refuses the path and asks
     for an approval no scheduled run can give. As corrected last run, this is a
     harness permission-policy fix, not a token one.
   - *No upstream write* — `POST /repos/UKGovernmentBEIS/inspect_ai/pulls` with
     `head_repo` set as AGENTS.md prescribes still returns
     `403 Resource not accessible by personal access token`, so this run's output
     is again a fork PR awaiting maintainer promotion.

   Consequence: **proposals 1, 4 and 5 are all unshippable by this skill, and it
   has now shipped zero code for six consecutive runs** — while proposal 1 alone
   is worth ~46s of PR wall clock. Structural (credentials + harness policy).
   Status: carried, re-evidenced on
   [#298](https://github.com/meridianlabs-ai/inspect_ai/issues/298).

3. **Fix the docs render cache key so `main` churn stops invalidating it.**
   Second window of measurement: 2 of 19 hits (11%), both back-to-back pushes on
   one branch. Unchanged proposal — key on `docs/**`, `requirements-doc.txt` and
   the PR's *own* source delta rather than the merged source tree. ~360s of job
   exec per hit and ~27s of Build wall on the two-thirds of docs-touching runs
   where `docs` finishes last. Structural (workflow change this run cannot push).
   Status: carried, [#317](https://github.com/meridianlabs-ai/inspect_ai/issues/317).

4. **Collector: validate the run window and refetch.** **Bit twice this run.**
   Attempts 1 and 2 both returned an identical bad window — a stale page 1 serving
   a 2026-08-17/18 clump ahead of a correct page 2, leaving a 204h hole in a 220h
   span — while a direct `gh api` call to the same endpoint between the attempts
   returned a perfectly contiguous page 1. Attempt 3 was clean and is the snapshot
   this report uses. The one-file fix (accumulate pages across attempts; treat
   "now" as the newest edge, so a stale *first* page is caught the same way a
   stale middle page is) is unchanged and still uncommittable (proposal 2). Cost so
   far: one wasted cycle on 2026-08-25, two today. Status: carried, **blocked**.

5. **Startup and collection is 50s of the 336s pytest step.** Sharpened this run
   with a direct measurement rather than an estimate: 15% of the step, paid across
   the controller and four workers. Locally the same 14,300 items collect in
   **35.9s cold vs 11.2s warm** — the gap is `__pycache__` bytecode compilation,
   which suggests a fourth lever (cache `__pycache__` across CI runs) alongside the
   two already quantified: suppressing trio variants at collection time (~10s of
   leg wall, but it changes test IDs) and dropping `--doctest-modules` (~1.4s per
   pass). None is an unattended safe fix, and the bytecode-cache idea needs a CI
   measurement of how much of the 50s is compilation before it is worth filing.
   Status: carried, **sharpened**.

6. **~~Find the `test`-leg creep.~~ Resolved: growth plus noise.** The second
   window this proposal asked for arrived and answered it. +674 collected items in
   two days explain +7–9s of leg wall; the ±60s-of-worker-time noise floor
   (measured from seven same-commit leg pairs) covers the rest. No unattributed
   creep remains. Status: **closed**.

7. **Test-volume policy.** The body of ordinary tests is 52–59% of test time at a
   33–35ms mean, and this window added 292 test functions in one day. Direct
   pricing puts two days of growth at +7–9s of leg wall — the first window where
   growth clears the noise floor on its own, which moves this from "arithmetic
   curiosity" toward a real question about what the PR gate should cost.
   Structural. Status: carried, **strengthened**.

8. **Duplicate and near-duplicate test cleanups.** The AST sweep above finds 11
   exact-duplicate pairs and one duplicated subject
   (`test_message_ids.py` / `test_stable_message_ids.py`); the real-sleep
   candidates are unchanged (`test_eval_set_previous_task_args` spends ~5s of its
   6.2s sleeping around a `keyboard_interrupt(2)` that must land mid-eval;
   `test_sample_shuffle`/`test_sample_shuffle_limit` differ by `limit=20`).
   Combined value is under 2s of wall clock, and every item is either
   coverage-sensitive or flakiness-sensitive. Status: carried, low.

9. **Defer the `acp.schema` import.** Unchanged: 483ms of the 1.70s import
   self-time of `import inspect_ai`, ~7x the next-largest module, reached through
   two eager edges. Paid by 5 interpreters per leg plus the subprocess-spawning
   tests that own most of the slow tail. Product change with a public-API surface —
   outside this skill's safe-fix categories. Status: carried,
   [#311](https://github.com/meridianlabs-ai/inspect_ai/issues/311).

10. **`uv run` re-syncs the environment the previous step just installed.**
    NEW, small. Every `test` leg spends 4.3s (median, 3.3–5.4s) uninstalling 27–28
    packages and reinstalling 28–29 before pytest starts, because `uv run` syncs
    the project environment while `Install dependencies` built it with `uv pip
    install`. `uv run --no-sync pytest` (or calling `.venv/bin/pytest`) removes it.
    ~8 runner-min per window, ~4s of wall clock. Workflow hygiene, same push
    blocker as proposal 1 — worth folding into that change rather than filing
    separately. Status: **new, low**.

11. **Runner pool size for burst absorption.** Fifth consecutive window with no
    supporting evidence, and this one is the strongest counter-evidence yet: the
    busiest hour in the series (50 runs, ~1,000 job records) held a 3s median and a
    35s p90, and both >120s waits are single-job runner-assignment stalls with
    every sibling starting in 3s. Structural/cost. Status: carried, **evidence now
    points the other way**.

12. **Merge the 4 Viewer jobs into 1–2** — required-check rename. Worth revisiting
    only as burst-load reduction (proposal 11), not wall clock, and the Viewer just
    got 19s cheaper on its own. Structural. Status: carried, low.

13. **Policy consistency: docker tests without `@pytest.mark.slow`.** Still six,
    still ~0.05s combined; the right fix is probably to drop `skip_if_no_docker`
    from the three ungated ones rather than to mark them slow. Zero wall-clock
    impact either way. Status: carried.

Dropped from this report: the `test`-leg creep (proposal 6, resolved) and the
viewer component-test regression (#318, resolved — see impact verification).

## PRs opened by this skill

See `prs.md`. This run's output (snapshot, report, ledger) is
[meridianlabs-ai/inspect_ai#343](https://github.com/meridianlabs-ai/inspect_ai/pull/343)
on the fork — upstream PR creation returned 403 again (proposal 2), so it needs
maintainer promotion as with #4935, #4948, #4995 and #5057. No code fix was
shipped. One new structural finding was filed as
[#342](https://github.com/meridianlabs-ai/inspect_ai/issues/342), evidence was
added to [#317](https://github.com/meridianlabs-ai/inspect_ai/issues/317), and
[#318](https://github.com/meridianlabs-ai/inspect_ai/issues/318) was closed out
with the resolving `ts-mono` range.
