# CI performance report — 2026-08-23

Data: 200 PR runs, 2026-08-21 01:31 .. 2026-08-22 16:35 UTC (39h). Snapshot:
`history/2026-08-23.json`. Previous: 2026-08-21 (200 runs, 2026-08-20 10:47 ..
2026-08-21 09:10). **The windows overlap by 7.6h — 39 of 200 runs are shared**,
so day-over-day medians are ~20% contaminated; the splits below are computed on
the run's own attributes (PR shape, workflow file at the head SHA) rather than
on time wherever it matters. Produced by the unattended scheduled run
([workflow run](https://github.com/meridianlabs-ai/actions/actions/runs/32630210430)).

## Summary

**Proposal 9 shipped and was verified on its first-ever execution.** A
maintainer removed the `slow-tool-tests-dev` → `slow-tool-tests-release` `needs`
edge in #4987, and this window contains the first successful `release` run in
five windows: it started **at the same second as `dev`** (17:35:25) and finished
in 744s while `dev` ran 812s. Under the old topology that run's Build wall would
have been ~1614s instead of 867s — **~12.5 min saved**, against a predicted
"~13 min". Estimate and outcome agree for once.

**Both workflow fixes from the last report are shipped but completely
unverified — no PR in this window exercised either path.** The Quarto render
cache (#297) and the `design/**` test-filter exclusion (#299) merged at
2026-08-21T18:08Z; of the 20 Build runs that started after that, **not one
touched `docs/**`** (every `docs` job skipped) and none was design-only. Both
carry forward with "predicted, unmeasured".

**The one new execution-side finding is an import, not a job.**
`import inspect_ai` takes **1.85s**, of which **`acp.schema` alone is 476ms
(26%)** — six times the next-largest module and reached through two eager import
edges. `inspect --version` takes 2.05s. This is paid by every CLI invocation, by
all five pytest processes per matrix leg, and by the ~47 subprocess spawn sites
in `tests/` that now dominate the slow tail. Filed as
[meridianlabs-ai/inspect_ai#311](https://github.com/meridianlabs-ai/inspect_ai/issues/311).

**This run ships no code fix, for the fourth consecutive run, for the same
reason.** All three blockers in proposal 3 were re-probed today and all three
still hold. The collector's stale-page bug (proposal 5) also bit for real this
time and had to be worked around with a throwaway retry wrapper.

## Queue vs execution

Median execution / queue over successful jobs. Queue for dependent jobs is
measured from predecessor completion (`needs` map read from the workflow files).

| Workflow | Job | n | exec med | exec p90 | queue med | queue p90 |
|---|---|---|---|---|---|---|
| Build | slow-tool-tests-dev | 12 | 814s | 885s | 2s | 3s |
| Build | slow-tool-tests-release | 1 | 744s | — | 2s | — |
| Build | docs (when docs change) | 13 | 351s | 392s | 3s | 3s |
| Build | test (per matrix leg) | 101 | 332s | 354s | 3s | 19s |
| Build | slow-tests | 1 | 185s | — | 2s | — |
| Build | sandbox-tools-unit | 6 | 175s | 179s | 3s | 8s |
| Build | mypy (per matrix leg) | 116 | 87s | 94s | 3s | 19s |
| Validate Embedded Viewer | viewer-tests | 59 | 66s | 83s | 3s | 3s |
| Validate Embedded Viewer | check-schema-and-types | 54 | 54s | 63s | 3s | 4s |
| Build | pre-commit | 59 | 32s | 35s | 3s | 20s |
| Validate Embedded Viewer | dist-validation | 59 | 31s | 38s | 3s | 4s |
| Build | package | 59 | 29s | 34s | 3s | 21s |
| Build | ruff | 59 | 10s | 13s | 3s | 19s |
| Build | check-version-bump | 16 | 9s | 11s | 3s | 6s |
| Build | detect-slow | 59 | 8s | 10s | 3s | 19s |
| Validate Embedded Viewer | submodule-on-main | 58 | 8s | 9s | 3s | 4s |
| Build | changes | 59 | 7s | 9s | 3s | 19s |
| Changelog Lint | entries-under-unreleased | 53 | 6s | 8s | 3s | 3s |

Workflow wall clock: Build **357s median / 794s p90** (was 384 / 790); Validate
Embedded Viewer 71s / 90s (was 66 / 81); Changelog Lint 10s / 12s (unchanged).

**Build's 384 → 357s is a mix shift, not a speedup.** Split by PR shape it is
flat everywhere:

| PR shape | n (prev) | wall median | prev | binding test leg | prev |
|---|---|---|---|---|---|
| code-only | 24 (10) | 342s | 343s | 336s | 339s |
| docs-touching | 12 (24) | 367s | 392s | 336s | 344s |
| sandbox-tools | 7 (6) | 803s | 812s | 339s | 345s |

Docs-touching PRs fell from 60% of successful Build runs to 28%, and they are
the expensive shape, so the overall median dropped without any job getting
faster.

### Queue: calm, with a rare 5-minute stall that is not contention

Across 815 independent-job samples: median 3s, p75 4s, **p90 18s, p95 27s, p99
42s, max 303s**. 25 jobs waited more than 30s (was 43) and 4 waited more than
120s (was 1). The hourly medians are 3s in every single hour, including 02:00
UTC (49 starts, 18s p90) — the burst that dominated the 08-18/08-19 reports has
not recurred in two windows.

The four waits over 120s are **not** pool saturation and should not be counted
as such: they are 303s, 303s, 303s and 302s — a suspiciously exact five
minutes — and each is a *single* job inside a run whose every sibling started in
2–4s. That signature is a runner-assignment stall on GitHub's side, not a queue.
Four job starts out of 815 (0.5%), across three pushes:

| Run | Stalled job | Wall-clock cost |
|---|---|---|
| 32579869066 (Build) | `mypy (3.10)`, 303s | none — `test (3.11)` ran 468s and still finished last |
| 32513323318 (Build) | `package`, 303s | none — finished 16s before `test (3.10)` |
| 32513323379 (Viewer), same push | `check-schema-and-types`, 302s | **+280s**: Viewer wall 351s against a 71s median |
| 32437903757 (Build) | `changes`, 303s | run was cancelled as superseded, so nothing measurable — but the stall propagated through `needs` and held `docs` and `sandbox-tools-unit` at the gate for the whole 303s |

Worth watching rather than acting on: 0.5% of job starts, no lever this repo
controls, but it is the only thing in the queue data that costs minutes.

### Critical path

Last-finishing job across the 43 successful Build runs:

| Last job | runs | median margin over the runner-up |
|---|---|---|
| `test` | 29 | 237s |
| `slow-tool-tests-dev` | 7 | 470s |
| `docs` | 7 | 48s |

`test` is back to being the determinant for the common PR (it was 18 of 40 last
window), purely because fewer PRs touched docs. On the 12 docs-touching runs
`docs` still finished last in 7, a median +48s past the slower test leg — so
proposal 1's premise is intact even though its sample shrank.

## Worker balance (`--dist worksteal`, #4948)

Still holding, from three post-merge report-log artifacts and the job-level
spread:

| Run | Leg | worker busy | max | avg | imbalance | efficiency |
|---|---|---|---|---|---|---|
| 32585165684 | 3.10 | 196 / 193 / 192 / 203 | 203s | 196s | +7s (4%) | 96% |
| 32585165684 | 3.11 | 204 / 203 / 199 / 207 | 207s | 203s | +4s (2%) | 98% |
| 32582951627 | 3.10 | 170 / 178 / 172 / 176 | 178s | 174s | +4s (2%) | 98% |

Build runs whose two `test` legs differ by more than 60s: **3 of 49 (6%)**,
median spread 17s — against 3 of 47 (6%) and 23s last window, and 21% before the
fix.

## Slowest tests

Median seconds across 20 CI test jobs, `call` + `setup` + `teardown` combined.
137 tests captured (`--durations-min=1`), 195.0s total per job.

| Median | Test | Classification |
|---|---|---|
| 11.0s | `test_eval_set.py::test_retry_attempt_killed_mid_sweep_leaves_completed_samples_reusable` | genuinely heavy — two real harness subprocesses, one SIGKILLed |
| 9.7s | `test_eval_set_scanner.py::test_scout_scan_resume_reruns_failed_scans` | genuinely heavy (eval_set + scout scan resume) |
| 9.2s | `_control/test_launch_handoff.py::test_eval_detach_via_dotenv_detaches_exactly_once` | real CLI subprocess + control-server handshake |
| 9.0s | `test_eval_set_selection.py::test_eval_set_selection_concurrent_workers` | **new** (#5000) — three real `inspect_ai` subprocesses; docstring says so explicitly. Inherent |
| 9.0s | `_control/test_launch_handoff.py::test_eval_detach_hands_off_and_leaves_eval_running` | real CLI subprocess |
| 6.8s | `agent/test_agent_bridge.py::test_google_bridge_computer_use_incompatible_model` | full `eval()`; cost is bridge/SDK import + eval startup |
| 6.7s | `_control/test_launch_handoff.py::test_eval_json_redirects_subprocess_stdout_to_stderr` | real CLI subprocess (documented: needs real fds) |
| 6.4s | `test_eval_set_scanner.py::test_scanner_resume_...[s3]` | moto S3 + full eval-set resume |
| 6.3s | `log/test_eval_log_config.py::test_eval_log_run_config_round_trip` | round-trips a full run config through eval |
| 6.2s | `agent/test_agent_bridge.py::test_google_bridge_streaming_not_supported` | (as above) |
| 6.1s | `test_eval_set.py::test_eval_set_previous_task_args` | **real sleeps**: ~5s is `sleep_for_3_task` plus a `keyboard_interrupt(2)` timer |
| 5.7s | `_control/test_launch_handoff.py::test_eval_detach_fails_when_control_bind_fails` | real CLI subprocess |
| 4.3s | `_control/test_pause.py::test_eval_hard_pause_time_limit_reap_reparks_grader` | real timers inherent to pause/limit semantics |
| 4.2s | `test_sample_limits.py::test_working_limit` | real waits inherent to limit tests |
| 4.0s | `_control/test_launch_handoff.py::test_eval_detach_sigterm_terminates_child` | real CLI subprocess + a deliberate 1.0s SIGTERM-handler grace sleep |

**Eight of the top fifteen spawn at least one real interpreter that imports
`inspect_ai`** — the five `test_launch_handoff.py` entries plus
`test_retry_attempt_killed_mid_sweep…` (two spawns),
`test_eval_set_selection_concurrent_workers` (three) and
`test_eval_log_run_config_round_trip` (verified by reading each test, not
inferred from the name). That is what makes the import cost below a test-suite
problem and not only a CLI problem.

### The tail did not get slower; it got longer

Tail total per job 176.9s → 195.0s (+18.1s). Decomposed:

- **84 tests present in both windows: +7.0s.** Spread over 84 tests, and inside
  the noise — the same test (`test_eval_detach_via_dotenv…`) ranges 5.7s to
  10.4s across the 20 legs of *this* window alone. Not a regression.
- **53 tests newly in the ≥1s tail: +20.8s**, led by
  `test_eval_set_selection_concurrent_workers` (5.2s amortized over the 12 legs
  that ran it, 9.0s where it ran).
- **35 tests left the tail: −9.7s.**

So the growth is new tests arriving, not existing tests degrading. Worth stating
plainly because the raw medians (e.g. 8.5 → 11.0s on the #1 test) read like a
regression and are not one.

### Docker-trap sweep

An AST sweep of every `tests/**` test function decorated with
`skip_if_no_docker` but not `@pytest.mark.slow` found **6**, the same six as
last run (`util/sandbox/test_docker_compose_config.py` ×3, measured at 0.05s
combined against a live daemon; `tools/test_think_tool.py` ×2 and
`agent/test_agent_docs.py::test_agent_collect`, all gated by a missing API key
and skipping in ~1ms). No change; see proposal 12.

## Suite size

Per matrix leg (pytest summary line, 20 CI jobs): **13,410 tests collected —
9,573 passed, 3,839 skipped** (medians), in 299s median pytest wall.

| Snapshot | legs | pytest wall (median) | collected | ≥1s tail total |
|---|---|---|---|---|
| 2026-08-19 (2 workers) | 20 | 393s | 13,247 | 149s |
| 2026-08-21 (4w worksteal) | 18 | 291s | 13,370 | 177s |
| 2026-08-23 (4w worksteal) | 20 | **299s** | **13,410** | **195s** |

From the report-log artifacts (three legs):

- **Test-phase work 697–813s per leg** (785s / 813s on the 3.10 / 3.11 legs of
  run 32585165684), of which call 733/771s, setup 33/27s, teardown 19/14s.
- **Tail vs body:** 8–14 tests ≥5s = 56–107s (8–13%); 126–157 tests ≥1s =
  270–368s (39–45%); the remaining **~13,270 tests = 427–469s (55–61%)**.
- **Heaviest files:** `test_eval_set_scanner.py` 51–59s, `test_eval_set.py`
  50–60s, `_control/test_launch_handoff.py` 38–48s, `test_sample_limits.py`
  32–35s, `_control/test_eval_set_integration.py` 27–50s,
  `_view/test_view_server.py` 17–24s, `agent/test_agent_bridge.py` 14–25s.
- **Collection and startup is still ~100s of the ~300s pytest step** (342 − 203,
  310 − 207, 276 − 178 = 139 / 103 / 98s of step time not accounted for by the
  busiest worker). Unchanged; see proposals 2 and 4.

### `import inspect_ai` is 1.85s and a quarter of it is one dependency

Measured on this run's checkout (`python -X importtime`, ambient dev install,
warm filesystem):

| Item | Cost |
|---|---|
| `python -c "import inspect_ai"` | 1.85s (3 runs, ±0.01s) |
| `inspect --version` | 2.05s (3 runs) |
| `acp.schema` (self time) | **476ms** |
| next largest, `inspect_ai.log._log` | 76ms |
| `pydantic` for comparison | 39ms |
| total import self-time for `inspect --version` | 1843ms over 1791 modules |

`acp.schema` is reached eagerly through **two independent edges**, so deferring
either alone changes nothing:

1. `inspect_ai/__init__` → `_eval.eval` → `from inspect_ai.agent._acp.server
   import acp_server`, and `server.py` imports `acp.interfaces` → `acp.schema`
   at module level.
2. `inspect_ai.util.__init__` → `_input._types` and `_input.request`, both of
   which import `ElicitationSchema` from `acp.schema` for **annotations only**
   (a dataclass field and a keyword-only parameter).

Edge 2 looks like a `from __future__ import annotations` + `TYPE_CHECKING`
change; edge 1 is a real decision about whether `eval()` should pull the ACP
server at import time. Both are product changes outside this skill's safe-fix
categories, so this is a proposal, filed as
[#311](https://github.com/meridianlabs-ai/inspect_ai/issues/311).

Value, stated separately because the confidence differs:
- **User-facing, directly measured:** `inspect --version` 2.05s → ~1.5s, and the
  same ~0.5s off every other CLI invocation.
- **CI, estimated:** 5 interpreter startups per matrix leg (controller + 4
  workers) ≈ 2.5s, plus the ~47 `sys.executable`/`subprocess` spawn sites in
  `tests/` — the cluster that now owns most of the slow tail — at ~0.5s each.
  Order of magnitude **~15–25s of worker time per leg, ~4–6s of leg wall** at
  four workers. Not verified by an A/B; the import numbers are.

### Growth

Top-level test functions at `origin/main` (`^(async )?def test_` under
`tests/`), re-derived at the last commit before 12:00 UTC on each date:

| Date | test functions | Δ |
|---|---|---|
| 2026-08-12 | 7,423 | — |
| 2026-08-18 | 7,716 | +293 (6d) |
| 2026-08-19 | 7,723 | +7 |
| 2026-08-21 | 7,786 | +63 (2d) |
| 2026-08-23 | 7,843 | +57 (2d) |

~+200 test functions/week, +40 collected items in two days. But the *cost* of
growth was lumpier than the count: the ≥1s tail took +18s per job in two days,
and +20.8s of that came from 53 tests newly crossing the 1s line — led by
`tests/test_eval_set_selection.py` (new in #5000), whose single
three-subprocess test is worth 5.2s per leg on its own. Last report priced
growth at +1–6s of leg wall per week; two days beat the top of that band. The
band is not wrong on average — it is the wrong shape.
Proposal 6 stays a maintainer question, unchanged in urgency.

### Duplicate-coverage and low-value sampling

`tests/test_eval_set_selection.py` (785 lines, 18 tests, the fastest-growing
file) was read: one expensive real-process test and 17 in-process ones, no
duplication — this is the shape we would ask for. Carried forward, unchanged:
`test_sample_shuffle` (4.0s) and `test_sample_shuffle_limit` assert the same
seeded-order property with and without `limit=20` and could be one parametrized
test (~2.4s); the `test_launch_handoff.py` cluster (5 tests, 38–48s) each spawns
the real CLI and the cost is inherent — though it is precisely the cluster that
proposal 2 (the import) would speed up. No exact duplicates found, so no test
deletion was eligible as a safe fix.

## Regressions since last report

- **None on the critical path.** Every job's exec median is within 5s of the
  previous window except `slow-tool-tests-dev` (764 → 814s) and `docs`
  (378 → 351s), both explained below.
- `slow-tool-tests-dev` **is not a regression**: its `Run slow tool tests` step
  is flat at 730 → 733s median. The job-level rise is entirely the
  `Build sandbox-tools -dev binaries` step, which fired on 3 of 12 runs this
  window (105–111s each) and 0 of 8 last window.
- `docs` 378 → 351s: 13 samples against 31, all pre-cache. Noise.
- Validate Embedded Viewer wall 66 → 71s median, 81 → 90s p90: the p90 is the
  single 302s runner-assignment stall described above.
- Run conclusions: 149 success, 24 failure (was 18), 7 cancelled (was 10),
  **20 `action_required`** (was 29) — still ~1 in 10 runs starting behind a human
  approval gate.

## Waste

- **Cancelled jobs: 90.6 runner-min** across the 200 runs (was 85.8), 7 runs
  cancelled outright (was 10). `test` legs account for 50.4 of those minutes,
  `slow-tool-tests-dev` 15.8, `docs` 14.5. This is `cancel-in-progress` working
  as intended on busy branches, not a defect.
- **Failed jobs burned 56.1 runner-min** (was 41.6): `test` 21.5,
  `sandbox-tools-unit` 17.9, `slow-tool-tests-dev` 9.8. The `sandbox-tools-unit`
  failures are all on two branches and are the subject of
  [issue #308](https://github.com/meridianlabs-ai/inspect_ai/issues/308);
  `entries-under-unreleased` failed 9 times (cheap, 1.0 min total).
- Compute: **1,288 runner-min** per 200 runs (Build 1,122; Viewer 158; Changelog
  Lint 7), up from 1,237 — more sandbox-tools PRs in this window.
- **Every PR still fans out ~20 job records.** Five remain overhead-dominated:
  `ruff` 10s exec for ~1.5s of linting, `changes` 7s, `detect-slow` 8s,
  `check-version-bump` 9s, `submodule-on-main` 8s. Irrelevant to wall clock,
  relevant to burst load (proposals 7 and 11).
- `docs`: 290s Quarto render + 40s dependency install, still uncached **in every
  sample here** — all 13 predate the cache.
- One ~5-minute runner-assignment stall cost ~280s of Viewer wall (see "Queue").

## Impact verification (previous runs' PRs)

**Un-serializing `slow-tool-tests-release` (#4987) — verified, estimate hit.**
Proposal 9 had gone four windows with zero executions to measure. It got one.
Classifying by the `needs:` list in `build.yml` at each run's head SHA (not by
time — the squash merge makes ancestry tests misleading here):

| Run | build.yml `needs` | dev | release | outcome |
|---|---|---|---|---|
| 32485221456 | includes `slow-tool-tests-dev` | 13:07:46 → 13:22:33 | **13:22:36** → 13:23:22 | serialized: release starts 3s after dev ends |
| 32508865021 | dev edge removed | 17:35:25 → 17:48:57 | **17:35:25** → 17:47:49 | parallel; release 744s, succeeded |

Run 32508865021's Build wall was 867s. Serialized it would have been ~1614s:
**~12.5 min saved on the only PR shape where `release` runs at all**, against a
predicted "~13 min". The predicted downside — `release` burning ~14 runner-min
when `dev` fails instead of being skipped — did not materialise: across the 16
runs where either job ran, `dev` never failed with `release` eligible. It cost
**2.0 runner-min once**, in a superseded run (32508682673) where `release` had
been running 122s in parallel when the whole run was cancelled; under the old
edge it would not have started.

**Quarto render cache (#297) — shipped, zero observations.** Of the 20 Build
runs that started after the 2026-08-21T18:08Z merge, every `docs` job was
skipped: no PR touched `docs/**` or `requirements-doc.txt`. The cache step
(`Check for previous successful render`) appears in **0** of the 13 `docs` job
records in this snapshot. Prediction stands unchanged and unmeasured; carry to
the next run.

**`design/**` test-filter exclusion (#299) — shipped, zero observations.** The
only no-op `test` legs in the window (6s, run 32436669508) are a docs-only PR
from before the change. No design-only push occurred after it merged. Note that
this report's own PR is a design-only push and will be the first observation —
if it no-ops the two `test` legs, that is the fix working.

**#4948 (`--dist worksteal`) — continues to hold.** 96–98% worker efficiency,
+4–7s imbalance, 6% of runs with a >60s leg spread. See "Worker balance".

**#4935 (`blob:none`) — fully closed out.** `slow-tool-tests-release` executed
for the first time in any window and its checkout took **9s** (against 56s+ for
the full-history checkouts #4935 replaced), matching every other converted job.
That was the last unverified leg from #4935; nothing outstanding.

## Proposals (ranked)

1. **Cache the Quarto render for `docs`.** Implemented by a maintainer in
   commit `7992b1ce8` (issue
   [#297](https://github.com/meridianlabs-ai/inspect_ai/issues/297), closed).
   Still the largest single execution-side item when it runs: 290s of the 351s
   job. Predicted win ~40–48s of wall on the docs-touching PRs where `docs`
   finishes last (7 of 12 this window), plus ~290s on a docs-only PR. Status:
   **shipped, unverified — no docs-touching PR has run since it merged.** Carry.

2. **Defer the `acp.schema` import.** NEW. 476ms of the 1.85s
   `import inspect_ai`, six times the next-largest module, reached through two
   eager edges (`_eval.eval` → `agent._acp.server`, and `util._input.{_types,
   request}` → `ElicitationSchema` for annotations only). `inspect --version`
   costs 2.05s today. Directly measured user-facing win ~0.5s per CLI
   invocation; estimated CI win ~4–6s of leg wall (5 interpreter startups per
   leg plus ~47 subprocess spawn sites in `tests/`, the cluster that owns
   8 of the 15 slowest tests). Product change — outside this skill's safe-fix
   categories. Status: **new, filed as
   [#311](https://github.com/meridianlabs-ai/inspect_ai/issues/311)**.

3. **Unblock the scheduled run.** All three blockers re-probed today, all three
   still hold:
   - *No `workflow` scope* — pushing a branch with a `.github/workflows/build.yml`
     edit to the fork is rejected (`refusing to allow a Personal Access Token to
     create or update workflow .github/workflows/build.yml without workflow
     scope`). Probe branch created and deleted.
   - *No write on upstream* — `POST /repos/UKGovernmentBEIS/inspect_ai/pulls`
     with `head_repo` set as AGENTS.md prescribes returns
     `403 Resource not accessible by personal access token`.
   - *`.claude/**` is not writable in the sandbox* — the edit tool refuses it as
     a protected path, so proposal 5 has now been blocked for three consecutive
     runs. Note `.github/workflows/**` *is* writable in the sandbox; it is only
     the push that fails, which is why the first blocker needs a probe branch to
     detect.

   Consequence: the run's top execution-side items (proposals 1, 2 and 4) are
   all unshippable by this skill, and it has now shipped zero code for four
   consecutive runs. Fix: a classic PAT with `public_repo` + `workflow`, and
   whatever allows `.claude/**` writes. Structural (credentials). Status:
   carried and re-evidenced,
   [#298](https://github.com/meridianlabs-ai/inspect_ai/issues/298) open,
   updated with today's probes.

4. **Collection and startup is ~100s of the ~300s pytest step.** Unchanged
   measurement (139 / 103 / 98s of step time above the busiest worker across
   three legs). The two quantified levers stand: suppressing trio variants at
   collection time (2,670 of 13,324 local items; 36.7s → 31.8s cold collection,
   ~10s of leg wall) and dropping `--doctest-modules` (~1.1s per pass, ~2s of
   leg wall, collects nothing). Proposal 2 attacks the same 100s from a
   different angle and is cheaper to reason about. Neither trio nor doctest is
   an unattended safe fix: the first changes what the suite collects and what
   test IDs exist, the second trades a dormant capability for under 1%. Status:
   carried.

5. **Collector: validate the run window and refetch.** **This is the run where
   it bit.** The first collection came back with a 71h hole inside a 100h window
   (head at 2026-08-21T21:15 while the API's own first page showed runs through
   2026-08-22T16:35) and had to be discarded after ~6 minutes of job fetching;
   the snapshot in this report came from a throwaway bash wrapper that kills and
   retries the collector when it prints its gap warning. The one-file fix is
   written but `.claude/**` is unwritable (proposal 3), so the wrapper cannot be
   committed either. Status: carried, **blocked, now with a demonstrated cost**.

6. **Test-volume policy.** The body of ordinary tests is 55–61% of test time and
   the suite adds ~200 test functions/week, but the sharper number this run is
   the tail: +18s per job in two days, +21s of it from tests newly crossing 1s.
   Growth is lumpy — one new file can beat a week's average. Still a maintainer
   question about what the PR gate should cost, not an arithmetic emergency.
   Structural. Status: carried.

7. **Runner pool size for burst absorption.** No fresh evidence for the third
   consecutive window: median queue 3s in every hour of the day, p90 18s, and
   the four >120s waits are runner-assignment stalls (~303s, single job, all
   siblings at 2–4s), not contention. The structural argument — ~20 job records
   per PR, so a batch of 20 PRs is ~400 queued jobs — is unchanged, and the case
   still rests on the 2026-08-18/19 02:00 UTC bursts (168s median queue in that
   hour). Structural/cost. Status: carried, **evidence continues to age**.

8. **Exclude `design/**` from the `test` job's `code` filter.** Implemented by a
   maintainer in commit `640577ebd` (issue
   [#299](https://github.com/meridianlabs-ai/inspect_ai/issues/299), closed).
   Status: **shipped, unverified — no design-only push has occurred since. This
   report's own PR should be the first.**

9. **Un-serialize `slow-tool-tests-release` from `slow-tool-tests-dev`.**
   Implemented by a maintainer in #4987. Status: **done and verified this run —
   ~12.5 min off the one measured execution, matching the ~13 min estimate.**
   Retained here only to close the loop; drop from the next report.

10. **Real-sleep and near-duplicate test cleanups.**
    `test_eval_set_previous_task_args` spends ~5s of its 6.1s sleeping
    (`sleep_for_3_task` plus a `keyboard_interrupt(2)` alarm that must land
    mid-eval, so shrinking it trades wall clock for flakiness);
    `test_eval_detach_sigterm_terminates_child` holds a deliberate 1.0s grace
    sleep whose comment explains the race it guards; merging
    `test_sample_shuffle`/`test_sample_shuffle_limit` saves ~2.4s. Combined ~7s
    of worker time, under 2s of wall clock at 96–98% efficiency. Status:
    carried, low priority — each candidate was re-read this run and each has a
    documented reason not to be mechanical.

11. **Merge the 4 Viewer jobs into 1–2** — required-check rename. Worth
    revisiting only as burst-load reduction (proposal 7), not wall clock: the
    Viewer path is 71s median. Structural. Status: carried, low.

12. **Policy consistency: docker tests without `@pytest.mark.slow`.** Still six,
    unchanged. The three ungated ones cost 0.05s combined against a live docker
    daemon because they never start a container; the right fix is probably to
    drop `skip_if_no_docker` from those three rather than to mark them slow.
    Zero wall-clock impact either way. Status: carried.

## PRs opened by this skill

See `prs.md`. This run's output (snapshot, report, ledger) goes out as a single
fork PR because upstream PR creation is blocked (proposal 3); no code fix was
shipped, and one new structural proposal was filed as issue
[#311](https://github.com/meridianlabs-ai/inspect_ai/issues/311) on
`meridianlabs-ai/inspect_ai`.
