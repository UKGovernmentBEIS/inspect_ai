# CI performance report — 2026-08-25

Data: 200 PR runs, 2026-08-21 15:20 .. 2026-08-25 09:11 UTC (90h). Snapshot:
`history/2026-08-25.json`. Previous: 2026-08-23 (200 runs, 2026-08-21 01:31 ..
2026-08-22 16:35). **The windows overlap by 90 of 200 runs (45%)** — the two
weekend days produced only 59 runs between them, so 200 runs now reaches much
further back. Day-over-day medians are therefore heavily contaminated; wherever
a comparison matters below it is computed either on the fresh (post-2026-08-22
16:35) portion or by classifying each run on whether its head commit *contains*
the change in question, never on time. Produced by the unattended scheduled run
([workflow run](https://github.com/meridianlabs-ai/actions/actions/runs/32830966778)).

## Summary

**The Quarto render cache (#297) got its first real measurement and it hits ~8%
of the time.** 13 `docs` jobs ran the cache step this window (three more docs
jobs predate the fix); **one** was a hit — 12s against a 375s median. The
repo's own cache index confirms it: 12
`docs-render-*` entries exist, exactly one was ever re-used, and PR 4884 alone
created four distinct keys in 26 hours. The cause is structural — on
`pull_request` the checkout is the *merge* ref, so `hashFiles(… 'src/inspect_ai/**')`
hashes the PR merged into current `main`, and every push to `main` invalidates
every open PR's entry. In this window `main` touched `src/inspect_ai/**` in 8 of
10 commits and `docs/**` in 2. Filed with a fix as
[meridianlabs-ai/inspect_ai#317](https://github.com/meridianlabs-ai/inspect_ai/issues/317).

**One new regression, off the critical path:** the viewer's
`Run inspect-components tests` step went **39s → 55s median (+42%)**, split by
commit containment over 119 legs, since the `ts-mono` pointer bump in #4934. It
is not test count (+11 tests across that range) — the same range swaps the CSS
pipeline and rewrites the workspace tooling. Filed as
[#318](https://github.com/meridianlabs-ai/inspect_ai/issues/318). Costs ~16
runner-min per window and no wall clock (Viewer is 84s against Build's 363s).

**A slow creep worth watching on the `test` leg.** Grouped by merge base, the
pytest step rises monotonically across four days of `main`: ~297–308s for
2026-08-21 bases, 308–314s for 2026-08-23 bases; on the fresh portion of this
window the `test` leg is 342s against 332s in the previous one, and code-only
Build wall 361s against 342s. Suite growth explains only ~1s of it (+79
collected items in four days at ~60ms of worker time each, over four workers). No single
commit accounts for the rest.

**This run ships no code fix — the fifth in a row, same three blockers, all
re-probed.** One of them needed correcting: `.claude/**` is *not* unwritable in
the sandbox (a plain file write succeeds); it is the agent's own edit tooling
that refuses the path and would need interactive approval nobody can give in a
scheduled run. That makes the fix a harness permission-policy change rather than
a token or filesystem one — [#298](https://github.com/meridianlabs-ai/inspect_ai/issues/298)
updated. The collector's stale-page bug (proposal 4) fired again and cost the
run a full collection cycle.

## Queue vs execution

Median execution / queue over successful jobs. Queue for dependent jobs is
measured from predecessor completion (`needs` map read from the workflow files).
p90 is linear-interpolation, as in prior reports.

| Workflow | Job | n | exec med | exec p90 | queue med | queue p90 |
|---|---|---|---|---|---|---|
| Build | slow-tool-tests-dev | 6 | 794s | 864s | 2s | 20s |
| Build | slow-tool-tests-release | 1 | 744s | — | 2s | — |
| Build | docs (when docs change) | 15 | 375s | 396s | 3s | 4s |
| Build | test (per matrix leg) | 112 | 335s | 367s | 3s | 18s |
| Build | mypy (per matrix leg) | 119 | 86s | 94s | 3s | 19s |
| Validate Embedded Viewer | viewer-tests | 60 | 79s | 88s | 3s | 3s |
| Validate Embedded Viewer | check-schema-and-types | 59 | 57s | 65s | 3s | 4s |
| Validate Embedded Viewer | dist-validation | 61 | 34s | 40s | 3s | 4s |
| Build | pre-commit | 61 | 32s | 36s | 3s | 19s |
| Build | package | 61 | 28s | 34s | 3s | 19s |
| Build | ruff | 61 | 11s | 12s | 3s | 5s |
| Build | check-version-bump | 8 | 9s | 11s | 3s | 5s |
| Validate Embedded Viewer | submodule-on-main | 60 | 8s | 9s | 3s | 4s |
| Build | detect-slow | 61 | 8s | 10s | 3s | 19s |
| Build | changes | 61 | 7s | 9s | 3s | 11s |
| Changelog Lint | entries-under-unreleased | 44 | 6s | 8s | 3s | 3s |

`sandbox-tools-unit` has no median row because it did not succeed once: it
executed 4 times this window (all on 2026-08-21, 3 failures and 1 cancelled) and
was skipped in the other 57 runs.

Workflow wall clock over successful runs: Build **363s median / 445s p90** (was
357 / 794); Validate Embedded Viewer **84s / 93s** (was 71 / 90); Changelog Lint
10s / 12s (unchanged). Build's p90 collapsed only because just 3 sandbox-tools
runs landed this window against 7 last window — that chain is the entire p90
tail, not a change in behaviour.

By PR shape (successful Build runs; the fresh-portion figure is the honest
day-over-day one):

| PR shape | n | wall median | fresh-portion median (n) | prev window |
|---|---|---|---|---|
| code-only | 34 | 349s | 361s (17) | 342s |
| docs-touching | 15 | 390s | 394s (12) | 367s |
| sandbox-tools | 3 | 803s | — | 803s |

### Queue: a non-issue this window

820 independent-job samples: median 3s, p75 3s, **p90 5s, p95 25s, p99 36s, max
303s**. Restricted to the fresh portion (426 samples, no overlap with the last
report): **max 36s, nothing above 120s, 18 jobs above 30s.** The three 303s
outliers are the same GitHub runner-assignment stalls the last report dissected
(single job, all siblings starting in 2–4s) and they sit inside the overlap, so
they have now been counted twice — they are not new.

Hourly medians are 3s in every hour of the day; the 02:00 UTC burst that
dominated the 08-18/08-19 reports has not recurred in three windows.

### Critical path

Last-finishing job across the 52 successful Build runs:

| Last job | runs | median margin over the runner-up |
|---|---|---|
| `test` | 39 | 17s |
| `docs` | 10 | 49s |
| `slow-tool-tests-dev` | 3 | 470s |

- **Code-only PR (34 of 52):** `test` determines wall clock; the two legs finish
  within 17s of each other, so both legs are effectively the critical path.
- **Docs-touching PR (15 of 52):** `docs` finishes last in 10, a median **+49s**
  past the slower test leg — unchanged from the last two windows, and the
  premise behind #297/#317.
- **Sandbox-tools PR (3 of 52):** `detect-slow` → `check-version-bump` →
  `slow-tool-tests-dev` (794s). Now that `release` runs in parallel (#4987),
  `dev` alone owns this chain.

## Worker balance (`--dist worksteal`, #4948)

From the `test-report-log.jsonl` artifacts of the two most recent successful
Build runs (four legs, 13,449 items each):

| Run | Leg | worker busy times | max | avg | imbalance | efficiency | test-phase wall |
|---|---|---|---|---|---|---|---|
| 32830587177 | 3.10 | 208 / 203 / 202 / 193 | 208s | 202s | +6s (3%) | 97% | 212s |
| 32830587177 | 3.11 | 205 / 204 / 200 / 199 | 205s | 202s | +3s (1%) | 99% | 210s |
| 32776711297 | 3.10 | 205 / 204 / 201 / 199 | 205s | 202s | +2s (1%) | 99% | 213s |
| 32776711297 | 3.11 | 207 / 207 / 195 / 195 | 207s | 201s | +6s (3%) | 97% | 211s |

Still exactly as designed: +2..+6s imbalance at 97–99% efficiency, no
stragglers, four windows after the fix landed.

## Slowest tests

Median seconds across 24 CI test jobs, `call` + `setup` + `teardown` combined.
144 tests captured (`--durations-min=1`), **198.4s total per job** (mean of
per-job totals, the series prior reports published).

| Median | Test | Classification |
|---|---|---|
| 10.7s | `test_eval_set.py::test_retry_attempt_killed_mid_sweep_leaves_completed_samples_reusable` | genuinely heavy — two real harness subprocesses, one SIGKILLed |
| 10.0s | `test_eval_set_scanner.py::test_scout_scan_resume_reruns_failed_scans` | genuinely heavy (eval_set + scout scan resume) |
| 9.4s | `test_eval_set_selection.py::test_eval_set_selection_concurrent_workers` | three real `inspect_ai` subprocesses; documented in its docstring. Inherent |
| 9.3s | `_control/test_launch_handoff.py::test_eval_detach_via_dotenv_detaches_exactly_once` | real CLI subprocess + control-server handshake |
| 8.9s | `_control/test_launch_handoff.py::test_eval_detach_hands_off_and_leaves_eval_running` | real CLI subprocess |
| 6.9s | `test_eval_set_scanner.py::test_scanner_resume_…[s3]` | moto S3 + full eval-set resume |
| 6.7s | `agent/test_agent_bridge.py::test_google_bridge_computer_use_incompatible_model` | full `eval()`; cost is bridge/SDK import + eval startup |
| 6.5s | `_control/test_launch_handoff.py::test_eval_json_redirects_subprocess_stdout_to_stderr` | real CLI subprocess (documented: needs real fds) |
| 6.4s | `log/test_eval_log_config.py::test_eval_log_run_config_round_trip` | round-trips a full run config through eval |
| 6.3s | `agent/test_agent_bridge.py::test_google_bridge_streaming_not_supported` | (as above) |
| 6.1s | `test_eval_set.py::test_eval_set_previous_task_args` | **real sleeps**: ~5s is `sleep_for_3_task` plus a `keyboard_interrupt(2)` timer that must land mid-eval |
| 5.8s | `_control/test_launch_handoff.py::test_eval_detach_fails_when_control_bind_fails` | real CLI subprocess |
| 4.3s | `_control/test_pause.py::test_eval_hard_pause_time_limit_reap_reparks_grader` | real timers inherent to pause/limit semantics |
| 4.2s | `test_sample_limits.py::test_working_limit` | real waits inherent to limit tests |
| 4.1s | `test_sample_shuffle.py::test_sample_shuffle` | two full evals; overlaps `test_sample_shuffle_limit` (proposal 8) |

The list is the same cast as the last two reports, in the same order, and the
subprocess-spawning cluster still owns most of it — which is what makes the
`import inspect_ai` cost ([#311](https://github.com/meridianlabs-ai/inspect_ai/issues/311))
a test-suite problem. Re-measured today, unchanged: `import inspect_ai` 1.9–2.0s
wall, 1.70s of import self-time over 1,491 modules, of which **`acp.schema` is
483ms** — nearly 7x the next-largest module (`inspect_ai.log._log`, 71ms).

### The tail did not move

Amortized tail total per job 195.3s → 199.4s (+4.1s in two days), decomposed:
102 shared tests **+3.8s**, 42 tests newly crossing 1s **+5.3s**, 35 leaving
**−5.0s**. The largest single shared mover is +1.0s
(`test_task_retry_accumulates_across_attempts`, 2.1 → 3.1s), inside the
run-to-run noise these subprocess tests show. No per-test regression.

### Docker-trap sweep

An AST sweep of every `tests/**` test function decorated with
`skip_if_no_docker` but not `@pytest.mark.slow` finds **6**, unchanged from the
last two runs: `util/sandbox/test_docker_compose_config.py` ×3 (ungated, 0.05s
combined against a live daemon — they never start a container),
`tools/test_think_tool.py` ×2 and `agent/test_agent_docs.py::test_agent_collect`
(gated by `skip_if_no_anthropic` / `skip_if_no_openai`, ~1ms each). No new
offenders; no wall-clock cost either way.

## Suite size

Per matrix leg (pytest summary line, 24 CI jobs): **13,449 tests collected —
9,605 passed, 3,844 skipped** (medians), in **305s median pytest wall**.

| Snapshot | legs | pytest wall (median) | collected | ≥1s tail (mean/job) |
|---|---|---|---|---|
| 2026-08-19 (2 workers) | 20 | 393s | 13,247 | 160s |
| 2026-08-21 (4w worksteal) | 18 | 291s | 13,370 | 177s |
| 2026-08-23 (4w worksteal) | 20 | 299s | 13,410 | 195s |
| 2026-08-25 (4w worksteal) | 24 | **305s** | **13,449** | **198s** |

(The tail column is the mean of per-job tail totals, re-derived here for every
snapshot with one metric. The 2026-08-19 row reads 160s rather than the 149s the
2026-08-23 report printed — that row carried the 2026-08-18 snapshot's value.)

From the four report-log artifacts:

- **Test-phase work 804–809s per leg**, of which call 757–764s, setup 27–31s,
  teardown 14–19s. (Previous window: 697–813s across three legs — overlapping
  ranges, so this is consistent with the creep but does not by itself prove it.)
- **Tail vs body:** 12–14 tests ≥5s = 96–106s (12–13%); 143–159 tests ≥1s =
  331–368s (41–46%); the remaining **~13,300 tests = 436–475s (54–59%)**.
- **Heaviest files:** `test_eval_set.py` 58–61s, `test_eval_set_scanner.py`
  59–60s, `_control/test_launch_handoff.py` 46–48s, `test_sample_limits.py`
  32–34s, `_control/test_eval_set_integration.py` 30–50s,
  `_view/test_view_server.py` 23–25s, `agent/deepagent/test_deepagent_background.py`
  18–20s.
- **Collection and startup is ~98s of the 310s pytest step** (310s median step
  against 210–213s test-phase wall), i.e. **32%**, paid once on the controller
  and once per worker. Unchanged for three windows; see proposal 4.

### Growth

Top-level test functions at `origin/main`, at the last commit before 12:00 UTC
on each date (`^(async )?def test_` under `tests/`):

| Date | test functions | Δ |
|---|---|---|
| 2026-08-12 | 7,423 | — |
| 2026-08-18 | 7,716 | +293 (6d) |
| 2026-08-19 | 7,723 | +7 |
| 2026-08-21 | 7,786 | +63 (2d) |
| 2026-08-23 | 7,843 | +57 (2d) |
| 2026-08-25 | 7,862 | +19 (2d) |

~+146 test functions/week over the last seven days (against ~+215/week a week
ago — the weekend is in this sample), and +79 collected items in four days.
Priced at this window's mean cost per test (~60ms of worker time), four days of
growth is ~5s of worker time, ~1s of leg wall. **Suite growth is not what is
moving the `test` leg** — see the creep in the Summary, which is 4–10x larger
than growth can explain and currently unattributed.

### Duplicate-coverage and low-value sampling

Nothing new eligible as a mechanical fix. Re-read this run:
`test_sample_shuffle` (4.1s) and `test_sample_shuffle_limit` assert the same
seeded-order property with and without `limit=20`; they are near-duplicates, not
exact ones — `limit` interacts with shuffling, so collapsing them deletes
coverage rather than merging it, which makes it a maintainer call (proposal 8).
The `test_launch_handoff.py` cluster (6 tests, 47s) each spawns the real CLI and
the cost is inherent to what it asserts. The 42 tests that newly crossed 1s this
window are spread across 20 files with no cluster worth a proposal.

## Regressions since last report

- **Viewer `Run inspect-components tests` 39s → 55s median (+42%)** — the one
  real regression. 75 legs on branches containing the #4934 `ts-mono` pointer
  bump against 44 without; `viewer-tests` job exec 66 → 79s, Viewer wall 71 →
  84s. Not test count (+11 tests across the submodule range). Off the critical
  path; ~16 runner-min per window. Filed as
  [#318](https://github.com/meridianlabs-ai/inspect_ai/issues/318).
- **`test` leg creep, unattributed.** Fresh-portion `test` exec 332 → 342s,
  pytest step 305 → 310s, code-only Build wall 342 → 361s. By merge base the
  rise is monotone across four days rather than a step, so it is not one
  commit. Growth accounts for ~1s. Watch; if it continues at this rate it
  cancels `worksteal`'s 43s in about six weeks.
- **11 `entries-under-unreleased` (Changelog Lint) failures** across 11 distinct
  branches — the most-failed check in the window, ahead of any test job. Cheap
  (6–11s) and self-inflicted by contributors placing CHANGELOG entries under a
  released heading, but it is the single most common red check a contributor
  sees.
- Everything else is within noise of the previous window: `mypy` 87 → 86s,
  `pre-commit` 32s, `package` 29 → 28s, `check-schema-and-types` 54 → 57s.
- `action_required` runs 20 → 23 of 200. Still ~1 in 9 runs starting behind a
  human approval gate.

## Waste

- **Cancelled jobs: 48.8 runner-min** across 6 cancelled runs (was 90.6 min /
  7 runs) — `test` 31.7, `docs` 5.3, `mypy` 4.4. Lower because fewer pushes were
  superseded mid-flight, not because anything changed.
- **Failed jobs: 27.6 runner-min** (was 56.1), led by `sandbox-tools-unit` 13.9
  and `slow-tool-tests-dev` 9.8. All three `sandbox-tools-unit` failures are the
  same signature — `RuntimeError: MCP server stdout reader is no longer running`
  from an `assert isinstance(response, JSONRPCResponse)`, i.e. the injectable's
  `mcp<2` pin meeting the root venv's mcp 2.0 after #4992, which is exactly
  [#308](https://github.com/meridianlabs-ai/inspect_ai/issues/308) (fix in
  flight as [#310](https://github.com/meridianlabs-ai/inspect_ai/pull/310)).
  **No `test` job failed at all this window** — the first in this report series
  where that is true (6, 4, 5, 4, then 0 test-leg failures per window).
- Compute: **1,305 runner-min** per 200 runs (Build 1,118; Validate Embedded
  Viewer 181; Changelog Lint 6), against 1,377 last window. The Viewer's share
  is up 158 → 181 min, which is the regression above.
- Run conclusions: 153 success, 23 `action_required`, 18 failure, 6 cancelled.
- `docs`: 314s Quarto render, cache hitting ~8% of the time
  ([#317](https://github.com/meridianlabs-ai/inspect_ai/issues/317)).
- `slow-tool-tests-release` shows one 744s execution, but it is run
  `32508865021` — the *same* execution the last report verified #4987 on,
  re-counted because it falls inside the 90-run overlap. No new execution
  landed; the job has now run successfully exactly once, ever.
- Six job records per PR remain overhead-dominated (`ruff` 11s for ~1.5s of
  linting, `changes` 7s, `detect-slow` 8s, `check-version-bump` 9s,
  `submodule-on-main` 8s). Irrelevant to wall clock, relevant to burst load.

## Impact verification (previous runs' changes)

**#297 (Quarto render cache) — shipped, works, hits ~8%.** Detail in the
Summary and [#317](https://github.com/meridianlabs-ai/inspect_ai/issues/317).
The prediction in the 2026-08-21 report was "~40s of wall clock on the ~40% of
successful runs where `docs` finishes last, plus ~290s on a docs-only PR", with
the hit rate left open. Measured hit rate: **1 of 13 docs jobs that ran the
cache step, 1 of 12 cache
entries ever re-used**. On the one hit the job took 12s instead of ~375s and the
run's Build wall was 347s against 390s for the same branch's neighbouring
pushes. So the mechanism delivers exactly what was predicted *per hit*; the hit
rate is the problem, and it is a fixable key-design problem rather than an
inherent one.

**#299 (`design/**` excluded from the `test` filter) — done, verified last
run**, and nothing this window contradicts it (no design-only push landed
upstream in the window; this report's own PR is the next observation).

**#4987 (`release` un-serialized from `dev`) — done, verified last run, nothing
new to add.** The one successful `release` execution in this snapshot is the
same run (`32508865021`) the last report measured, pulled in by the window
overlap; no fresh execution occurred.

**#4948 (`--dist worksteal`) — holding at four windows.** +2..+6s imbalance,
97–99% efficiency, zero stragglers in four legs.

## Proposals (ranked)

1. **Fix the docs render cache key so `main` churn stops invalidating it.**
   NEW, and the only execution-side item with a measured mechanism and a
   concrete fix. Key on `docs/**`, `requirements-doc.txt` and the PR's *own*
   source delta (`git diff $(git merge-base origin/main HEAD) HEAD --
   src/inspect_ai`) instead of the merged source tree; the job already checks
   out full history so the diff is free. Replaying this window's docs jobs
   against each run's head tree and PR source delta — an approximation, since
   the real key is computed on the merge tree — 3 of the 13 would have hit
   instead of 1 (~23%). Each hit is ~360s of job exec
   (~6 runner-min) and ~40s of Build wall on the two-thirds of docs-touching
   runs where `docs` finishes last. Structural (workflow change this run cannot
   push). Status: **new, filed as
   [#317](https://github.com/meridianlabs-ai/inspect_ai/issues/317)**.

2. **Unblock the scheduled run.** Three blockers, all re-probed today:
   - *No `workflow` scope* — pushing a branch with a `.github/workflows/build.yml`
     edit to the fork is rejected (`refusing to allow a Personal Access Token to
     create or update workflow … without workflow scope`). The push is rejected,
     so no probe branch survives.
   - *No write on upstream* — `POST /repos/UKGovernmentBEIS/inspect_ai/pulls`
     with `head_repo` set as AGENTS.md prescribes returns
     `403 Resource not accessible by personal access token`.
   - *`.claude/**` — corrected this run.* The path is **writable in the
     sandbox**; what refuses is the agent's own edit tooling, which treats
     `.claude/**` as protected and asks for an approval no scheduled run can
     give. The fix is a harness permission-policy change (allowlist
     `.claude/skills/ci-perf/**` for this run), not a token or filesystem one.
     Writing the file from a subprocess would defeat the policy, so this run did
     not.

   Consequence: proposals 1 and 4 are unshippable by this skill, and it has now
   shipped zero code for five consecutive runs. Structural (credentials +
   harness policy). Status: carried, re-evidenced on
   [#298](https://github.com/meridianlabs-ai/inspect_ai/issues/298).

3. **Defer the `acp.schema` import.** Re-measured today, unchanged: 483ms of the
   1.70s import self-time of `import inspect_ai`, ~7x the next-largest module,
   reached through two eager edges (`_eval.eval` → `agent._acp.server`, and
   `util._input.{_types,request}` → `ElicitationSchema` for annotations only).
   ~0.5s per CLI invocation for users; in CI it is paid by 5 interpreters per
   leg plus the subprocess-spawning tests that own most of the slow tail
   (estimated ~4–6s of leg wall, not directly measured). Product change with a
   public-API surface — outside this skill's safe-fix categories. Status:
   carried, [#311](https://github.com/meridianlabs-ai/inspect_ai/issues/311)
   open.

4. **Collector: validate the run window and refetch.** **Bit again this run.**
   The first two page-fetch attempts returned a window whose newest run was 44h
   stale (85h hole); the third attempt, after merging pages across retries,
   produced the clean window this report uses. The one-file fix — accumulate
   pages across attempts and treat "now" as the newest edge of the window, so a
   stale first page is caught the same way a stale middle page is — is written
   and was exercised end to end from `/tmp`, but cannot be committed (proposal
   2). One refinement learned today: the existing >12h gap heuristic **cannot
   distinguish a stale page from a weekend**; this window contains a genuine
   19.5h Saturday-to-Sunday lull. Head freshness is the reliable signal, mid-window
   holes are not. Status: carried, **blocked, cost paid twice now**.

5. **Collection and startup is ~98s of the 310s pytest step.** Unchanged for
   three windows, ~32% of the step, paid once per process across the controller
   and four workers. The two quantified levers stand: suppressing trio variants
   at collection time (2,670 of 13,324 local items skip unless `--runtrio`;
   36.7s → 31.8s cold collection locally, ~10s of leg wall) and dropping
   `--doctest-modules` (~1.1s per pass, ~2s of leg wall, collects nothing).
   Neither is an unattended safe fix: the first changes what the suite collects
   and what test IDs exist, the second trades a dormant capability for under 1%.
   Proposal 3 attacks the same 98s from the import side. Status: carried.

6. **Find the `test`-leg creep.** NEW. +10s of `test` exec and +19s of code-only
   Build wall over two days, monotone by merge base rather than a step, with
   suite growth accounting for ~1s. Not yet actionable — the next snapshot
   decides whether it is a trend or a fortnight of noise, which is exactly why
   it is a proposal and not an issue. If it holds, the next step is a
   per-file diff of report-log totals between two known-good runs a week apart.
   Status: **new, watch**.

7. **Test-volume policy.** The body of ordinary tests is 54–59% of test time and
   the suite adds ~150–215 test functions/week. Direct pricing still puts that
   at ~1s of leg wall per week, so this remains a question about what the PR
   gate should cost rather than an arithmetic emergency. Structural. Status:
   carried.

8. **Real-sleep and near-duplicate test cleanups.** Re-read again this run and
   still not mechanical: `test_eval_set_previous_task_args` spends ~5s of its
   6.1s sleeping, but the `keyboard_interrupt(2)` must land mid-eval, so
   shrinking it trades wall clock for flakiness;
   `test_eval_detach_sigterm_terminates_child` holds a documented 1.0s grace
   sleep; merging `test_sample_shuffle`/`test_sample_shuffle_limit` (~2.4s)
   deletes the unlimited-dataset case rather than merging it. Combined ~7s of
   worker time, under 2s of wall clock at 97–99% efficiency. Status: carried,
   low.

9. **Runner pool size for burst absorption.** Fourth consecutive window with no
   fresh evidence: on the uncontaminated portion the worst wait of 426
   independent job starts was 36s. The structural argument (~20 job records per
   PR, so 20 simultaneous PRs is ~400 queued jobs) is unchanged and the case
   still rests on the 2026-08-18/19 02:00 UTC bursts. Structural/cost. Status:
   carried, **evidence continues to age**.

10. **Viewer component-test regression (#318).** Filed rather than proposed: the
    fix lives in `meridianlabs-ai/ts-mono`, and at 84s median the Viewer path is
    nowhere near wall clock. Tracked here so it does not silently double.
    Status: **new, filed**.

11. **Merge the 4 Viewer jobs into 1–2** — required-check rename. Worth
    revisiting only as burst-load reduction (proposal 9), not wall clock.
    Structural. Status: carried, low.

12. **Policy consistency: docker tests without `@pytest.mark.slow`.** Still six,
    still 0.05s combined for the three ungated ones because they never start a
    container; the right fix is probably to drop `skip_if_no_docker` from those
    three rather than to mark them slow. Zero wall-clock impact either way.
    Status: carried.

Dropped from this report: `design/**` exclusion (#299) and `release`
un-serialization (#4987), both done and verified.

## PRs opened by this skill

See `prs.md`. This run's output (snapshot, report, ledger) is pushed onto the
still-open fork PR
[meridianlabs-ai/inspect_ai#312](https://github.com/meridianlabs-ai/inspect_ai/pull/312)
rather than opening a second PR, per the skill's unattended rules; upstream PR
creation remains blocked (proposal 2). No code fix was shipped. Two new
structural findings were filed as issues
[#317](https://github.com/meridianlabs-ai/inspect_ai/issues/317) and
[#318](https://github.com/meridianlabs-ai/inspect_ai/issues/318), and
[#298](https://github.com/meridianlabs-ai/inspect_ai/issues/298) was updated
with today's probes.
