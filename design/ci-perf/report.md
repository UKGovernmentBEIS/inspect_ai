# CI performance report — 2026-08-29

Data: 200 PR runs, 2026-08-27 23:30 .. 2026-08-29 07:55 UTC (**32.4h**, 6.2
runs/hour). Snapshot: `history/2026-08-29.json`. Previous: 2026-08-27 (200 runs
over 20.1h, ending 10:51 UTC). The two windows do not overlap — there is a
12.6h hole between them, and the three gaps >2h inside this window (8.1h from
00:53 UTC, then 2.8h and 2.4h) are overnight quiet periods, not collector
staleness. Produced by the unattended scheduled run
([workflow run](https://github.com/meridianlabs-ai/actions/actions/runs/33244962483)).

## Summary

**The `-rA` fix landed and delivered what it promised.** #5075 (the previous
run's report PR, promoted upstream by a maintainer) changed the pytest
invocation from `-rA` to `-ra`. Measured across this window: the `Test with
pytest` step went **324.5 → 292.5s** (3.10) / 323 → 301s (3.11), pytest's own
reported wall **328.7 → 287.1s (−41.6s)**, and Build wall clock on successful
code-touching runs **369.5 → 341s**, with p90 tightening from 434 to 353s. The
prediction was ~46s; the suite grew by 550 collected items in the same two days,
which costs ~4s of the difference back, so the gross effect is ~46s. Straight
hit. Job logs corroborate the mechanism: a `test` leg's raw log is now **5,477
lines against ~31,000** before.

**The long pole has moved off `test` and onto `docs`.** `test` legs are now
324–330s while the `docs` job is **392s** whenever it runs. `docs` binds the
Build run in 11 of 59 runs, and the run classes have inverted: docs-touching
pushes are now the *slowest* class (**406–422s**) and code-only pushes the
faster one (**341s**). The render cache from #297 hit **2 of 14** docs jobs
(14%) — the same ~10% it has managed in every window since it landed —
so the fix filed as
[#317](https://github.com/meridianlabs-ai/inspect_ai/issues/317) is now the
largest single wall-clock lever in the data, and this report adds direct
evidence for why the key churns (55 cache entries, 38 distinct keys, 4 ever
re-read; below).

**Two new findings, both measured rather than estimated:**

1. **The 55.3s of pytest startup is assertion rewriting, not bytecode
   compilation.** The last two reports asserted the latter; that was wrong and
   this report corrects it. `compileall` over `src` + `tests` takes 1.3s and
   leaves cold collection completely unchanged (36.2 → 33.4s), because pytest
   ignores plain `.pyc` for modules it rewrites and keeps its own
   `*-pytest-9.1.1.pyc`. Deleting only the rewritten pyc while keeping the plain
   ones reproduces the full cold cost (32.6s), and `--assert=plain` cuts cold
   collection to **14.9s**. So ~21s of the 36s single-process cold collect is
   assertion rewriting, paid again by every one of the 5 interpreters in a leg.
   `uv`'s `compile-bytecode` was measured as a candidate fix and **rejected**:
   +13.6s on install for −3.5s on collection.
2. **Rendering exception tracebacks costs ~60s of worker time per leg** — 5% of
   all test-execution worker time, ~15s of leg wall. Instrumented across two
   full local suite runs: 649 calls to `format_traceback`, ~250 of them missing
   the LRU cache, 208 tests affected. It is concentrated: the two
   `test_agent_bridge.py` Google tests pay **3.9s per render** because
   `rich.traceback` syntax-highlights every frame's source file through
   pygments, and their stack runs through the Google GenAI SDK.

**Queue is a non-issue this window.** Median 3s, p90 8s, worst 45s, zero waits
over 60s across 820 job records — the fifth window in a row with no evidence for
the runner-pool proposal.

**Still no code shipped by the scheduled run — seventh consecutive run.** All
three blockers were re-probed with real attempts today (details in proposal 2).

## Queue vs execution

Per job, this window against the last. `exec` is job execution seconds; `queue`
is measured from run start for independent jobs and from the predecessor's
completion for dependent ones (dependency map read from
`.github/workflows/build.yml`: `docs`/`sandbox-tools-unit` ← `changes`,
`check-version-bump`/`slow-tests` ← `detect-slow`, `slow-tool-tests-*` ←
`detect-slow` + `check-version-bump`).

| workflow | job | n | exec med | prev | exec p90 | queue med | queue p90 |
|---|---|---:|---:|---:|---:|---:|---:|
| Build | slow-tool-tests-dev | 1 | 754 | 895 | 754 | 23 | 23 |
| Build | **docs** | 14 | **392** | 384 | 418 | 14 | 20 |
| Build | test (3.11) | 53 | **330** | 356 | 346 | 3 | 13 |
| Build | test (3.10) | 54 | **324** | 355.5 | 339 | 3 | 14 |
| Build | mypy (3.10) | 58 | 90 | 88.5 | 96 | 3 | 19 |
| Build | mypy (3.11) | 58 | 88 | 87 | 94 | 3 | 16 |
| Viewer | viewer-tests | 59 | 69 | 75 | 75 | 3 | 4 |
| Viewer | check-schema-and-types | 59 | 59 | 57 | 66 | 3 | 6 |
| Viewer | dist-validation | 59 | 35 | 37 | 41 | 3 | 5 |
| Build | pre-commit | 59 | 33 | 34 | 37 | 3 | 14 |
| Build | package | 59 | 30 | 31 | 34 | 3 | 12 |
| Build | ruff | 59 | 11 | 11 | 12 | 3 | 14 |
| Viewer | submodule-on-main | 59 | 9 | 9 | 10 | 3 | 8 |
| Build | detect-slow | 59 | 9 | 9 | 11 | 3 | 18 |
| Build | changes | 59 | 8 | 8 | 9 | 3 | 21 |
| Changelog Lint | entries-under-unreleased | 50 | 7 | 7 | 9 | 3 | 4 |

Workflow wall clock, successful runs only (the `action_required` runs that sit
unapproved record a 0s wall and would otherwise drag every median down — 10 of
this window's 71 Build runs):

| workflow | n | wall med | prev | wall p90 | prev p90 |
|---|---:|---:|---:|---:|---:|
| Build | 52 | **342** | 390 | 412 | 445 |
| Validate Embedded Viewer | 59 | 74 | 80 | 80 | 97 |
| Changelog Lint | 46 | 10 | 11 | 12 | 13 |

Split by what the push touched:

| class | n | wall med | prev | p90 | Build runner-min |
|---|---:|---:|---:|---:|---:|
| code only | 42 | **341** | 369.5 | 353 | 15.3 |
| code + docs | 4 | 422.5 | 409.5 | 500 | 22.4 |
| docs only (no code) | 6 | 406.5 | — | 420 | 11.1 |

A code-only push costs ~18.3 runner-minutes end to end (Build 15.3 + Viewer 2.9
+ Changelog Lint 0.1), down from ~19.7 last window.

### Critical path

Binding job (last to finish) across 59 Build runs: `test (3.11)` 30 runs (wall
median 339.5s), `test (3.10)` 13 (342s), **`docs` 11 (412s)**, `mypy (3.10)` 4
(153.5s — design-only pushes, where #299 skips the test legs), `slow-tool-tests-dev`
1 (778s). The two `test` legs still bind most runs, but they are now only ~10s
apart from each other and 60–70s below `docs`, so any further `test` work moves
the median by less than it used to, while `docs` sets a hard floor of ~400s on
every push that touches documentation.

## Where the pytest step actually goes

Timestamps from the raw job log of `test (3.10)` in run 33229493965, and the
`--report-log` artifact from the same leg:

| phase | seconds | note |
|---|---:|---|
| `uv run` re-sync | 5.1 | uninstalls 38 packages, reinstalls 39, rebuilds `inspect-ai` |
| collection (5 interpreters) | 50.2 | banner "test session starts" appears at 55.3s into the step |
| test execution | 231.3 | 846.2 worker-seconds over 4 workers |
| reporting (durations, summary) | ~1.4 | this is the phase `-ra` emptied; it was ~46s |
| **step total, this leg** | **288** | window median 292.5 |

Startup is **19% of the step**. Local measurement on the same 4-core shape,
against a venv built the way CI builds it:

| variant | cold collect | note |
|---|---:|---|
| normal (single process) | 36.2s | |
| after `compileall src tests` | 33.4s | `compileall` itself takes 1.3s |
| rewritten pyc deleted, plain pyc kept | 32.6s | reproduces the full cost |
| `--assert=plain` | **14.9s** | rewriting disabled |
| warm (second run) | 12.7s | |

pytest writes `conftest.cpython-311-pytest-9.1.1.pyc` next to the plain
`conftest.cpython-311.pyc`: the rewritten module is a *different* cache entry,
validated by source mtime + size, and `compileall` never produces it. That is
why the "cache `__pycache__`" idea in the last two reports was mis-attributed —
and also why it can still work, but only if source mtimes are normalized after
checkout so the restored rewrite cache validates (proposal 4).

`uv`'s bytecode compilation was measured directly (two arms, two reps, fresh
venv and cleared `__pycache__` each time): `uv pip install .[dev]` 3.7–7.5s →
17.3s with `UV_COMPILE_BYTECODE=1`, collection 45.1–47.7s → 42.5–43.3s. Net
**+10s per leg**. Not worth shipping; recorded here so it is not re-proposed.

## Worker balance (`--dist worksteal`, #4948)

Sixth window holding. From the `test (3.10)` report-log artifact of run
33229493965: per-worker test time 209.4 / 207.9 / 211.6 / 217.3s, imbalance
**+5.8s over the average (97.3% efficiency)**, spans within 1.6s of each other.
gw3 ran 1,293 test records against gw1's 15,087 — the point of worksteal is
exactly that this no longer matters.

## Slowest tests

Median seconds per test, aggregated across the 20 legs mined this window
(`--durations=50 --durations-min=1`, `call` + `setup` + `teardown`).

| s | test | classification |
|---:|---|---|
| 11.5 | `test_eval_set.py::test_retry_attempt_killed_mid_sweep_leaves_completed_samples_reusable` | genuinely heavy — kills a live attempt mid-sweep |
| 10.9 | `test_eval_set_selection.py::test_eval_set_selection_concurrent_workers` | genuinely heavy — concurrent workers |
| 9.3 | `_control/test_launch_handoff.py::test_eval_detach_hands_off_and_leaves_eval_running` | subprocess launch; pays `import inspect_ai` (#311) |
| 9.3 | `test_eval_set_scanner.py::test_scout_scan_resume_reruns_failed_scans` | genuinely heavy |
| 9.3 | `_control/test_launch_handoff.py::test_eval_detach_via_dotenv_detaches_exactly_once` | subprocess launch (#311) |
| 7.8 | `agent/test_agent_bridge.py::test_google_bridge_computer_use_incompatible_model` | **~3.9s is traceback rendering** (new, below) |
| 7.0 | `_control/test_launch_handoff.py::test_eval_json_redirects_subprocess_stdout_to_stderr` | subprocess launch (#311) |
| 6.8 | `test_eval_set_scanner.py::test_scanner_resume_accumulates_summary_and_only_scans_rerun_samples` | genuinely heavy |
| 6.5 | `agent/test_agent_bridge.py::test_google_bridge_streaming_not_supported` | **~3.9s is traceback rendering** |
| 6.4 | `log/test_eval_log_config.py::test_eval_log_run_config_round_trip` | genuinely heavy (round-trips every config) |
| 6.2 | `test_eval_set.py::test_eval_set_previous_task_args` | ~5s real sleep around `keyboard_interrupt(2)` |
| 5.6 | `_control/test_launch_handoff.py::test_eval_detach_fails_when_control_bind_fails` | subprocess launch (#311) |
| 5.0 | `test_eval_set.py::test_task_identifier_with_task_limits` | five `hello_world` evals; not new (3.6s in the previous window's legs) |
| 5.0 | `test_sample_shuffle.py::test_sample_shuffle` | duplicate-ish with `test_sample_shuffle_limit` |
| 4.5 | `_control/test_pause.py::test_eval_hard_pause_time_limit_reap_reparks_grader` | timer-bound |
| 4.3 | `test_sample_limits.py::test_working_limit` | timer-bound |

### No per-test regression

Every newcomer to the top-20 was already this expensive last window and simply
crossed the ranking boundary: `test_task_identifier_with_task_limits` measured
3.62s in the previous window's 3.10 leg against 3.40s in this one's, and
`test_eval_set_retry_in_same_second_does_not_clobber_failed_log` 3.62 → 5.05s,
inside the ±8% per-leg noise band this series measured on 2026-08-27. Diffing
the two report-log artifacts leg-to-leg, the 14,298 tests present in both got
**10.4s faster** in aggregate.

### The traceback-rendering finding

`EvalError` carries both `traceback` (plain) and `traceback_ansi`, and the ANSI
variant is produced by `rich.traceback.Traceback.from_exception`, which builds a
`rich.Syntax` for each frame's source file — pygments lexes the file. Measured by
wrapping `inspect_ai._util.rich.format_traceback` for two full local suite runs:

- **59.9–62.2s of worker time per run**, 649 calls, ~250 of them missing the LRU
  cache, spread over 208 tests (83 above 0.2s).
- Top consumers: `test_agent_bridge.py` **17.1s**,
  `_control/test_eval_set_integration.py` 10.8s, `test_eval_set.py` 5.6s,
  `test_cancellation_logging.py` 3.8s.
- The two Google bridge tests render 3.9s *each* — a stack through the GenAI
  SDK means pygments lexes several thousand-line SDK modules. A standalone
  render of a deep GenAI traceback measures 0.91s; a repeat is 0.0003s (cache).

At 4 workers that is ~15s of every `test` leg, and it is also a product cost:
each *distinct* error in a real eval pays 0.3–4s of CPU before the sample's
error is recorded. Filed as
[#374](https://github.com/meridianlabs-ai/inspect_ai/issues/374).

### Docker-trap sweep

Unchanged: six tests pair `skip_if_no_docker` with no `@pytest.mark.slow`, all
sub-100ms because they skip for reasons other than docker. No new pairing
violations; nothing in the durations tail touches docker.

## Suite size

| snapshot | collected items | pytest wall (median leg) | Build wall (success) |
|---|---:|---:|---:|
| 2026-08-18 | 13,245 | 407.4 | 482.5 |
| 2026-08-19 | 13,247 | 393.1 | 472.0 |
| 2026-08-21 | 13,370 | 290.7 | 362.5 |
| 2026-08-23 | 13,410 | 299.3 | 354.0 |
| 2026-08-25 | 13,449 | 304.8 | 353.0 |
| 2026-08-27 | 14,123 | 328.7 | 390.0 |
| 2026-08-29 | **14,673** | **287.1** | **342.0** |

+550 items in two days (+3.9%), ~+91 items/day over the last eleven days.

**Priced directly this window**, by diffing the `--report-log` artifacts of the
3.10 leg at each end of the window (14,300 → 14,679 test IDs in those two
specific legs): **381 test IDs added, costing 15.0s of worker time**; 2 removed;
the tests present in both got 10.4s faster (noise). Net measured worker time
841.9 → 846.2s. So two days of growth is ~**+3.8s of leg wall** — real, but an
order of magnitude below the two findings above.

### Where the time actually sits (from the report log, 14,679 tests, 846.2 worker-s)

| band | tests | worker-s | share |
|---|---:|---:|---:|
| ≥1s | 151 | 345.8 | 40.9% |
| 0.1–1s | 1,221 | 429.6 | 50.8% |
| <0.1s | 13,307 | 70.8 | 8.4% |

Median test: **3.3ms**. Mean: 57.6ms. Phase split: call 795.0s, setup 33.1s,
teardown 18.1s.

This changes the framing the last three reports used. The "body of ordinary
tests" is *not* the long pole: 91% of the tests account for 8% of the time. The
mass is in a **middle band of 1,221 tests between 0.1s and 1s** — half of all
test time — which is where an eval-invoking test lands. Adding 550 cheap tests
costs almost nothing; adding 50 that each `eval()` something costs 30s of worker
time. Test-volume policy (proposal 8) should be about that band, not about the
count.

### Duplicate-coverage and low-value sampling

Sampled the four fastest-growing test files of the window (`test_http_defaults.py`
777 lines / 29 new test functions, `providers/test_openai_compatible.py` 691/18,
`test_eval_set_pruning.py` 594/17, `checkpoint/test_sample_runtime.py` 324/17).
All four are parametrized rather than copy-pasted, with per-test costs in the
0.4–0.7s range for the pruning file and under 0.1s for the rest; nothing worth
deleting. The AST sweep for identical test bodies returns the same **11 exact
duplicate pairs** as last window (unchanged list; `test_message_ids.py` /
`test_stable_message_ids.py` still the only duplicated *subject*), worth well
under 2s combined.

## Regressions since last report

None. `test` execution worker time is flat (841.9 → 846.2s on matched legs),
`mypy` is flat (66.5s of `Run mypy`), `viewer-tests` is holding the recovery
noted last window (40s, against 54s at the regression's peak), and no test
crossed the noise band in either direction.

## Waste

- **Cancelled superseded runs: 6 runs, 46.8 runner-minutes** (was 10 runs /
  107.5 min). The worst two were `claude/issue-355-…` at 13.1 min and
  `claude/issue-357-…` at 9.8 min — force-pushes that superseded a run whose
  `test` legs were already several minutes in. Concurrency cancellation is doing
  its job; the residue is inherent.
- **Runs that never ran: 27 `action_required`** (fork PRs awaiting maintainer
  approval). No compute, but they distort any wall-clock statistic that does not
  filter on conclusion — this report does.
- **Overhead-dominated jobs:** `ruff` is 11s of which 5s is checkout and 2s is
  actual linting; `changes` and `detect-slow` are 8–9s each of nearly pure
  setup. Combined ~28s of runner time per push, none of it on the critical path.
- **Docs render cache entries:** 55 entries, 38 distinct keys, **4 ever
  re-read**, 16–22 new keys/day, ~0 bytes each (marker file only). Cheap to
  store, but the churn is the point — see proposal 1.

## Impact verification (previous runs' changes)

- **#5075 (`-rA` → `-ra`, merged 2026-08-27 14:02Z) — verified, prediction hit.**
  Predicted ~46s off the pytest step; measured pytest-reported wall 328.7 →
  287.1s (−41.6s) with +550 items of growth (+4.3s of measured worker time) in
  the same window, i.e. ~46s gross. Build wall on code-only pushes 369.5 → 341s,
  p90 434 → 353s. Raw `test` leg logs: ~31,000 lines → 5,477. Every run in this
  window is post-merge (a `pull_request` run takes its workflow *and* its
  `pyproject.toml` from the merge ref), so there is no pre/post split to make
  inside the window; the comparison is window-to-window and the previous window
  is entirely pre-merge.
- **#297 (docs render cache) — third window, hit rate unchanged at ~11%.**
  2 hits in 14 docs jobs. Both hits were re-reads of a cache entry created by an
  earlier push on the *same* PR branch. New evidence added this window (posted to
  #317): the repository holds 55 `docs-render-*` entries over 38 distinct keys of
  which only 4 have ever been re-read, and cache scoping means a PR-scoped entry
  is invisible to any other branch, so the only reuse GitHub will ever allow for a
  PR is main→PR (killed by the key churn) or push→push within one branch (the
  observed 11%).
- **#299 (`design/**` excluded from the test filter) — holding.** The four
  design-only pushes in this window ran `mypy` as their binding job at 153.5s
  Build wall instead of ~340s.
- **#4948 (`--dist worksteal`) — holding, sixth window** (imbalance +5.8s, 97.3%
  efficiency).
- **#4760 (`test_package` pre-installed) — holding**: no `test_extensions` test
  appears anywhere in the durations tail.
- **#342 was the report proposal; it is now closed by #5075.** Verification
  comment posted on the issue.

## Proposals (ranked)

1. **Fix the docs render cache key so `main` churn stops invalidating it.**
   Now the top lever, because `docs` has become the binding job class: 392s of
   exec whenever it runs, 406–422s of Build wall on docs-touching pushes against
   341s for code-only ones. Third window of measurement, hit rate stuck at
   ~11% (2/14; 1/13 and 2/19 before). The cause is now fully characterized: on
   `pull_request` the checkout is the *merge* ref, so `hashFiles('docs/**',
   'requirements-doc.txt', 'src/inspect_ai/**')` hashes the PR merged into
   current `main`, and any push to `main` touching `src/inspect_ai/**`
   invalidates every open PR's key — 38 distinct keys in three days, 4 ever
   re-read. Proposed key: `docs/**` + `requirements-doc.txt` + the PR's *own*
   source delta, not the merged source tree. Est. impact: ~360s of job exec per
   hit, ~27–65s of Build wall on the two-thirds of docs-touching runs where
   `docs` finishes last. Structural (workflow change this run cannot push).
   Status: carried, [#317](https://github.com/meridianlabs-ai/inspect_ai/issues/317),
   re-evidenced today.

2. **Unblock the scheduled run.** Re-probed today with real attempts, all three
   still standing:
   - *No `workflow` scope* — pushed a probe branch carrying a one-byte
     `.github/workflows/build.yml` edit to the fork; rejected with `refusing to
     allow a Personal Access Token to create or update workflow
     .github/workflows/build.yml without workflow scope`. A control push of a
     non-workflow file on the same branch succeeded, so the block is
     scope-specific, not repo-wide. Both probe branches deleted.
   - *`.claude/**`* — a plain write under `.claude/skills/ci-perf/` is refused by
     the agent's edit tooling as a "sensitive file", asking for an approval no
     scheduled run can give. Harness policy, not a token.
   - *No upstream write* — `repos/UKGovernmentBEIS/inspect_ai` reports
     `push: false` for this token; PR creation was attempted at the end of this
     run (result recorded in `prs.md`).

   Consequence: proposals 1, 4, 5 and 7 are all unshippable by this skill, and it
   has now shipped zero code for **seven consecutive runs** — while proposal 1
   alone is worth ~60s of wall clock on docs pushes and proposal 4 ~30s on every
   code push. Structural (credentials + harness policy). Status: carried,
   re-evidenced on [#298](https://github.com/meridianlabs-ai/inspect_ai/issues/298).

3. **Stop rendering `traceback_ansi` eagerly (or stop syntax-highlighting it).**
   NEW. ~60s of worker time per `test` leg (~15s of leg wall, 5% of all test
   execution), and 0.3–4s of CPU per distinct error for real users, spent in
   pygments lexing whole source files for `rich.traceback`. Options, cheapest
   first: cap `max_frames` on `Traceback.from_exception`; skip the ANSI render
   when nothing will consume it (it duplicates `traceback`, which is always
   present); or render lazily at display time. Product change with a public field
   (`EvalError.traceback_ansi`) in play — outside this skill's safe-fix
   categories. Status: **new**,
   [#374](https://github.com/meridianlabs-ai/inspect_ai/issues/374).

4. **Cache pytest's assertion-rewrite bytecode across runs.** Startup is 55.3s of
   the 292.5s step; ~21s of a 36s cold single-process collect is assertion
   rewriting, and five interpreters pay it in parallel on four cores. Warm
   collection is 12.7s. Fix shape: restore `**/__pycache__` from `actions/cache`
   keyed on a hash of `src/**/*.py` + `tests/**/*.py`, and normalize source
   mtimes deterministically right after checkout in both the producing and the
   consuming run — pytest validates a rewritten pyc against source mtime + size,
   which a fresh checkout otherwise breaks. Est. **~30s off both `test` legs**
   (55.3s startup → ~25s), i.e. ~30s of Build wall on code-only pushes. Needs
   one CI experiment to confirm the restored cache actually validates before it
   is worth shipping. Note what does *not* work, both measured today:
   `compileall` (wrong cache entry, 1.3s and no effect) and `uv`'s
   `compile-bytecode` (+13.6s install for −3.5s collect). Structural (workflow
   change). Status: **new, replaces the mis-attributed "bytecode compilation"
   item from the last two reports**.

5. **`uv run` re-syncs the environment the previous step just installed.**
   Unchanged and re-measured from this window's logs: 5.1s per `test` leg
   uninstalling 38 packages and reinstalling 39 before pytest starts, because
   `uv run` syncs the project environment while `Install dependencies` built it
   with `uv pip install`. `uv run --no-sync pytest` (or `.venv/bin/pytest`)
   removes it. ~9 runner-min per 200 runs, ~5s of wall clock. Workflow hygiene,
   same push blocker as proposals 1 and 4 — fold into whichever workflow change
   lands first. Status: carried, low.

6. **Defer the `acp.schema` import.** Unchanged: 483ms of the 1.70s self-time of
   `import inspect_ai`, ~7x the next-largest module, reached through two eager
   edges. Paid by 5 interpreters per leg plus the subprocess-spawning tests that
   own five of the top twelve slots in the durations tail. Product change with a
   public-API surface. Status: carried,
   [#311](https://github.com/meridianlabs-ai/inspect_ai/issues/311).

7. **Test-volume policy — reframed.** The measurement this window contradicts how
   the last three reports posed this: 13,307 tests under 0.1s account for 8.4% of
   test time, while 1,221 tests in the 0.1–1s band account for 50.8%. Two days of
   growth (+381 IDs on matched legs) cost 15.0s of worker time — ~3.8s of leg
   wall. The question worth asking a maintainer is therefore not "how many tests"
   but "how many tests may call `eval()`", and whether the mid-band deserves a
   shared in-process fixture. Structural. Status: carried, **reframed**.

8. **Duplicate and near-duplicate test cleanups.** The AST sweep still finds the
   same 11 exact-duplicate pairs and one duplicated subject
   (`test_message_ids.py` / `test_stable_message_ids.py`); the real-sleep
   candidates are unchanged (`test_eval_set_previous_task_args` spends ~5s of its
   6.2s sleeping around a `keyboard_interrupt(2)` that must land mid-eval;
   `test_sample_shuffle` / `test_sample_shuffle_limit` differ by `limit=20`).
   Combined value is under 2s of wall clock against a review cost and a coverage
   risk on every item, which is why this run again declined to ship it as its
   "safe fix". Status: carried, low.

9. **Collector: validate the run window and refetch.** Did not bite this run
   (single clean fetch; the three >2h gaps in this window are genuine quiet
   periods, verified against run timestamps). The one-file fix — accumulate pages
   across attempts and treat "now" as the newest edge so a stale *first* page is
   caught like a stale middle one — is unchanged and still uncommittable
   (proposal 2). Status: carried, **blocked**.

10. **Runner pool size for burst absorption.** Sixth consecutive window with no
    supporting evidence: median queue 3s, p90 8s, maximum 45s, zero waits over
    60s in 820 job records. Structural/cost. Status: carried, **evidence points
    the other way; drop unless a burst window shows otherwise**.

11. **Merge the 4 Viewer jobs into 1–2** — required-check rename. The Viewer
    workflow is 74s wall and 2.9 runner-min; nothing to win but job-count
    reduction. Structural. Status: carried, low.

12. **Policy consistency: docker tests without `@pytest.mark.slow`.** Still six,
    still ~0.05s combined; the right fix is probably to drop `skip_if_no_docker`
    from the three ungated ones rather than to mark them slow. Zero wall-clock
    impact either way. Status: carried.

Dropped from this report: proposal 1 of the last report (`-rA`, shipped in #5075
and verified above) and the previous "bytecode compilation" framing of the
startup cost (superseded by proposal 4 with contrary evidence).

## PRs opened by this skill

See `prs.md`. This run ships the snapshot, this report and the ledger update —
**no code fix, the seventh consecutive run with none**, for the reasons in
proposal 2: every ranked item that is worth shipping lives in
`.github/workflows/**` (proposals 1, 4, 5) or is a product change requiring a
maintainer decision (proposals 3, 6). One new issue was filed
([#374](https://github.com/meridianlabs-ai/inspect_ai/issues/374)), evidence was
added to [#317](https://github.com/meridianlabs-ai/inspect_ai/issues/317) and
[#298](https://github.com/meridianlabs-ai/inspect_ai/issues/298), and the
verified impact of #5075 was recorded on
[#342](https://github.com/meridianlabs-ai/inspect_ai/issues/342).
