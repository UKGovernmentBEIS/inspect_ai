# CI performance report — 2026-08-19

Data: 200 PR runs, 2026-08-18 02:01 .. 2026-08-19 09:18 UTC (31.3h). Snapshot:
`history/2026-08-19.json`. Previous: 2026-08-18 (200 runs, 19.8h). **The two
windows overlap by ~19h**, so most day-over-day medians are literally the same
runs; trend arrows are weak by construction this time and the load-bearing
comparisons are the before/after splits *inside* this window. Produced by the
unattended scheduled run
([workflow run](https://github.com/meridianlabs-ai/actions/actions/runs/32236499178)).

## Summary

**#4935 landed and delivered.** It merged at 07:42 UTC today, which puts a clean
natural experiment inside this window: 97 `test` legs from branches without it
against 10 with it. Pytest step **417s → 320s** median, job exec **447s → 349s**,
Build wall **485s → 383s** — against predictions of ~330s job and ~370s wall.
Both halves of the PR are confirmed; the `blob:none` half took
`check-version-bump` checkout from 27.5s to 5s and `slow-tool-tests-dev` from
29.5s to 6s.

**Four workers exposed the next bottleneck: xdist's scheduler strands the job on
one worker.** Across the 10 post-#4935 CI legs, the busiest worker ran 12–80s
past the leg's own average, and **4 of 10 legs had a ~76–80s straggler** while
its three peers sat idle. Since a Build run waits for both matrix legs, the
median recoverable wall clock is ~71s — roughly three-quarters of what #4935
itself won. `--dist worksteal` fixes it: across five local full-suite runs
imbalance went from +22s/+83s to +4–7s and worker efficiency from 72–88% to 96%,
with identical results every time. That is this run's one fix PR (proposal 1).

**`docs` is now the longest Build job** (378s against `test`'s 349s), exactly the
promotion last report predicted. Quarto caching moves from a nice-to-have to the
top execution-side item after worksteal.

**Neither PR this run prepared could be opened upstream.** Three separate
mechanical blockers, all re-verified today with exact errors (proposal 2): the
token cannot push `.github/workflows/**`, cannot create a PR on upstream, and the
sandbox cannot write `.claude/**` — which is where the collector fix this run
needed lives. Both PRs went to the fork, based on upstream `main` and ready to
re-open there unchanged.

## Data-quality note (read before trusting any trend)

Two things about this window:

1. **The runs API served stale pages repeatedly.** The committed collector's
   first attempt produced a snapshot spanning *2026-06-12 to 2026-08-17* —
   a 1475h hole, with a head 36h older than collection time. Direct probing
   confirmed the cause: 1 request in ~5 to
   `actions/runs?event=pull_request&status=completed&page=1` returns a replica
   ~31h behind, and one page in the bad set carried June runs. The snapshot
   analyzed here was collected with the retry/validation fix from proposal 4
   applied (head 6 minutes stale; largest internal gap 3.8h, matching two
   genuine overnight lulls at 03:57–07:45 and 03:36–07:15 UTC).
2. **Per-test durations are no longer comparable with pre-#4935 snapshots.**
   Four workers on two physical cores means each test runs slower in wall terms:
   total test-phase work went from 631s (2 workers) to 716–793s (4 workers),
   +13–25% for the same tests. The captured ≥1s tail "grew" 149.5s → 156.0s
   purely from this. **Only wall clock is comparable across the cutover** —
   future runs should not read the duration inflation as a regression.

## Queue vs execution

Median execution / queue over successful jobs. Queue for dependent jobs is
measured from predecessor completion (`needs` map read from the workflow files).
`test` mixes pre- and post-#4935 legs; see the split below it.

| Workflow | Job | n | exec med | exec p90 | queue med | queue p90 |
|---|---|---|---|---|---|---|
| Build | slow-tool-tests-dev | 8 | 779s | 987s | 3s | 3s |
| Build | test (per matrix leg) | 113 | 444s | 493s | 3s | 35s |
| Build | docs (when docs change) | 12 | 378s | 414s | 2s | 3s |
| Build | slow-tests | 2 | 224s | 235s | 2s | 3s |
| Build | sandbox-tools-unit | 1 | 176s | — | 2s | 2s |
| Build | mypy (per matrix leg) | 120 | 89s | 95s | 3s | 40s |
| Viewer | viewer-tests | 61 | 62s | 68s | 3s | 14s |
| Viewer | check-schema-and-types | 62 | 54s | 63s | 3s | 9s |
| Build | pre-commit | 61 | 34s | 39s | 3s | 33s |
| Build | package | 62 | 30s | 34s | 3s | 35s |
| Build | check-version-bump | 8 | 30s | 37s | 2s | 50s |
| Viewer | dist-validation | 63 | 28s | 33s | 3s | 12s |
| Build | ruff | 62 | 11s | 14s | 3s | 20s |
| Viewer | submodule-on-main | 61 | 9s | 11s | 3s | 14s |
| Build | detect-slow | 63 | 9s | 10s | 3s | 35s |
| Build | changes | 63 | 8s | 9s | 3s | 52s |
| Changelog Lint | entries-under-unreleased | 38 | 6s | 8s | 3s | 9s |

Workflow wall clock: Build 484s median / 805s p90 (was 485 / 805); Viewer 67s /
85s (was 67 / 137); Changelog Lint 10s / 17s (was 10 / 50). The Viewer and
Changelog p90 improvements are queue, not execution — this window has a milder
burst profile than the last one.

### #4935 before/after, inside this window

Legs classified by whether the branch contained the fix (merged 07:42:45 UTC;
the `ci-perf/report-2026-08-18` branch counts as "with", it *is* #4935's branch).

| Metric | Without #4935 | With #4935 | Predicted |
|---|---|---|---|
| `Test with pytest` step | 417s (n=97, 358–522) | **320s** (n=10, 296–373) | — |
| `test` job exec | 447s | **349s** | ~330s |
| Build wall clock | 485s (n=48) | **383s** (n=5) | ~370s |
| `check-version-bump` checkout | 27.5s | **5s** (n=1) | ~5s |
| `slow-tool-tests-dev` checkout | 29.5s | **6s** (n=1) | ~5s |

`slow-tests` (56s checkout) and `slow-tool-tests-release` didn't run on any
post-merge PR, so those two legs of the `blob:none` rollout stay unverified until
the next report.

### Queue is calmer, but the 02:00 UTC burst is unchanged

Across 871 independent-job samples: median 3s, p75 5s, **p90 28s, p95 61s, max
313s**. 85 jobs waited more than 30s, 31 more than 120s (previous window: p90
61s, p95 171s, max 410s; 123 and 56). The improvement is entirely that this
window contains one burst instead of two:

| Hour (UTC) | runs started | queue med | queue p90 | queue max |
|---|---|---|---|---|
| 01 | 8 | 12s | 44s | 55s |
| 02 | 16 | **168s** | 285s | 313s |
| 03–13 | 3–21/hr | 3s | ≤24s | ≤59s |
| 14 | 15 | 3s | 60s | 61s |
| 15 | 12 | 3s | 71s | 87s |
| 16–23 | 2–17/hr | 3s | ≤35s | ≤35s |

The 02:00 hour is the same pattern reported last time: a batch of PRs lands
together and ~13 jobs per PR saturate the pool. Nothing regressed and nothing
improved structurally — see proposal 5.

### Critical path

- **Ordinary PR:** still `test`, last to finish in 44 of 53 successful Build
  runs. But post-#4935 the margin is thin: `test` 349s against `docs` 378s.
- **Docs-touching PR:** `docs` now determines wall clock. Its 378s is 317s of
  uncached `quarto render` plus 48s of dependency install.
- **Sandbox-tools PR:** unchanged — `detect-slow` → `check-version-bump` →
  `slow-tool-tests-dev` (779s) → `slow-tool-tests-release`, serialized by
  `needs`. The 805–1105s tail of Build runs is all this chain.

## The four-worker straggler

`test` gets 4 xdist workers since #4935. From the `test-report-log.jsonl`
artifacts of all five post-merge Build runs (10 legs, 13,245–13,250 tests each):

| Run | Leg | worker busy times | max | leg avg | imbalance | test-phase wall |
|---|---|---|---|---|---|---|
| 32229091541 | 3.10 | 161 / **266** / 155 / 163 | 266s | 186s | **+80s** | 271s |
| 32229091541 | 3.11 | 182 / 182 / 181 / 213 | 213s | 189s | +23s | 218s |
| 32229392189 | 3.10 | 153 / **256** / 151 / 156 | 256s | 179s | **+77s** | 261s |
| 32229392189 | 3.11 | 171 / 175 / 200 / 212 | 212s | 190s | +23s | 219s |
| 32232439402 | 3.10 | 180 / 212 / 178 / 179 | 212s | 187s | +25s | 218s |
| 32232439402 | 3.11 | 222 / 175 / 220 / 175 | 222s | 198s | +24s | 224s |
| 32232447154 | 3.10 | 204 / 185 / 189 / 189 | 204s | 192s | +12s | 211s |
| 32232447154 | 3.11 | 146 / 149 / 145 / **248** | 248s | 172s | **+76s** | 254s |
| 32232453887 | 3.10 | 174 / 155 / **259** / 145 | 259s | 183s | **+76s** | 265s |
| 32232453887 | 3.11 | 184 / 204 / 194 / 188 | 204s | 192s | +12s | 209s |

Mechanism: xdist's default `--dist load` hands each worker a large contiguous
slice of the collection up front, and collection is file-ordered, so a file's
tests stay together and cost clusters travel as a unit. The straggler in
32229091541/3.10 was one worker holding `test_eval_set.py` (49s) *and*
`test_sample_limits.py` (32s) *and* `test_cancellation_logging.py` (10s), while
the worker that finished 111s earlier had picked up the cheap
`agent/deepagent` and `model` directories.

A Build run waits for the slower of its two legs, so per run the recoverable
wall clock is `max(leg wall) − leg avg`: **81s, 71s, 26s, 62s, 73s** across the
five runs, median 71s.

### Local A/B: `--dist worksteal` removes the straggler

Same command as CI on an identical runner (4 logical / 2 physical vCPU, 15GB,
xdist 3.8.0), full suite, identical results in all five runs (9,446 passed /
3,799 skipped / 0 failed):

| Arm | worker busy times | max | leg avg | imbalance | test-phase wall | worker efficiency |
|---|---|---|---|---|---|---|
| `load`, run 1 | 200 / 202 / 243 / 240 | 243s | 221s | +22s (+10%) | 251s | 88% |
| `load`, run 2 | 196 / **305** / 193 / 195 | 305s | 222s | **+83s (+37%)** | 310s | 72% |
| `worksteal`, run 1 | 230 / 216 / 222 / 232 | 232s | 225s | +7s (+3%) | 234s | **96%** |
| `worksteal`, run 2 | 233 / 225 / 224 / 236 | 236s | 229s | +7s (+3%) | 239s | **96%** |
| `worksteal`, run 3 (via `addopts`) | 239 / 234 / 233 / 240 | 240s | 236s | +4s (+2%) | 247s | **96%** |

The second `load` run reproduced the CI straggler exactly — one worker at 305s
while the other three finished in ~195s — and all three worksteal runs held at
+4–7s and 96% worker efficiency.

Total pytest wall was 328s / 451s for `load` and 342s / 380s / 356s for
`worksteal`, but this box's fixed overhead (collection plus worker startup)
wandered between 77s and 141s across the five runs, so **total wall is too noisy
here to quote; imbalance and worker efficiency are the run-internal metrics that
survive that noise**. The expected CI effect is therefore the 71s median of
recoverable Build wall clock from the table above, and the next report will
measure it with the same before/after split that validated #4935.

Three full-suite runs under a completely different test-to-worker assignment, all
green with identical counts, is also the best available evidence against the
order-dependence risk noted in proposal 1.

### CI A/B (one run per arm)

The two PRs this run opened are the same base commit differing only in the flag,
so their Build runs are a real CI A/B — #261 carries `worksteal`, #262 (this
report) carries `load`:

| PR | Arm | Leg | worker busy times | imbalance | worker efficiency | test-phase wall | pytest step |
|---|---|---|---|---|---|---|---|
| #261 | `worksteal` | 3.10 | 161 / 152 / 160 / 154 | **+4s (+3%)** | **95%** | 165s | 260s |
| #261 | `worksteal` | 3.11 | 190 / 183 / 191 / 192 | **+3s (+2%)** | **95%** | 199s | 401s |
| #262 | `load` | 3.10 | 203 / 169 / 167 / 178 | +24s (+13%) | 86% | 209s | 314s |
| #262 | `load` | 3.11 | 160 / 160 / **266** / 156 | **+80s (+43%)** | 68% | 271s | 365s |

The straggler reproduced on #262's 3.11 leg — one worker at 266s against 156–160s
— and both worksteal legs came in at +3–4s and 95% efficiency. Comparing what a
Build run actually waits for, the slower of its two legs: 199s of test-phase wall
under worksteal against 271s under load, a **72s difference** that lands almost
exactly on the 71s median predicted from the ten-leg table above.

Two honest caveats. It is one run per arm on different runners, and the work
totals differ (627–755s vs 718–741s), so the *absolute* seconds are not directly
comparable — worker efficiency is. And #261's 3.11 leg had the longest pytest
step of the four (401s) despite the best balance, because that leg spent 202s
outside the test phase against 94–105s for the others: unrelated runner variance
in install and collection, and a reminder that the ~99s of fixed overhead
(proposal 8) has a long tail of its own.

## Slowest tests

Median seconds across 20 CI test jobs, `call` + `setup` + `teardown` combined.
147 tests captured (`--durations-min=1`), 156.0s total per job — spread across 2
workers for most of the window and 4 for the newest legs, so **these numbers are
inflated ~15–25% relative to the last report by CPU contention, not by the tests
getting slower** (see the data-quality note).

| Median | Test | Classification |
|---|---|---|
| 7.2s | `test_eval_set_scanner.py::test_scout_scan_resume_reruns_failed_scans` | genuinely heavy (eval_set + scout scan resume) |
| 6.7s | `_control/test_launch_handoff.py::test_eval_detach_via_dotenv_detaches_exactly_once` | real CLI subprocess + control-server handshake |
| 6.7s | `_control/test_launch_handoff.py::test_eval_detach_hands_off_and_leaves_eval_running` | (as above) |
| 6.1s | `test_eval_set_scanner.py::test_scanner_resume_...[s3]` | moto S3 + full eval-set resume |
| 6.0s | `test_eval_set.py::test_eval_set_previous_task_args` | **real sleeps**: ~5s of it is `sleep_for_3_task` plus a `keyboard_interrupt(2)` timer |
| 5.4s | `agent/test_agent_bridge.py::test_google_bridge_streaming_not_supported` | full `eval()` per test; cost is bridge/SDK import + eval startup |
| 5.3s | `agent/test_agent_bridge.py::test_google_bridge_computer_use_incompatible_model` | (as above) |
| 5.1s | `_control/test_launch_handoff.py::test_eval_json_redirects_subprocess_stdout_to_stderr` | real CLI subprocess (documented: needs real fds) |
| 5.0s | `log/test_eval_log_config.py::test_eval_log_run_config_round_trip` | round-trips a full run config through eval |
| 4.5s | `_control/test_launch_handoff.py::test_eval_detach_fails_when_control_bind_fails` | real CLI subprocess |
| 4.3s | `_control/test_pause.py::test_eval_hard_pause_time_limit_reap_reparks_grader` | real timers inherent to pause/limit semantics |
| 4.3s | `test_sample_limits.py::test_working_limit` | real waits inherent to limit tests |
| 4.1s | `test_retry.py::test_eval_retryable` | new this window (n=1 job); retry flow |
| 3.8s | `test_sample_shuffle.py::test_sample_shuffle` | two full evals; overlaps `test_sample_shuffle_limit` |
| 3.4s | `test_sample_limits.py::test_solver_timeout_not_scored` | real waits |

No test in the tail is a slow-policy violation: nothing in the top 30 uses
docker or an unmocked external service. Standing docker-trap sweep found two
new unmarked docker tests (`tools/test_think_tool.py`) — both sit behind
`@skip_if_no_anthropic` and skip in 1ms in the PR gate, so it is a convention
gap with no wall-clock cost (proposal 12).

## Suite size

Per matrix leg (pytest summary line, 20 CI jobs): **13,247 tests collected —
9,449 passed, 3,798 skipped**, in 393s median (min 302s, max 481s; the spread is
the 2-worker/4-worker cutover plus the straggler). Collected locally at
`origin/main`: 13,245.

From the report-log artifacts of the merge run (4 workers, both legs):

- **Test-phase work 745s (3.10) / 758s (3.11)**, of which call 699/716s, setup
  29/27s, teardown 17/14s.
- **Tail vs body:** 10–11 tests ≥5s = 75–76s (~10%); 137–149 tests ≥1s =
  295–323s (~40%); the remaining **~13,100 tests = 435–450s (57–60%)**. Median
  test 2.3–3.2ms, mean 56–57ms.
- **Heaviest files:** `test_eval_set_scanner.py` 54–57s/104 tests,
  `test_eval_set.py` 48–49s/68, `_control/test_launch_handoff.py` 45–47s/41,
  `_control/test_eval_set_integration.py` 29–48s/47, `test_sample_limits.py`
  32–34s/33.
- **By directory:** root 234–243s (518 tests), `_control` 95–117s (1,115),
  `scorer` 59–61s (689), `log` 45–47s (1,011), `util` 44s (1,368), `model`
  37–42s (1,542), `agent` 37–40s (544).
- **Collection and startup is ~99s of the 320s step** (step 320s median against
  a 221s median test-phase wall). Single-process `--collect-only` is 32s cold,
  and xdist pays it once on the controller plus once per worker. That is now ~31%
  of the step — proposal 8, where the `--doctest-modules` hypothesis is measured
  and ruled out.

### Growth

Source-level test functions at `origin/main`, by date:

| Date | `def test_` in `tests/` | Δ |
|---|---|---|
| 2026-08-04 | 7,208 | — |
| 2026-08-12 | 7,474 | +266 (8d) |
| 2026-08-18 | 7,723 | +249 (6d) |
| 2026-08-19 | 7,723 | 0 |

So ~+250 test functions/week, ~+3.3%/week, expanding to ~+430 collected items
via parametrize and the anyio backends. Last report's indirect estimate — the
pytest step stayed at ~415s across six days *despite* #4848 removing 45s of
measured test work — implies about +22s of 2-worker wall clock per 6 days, i.e.
**~+26s/week at 2 workers, ~+13s/week at 4**. At that rate #4935's 97s buys
roughly two months before growth absorbs it, against the two-week half-life the
previous tail fix had. Worker count bought time that per-test fixes could not.

### Duplicate-coverage and low-value sampling

Sampled the fastest-growing test files this week by line count, then priced each
from the report log:

| File | Lines added since 08-12 | Test-phase cost |
|---|---|---|
| `_control/test_ctl.py` | +2,176 | **1.2s** |
| `_eval/task/test_input_media.py` | +950 | 7.0s |
| `_control/test_limits.py` | +676 | 3.2s |
| `_control/test_pause.py` | +631 | 10.4s |
| `util/test_media_resolver.py` | +496 | 0.3s |
| `model/test_inline_media_serialization.py` | +326 | 0.6s |

**Line growth is not time growth.** The single fastest-growing test file in the
repo costs 1.2s across 100+ tests — these are cheap unit tests, which is the
pattern you want. That materially de-escalates last report's test-volume concern
(proposal 6): the body of the suite is 57–60% of test time, but what is being
added to it is inexpensive.

Findings carried forward unchanged: `test_sample_shuffle` (3.8s) and
`test_sample_shuffle_limit` (2.4s) assert the same seeded-order property with
and without `limit=20` and could be one parametrized test (~2.4s); the
`test_launch_handoff.py` cluster (5 tests, 45s) each spawns the real CLI and the
cost is inherent to what it asserts. No exact duplicates found, so no test
deletion was eligible as a safe fix.

## Regressions since last report

- **None in execution.** Every job's exec median is within 2s of last window
  except `test`, which improved.
- No individual test grew after correcting for the 4-worker inflation.
- `action_required` runs rose 21 → 33 of 200 (PR-gate approval waits). This is
  contributor mix, not CI, but it is worth knowing that a sixth of runs now
  start with a human gate.

## Waste

- Cancelled superseded runs: 7/200, 28.2 runner-min (previous: 5/200, 19.0).
- Failed jobs burned 28.0 runner-min, 25.6 of it in `test` (previous: 48.6 /
  40.3).
- Compute: **1,489 runner-min** total (Build 1,325; Viewer 160; Changelog Lint
  4), down from 1,573 — `-n logical` shortens the job, so more parallelism cost
  *less* compute, and `slow-tool-tests-dev` ran 8 times against 11.
- Run conclusions: 150 success, 33 `action_required`, 10 failure, 7 cancelled.
- `docs`: 317s Quarto render, still uncached (proposal 3).
- Documentation-only PRs that aren't markdown still run the full suite: the
  `test` job's `code` filter excludes `docs/**` and `**/*.md` but not
  `design/**` (proposal 9). This report's own PR demonstrates it again.

## Impact verification (previous run's PRs)

**#4935 — confirmed, both halves.** The first time a ci-perf prediction has been
this close.

| Prediction | Outcome |
|---|---|
| `-n logical`: `test` exec 445 → ~330s | **Held.** 447 → 349s (−98s) |
| Build wall 485 → ~370s | **Held.** 485 → 383s (−102s) |
| `blob:none` on the last 4 checkouts: ~75s off the sandbox-tools chain | **Partly verified.** `check-version-bump` 27.5 → 5s, `slow-tool-tests-dev` 29.5 → 6s (−46s on the two that ran); `slow-tests` and `slow-tool-tests-release` didn't run post-merge |
| Memory risk at 4 workers (7.29GB of 15GB predicted peak) | No OOM, no worker deaths in 10 post-merge legs; all 4 workers reported in every leg |

The one thing the prediction missed was second-order: 4 workers made xdist's
scheduling imbalance the new long pole, which nothing in the previous analysis
anticipated.

## Proposals (ranked)

1. **`--dist worksteal` for the distributed test run.** Measured problem: 4 of 10
   post-#4935 CI legs stranded 76–80s of work on one worker while three sat idle;
   median recoverable Build wall clock across the five runs is **71s**. Fix
   validated locally over five full-suite runs, all with identical results:
   imbalance +22s/+83s under `load` against +4s/+7s/+7s under `worksteal`, worker
   efficiency 72–88% against 96%.

   Added to `addopts` in `pyproject.toml` rather than to the workflow step, so it
   also covers the scheduled slow-test suite (which passes `-n logical` too) and
   local `-n` runs; `--dist` is inert without `-n`, verified. The other candidate
   home is beside `-n logical` in `build.yml`, which this run could not write
   (proposal 2) — the PR says so explicitly and invites a maintainer to move it.

   Risk to weigh: changing the distribution algorithm reshuffles which tests
   share a worker, and this suite has a history of order-dependent flakiness
   (meridianlabs-ai/inspect_ai#247, #250). `load` is already nondeterministic, so
   this changes the distribution of co-location rather than introducing it; three
   full-suite runs under a completely different assignment came back green with
   identical counts. Status: **PR opened** —
   [meridianlabs-ai/inspect_ai#261](https://github.com/meridianlabs-ai/inspect_ai/pull/261)
   on the fork, ready to open upstream unchanged.

2. **Unblock the scheduled run.** Three independent mechanical blockers, each
   re-verified today:
   - *No `workflow` scope* — `git push` of any branch touching
     `.github/workflows/**` is rejected: `refusing to allow a Personal Access
     Token to create or update workflow .github/workflows/build.yml without
     workflow scope`. Every safe fix this skill has shipped (#4746, #4747,
     #4760, #4848, #4935) would have been blocked by this, and it forced
     proposal 1 into `pyproject.toml` rather than beside `-n logical`.
   - *No write on upstream* — `POST /repos/UKGovernmentBEIS/inspect_ai/pulls`
     returns `403 Resource not accessible by personal access token` even with
     `head_repo` set as AGENTS.md prescribes (probed with a deliberately invalid
     head: a permissions failure, not a validation one). Fine-grained PATs
     cannot be scoped to a repo the account doesn't own.
   - *`.claude/**` is not writable from the sandbox* — new this run, and it bit:
     the collector fix in proposal 4 is the change this run most needed, was
     written and validated, and could not be committed. This one is a harness
     permission, not a token scope.

   Fix: a classic PAT with `public_repo` + `workflow` for the workflow, and
   whatever allows `.claude/**` writes in the scheduled sandbox. Until then an
   unattended run can push branches touching everything *except* workflows and
   `.claude/`, and can open PRs only on the fork. Structural (credentials).
   Status: carried from last report's proposal 3, re-evidenced, **now the
   binding constraint on this skill's output**.

3. **Cache the Quarto render for `docs`.** 317s of the job's 378s, uncached, and
   `docs` is now the longest Build job (`test` is 349s post-#4935). Every
   docs-touching PR pays it in full. Structural. Status: carried (was proposal
   7), **promotion realized exactly as predicted — now the top execution-side
   item after proposal 1**.

4. **Collector: validate the run window and refetch.** This run lost a full
   collection cycle to a stale API replica: the committed collector emitted its
   gap warning and then wrote the snapshot anyway, spanning 2026-06-12 to
   2026-08-17. Probing showed ~1 in 5 requests to page 1 returns a ~31h-stale
   replica. The fix, written and used for this run's snapshot: split the fetch
   into `fetch_runs_once`, add a `window_problem()` check for both a stale head
   (`now − newest_run_start`) and an internal gap, retry up to N times, and fall
   back to the freshest candidate with a loud warning. Refetching costs 2 API
   calls against the ~200 the job pass costs, so retrying is nearly free.
   One correction from using it: scale the *head-staleness* tolerance to the
   window's own run cadence (`max(1h, 20 × median inter-run gap)`) but keep the
   existing fixed 12h threshold for internal gaps — the cadence-scaled tolerance
   came out at 3.1h and flagged two genuine overnight lulls (3.8h, 3.65h).
   Status: carried (was proposal 6), **upgraded to urgent** — unshippable only
   because of the `.claude/**` blocker in proposal 2.

5. **Runner pool size for burst absorption.** Queue is 3s median overall and
   168s median inside the 02:00 UTC hour; p90 improved 61s → 28s only because
   this window has one burst instead of two. With ~13 jobs per PR, a batch of 20
   PRs is 260 concurrent jobs. Options: larger hosted pool, self-hosted
   capacity, or fewer jobs per PR (proposal 11). Structural/cost. Status:
   carried, re-evidenced.

6. **Test-volume policy.** The body of ordinary tests is 57–60% of test time and
   the suite adds ~250 test functions/week. But this run priced the
   fastest-growing files and found them cheap (`_control/test_ctl.py`: +2,176
   lines, 1.2s), and at 4 workers growth costs ~13s of wall clock per week
   against #4935's 97s saving. Still worth a maintainer view on what the PR gate
   should cost, but the urgency is lower than last report implied. Structural.
   Status: carried, **downgraded**.

7. **Real-sleep and near-duplicate test cleanups.**
   `test_eval_set_previous_task_args` spends ~5s of its 6.0s sleeping
   (`sleep_for_3_task` plus a `keyboard_interrupt(2)` alarm, where the interrupt
   must land mid-eval — so shrinking the sleeps trades wall clock for flakiness
   risk); merging `test_sample_shuffle`/`test_sample_shuffle_limit` saves ~2.4s.
   Both are coverage judgements rather than mechanical fixes. Combined worth ~7s
   of worker time, which after worksteal is ~2s of wall clock. Status: carried,
   low priority.

8. **Collection is ~31% of the pytest step.** The step is 320s median against a
   221s test-phase wall, so ~99s is collection, worker startup and reporting —
   and collection (32s single-process cold, 12s with warm bytecode caches; CI is
   always cold) is paid once on the controller plus once per worker. That is now
   a bigger slice than the entire ≥5s slow tail (75s of *work*, ~19s of wall),
   and worksteal does not touch it. Worth an investigation before more per-test
   work.

   One hypothesis measured and closed this run: **`--doctest-modules` collects
   nothing.** 13,245 items collected with it and 13,245 without — `testpaths =
   ["tests"]` confines collection to `tests/`, which contains no doctests — so it
   costs ~1s and is not the source of the overhead. Two side notes from that
   check: the flag is dead weight in both `addopts` and the CI command, and the
   4 doctests that do exist in `src/inspect_ai` (`_util/format.py`,
   `_util/file.py`, `_util/_json_rpc.py`, `model/_providers/_vllm_lora.py`) are
   never executed by the PR gate. Collecting `src` directly is not a drop-in fix:
   it errors on 84 modules under direct-module collection. Structural. Status:
   new.

9. **Exclude `design/**` from the `test` job's `code` filter.** The filter is
   `'**'` minus `docs/**` and `**/*.md`, so a documentation-only change that
   isn't markdown counts as code. This report's own PR is the demonstration:
   three files under `design/ci-perf/` (one a JSON snapshot) trigger the full
   13-job fan-out, ~25 runner-minutes to test a data file. Adding `'!design/**'`
   is one line, but it changes what a required check covers, so it is a
   maintainer call. Status: carried.

10. **Un-serialize `slow-tool-tests-release` from `slow-tool-tests-dev`** —
    release consumes no output from dev (it downloads the published artifact and
    re-runs the same suite), so the `needs` edge is pure ordering. Would cut ~13
    min off *version-bump* sandbox-tools PRs — the only ones where `release` runs
    at all, and it ran on none this window (63 skipped, 1 cancelled, 0 executed,
    against 8 successful `dev` runs), which continues to cap how much this is
    worth. Cost: when dev fails, release burns ~14 runner-min instead of being
    skipped. The sequence is deliberate and documented in
    `design/sandbox-tools-ci-gates.md`. Structural. Status: carried.

11. **Merge the 4 Viewer jobs into 1–2** — required-check rename. Worth
    revisiting only as burst-load reduction (proposal 5), not wall clock: the
    Viewer path is 67s median. Structural. Status: carried, low.

12. **Policy consistency: docker tests without `@pytest.mark.slow`.**
    `util/sandbox/test_docker_compose_config.py` (3, carried) and now
    `tools/test_think_tool.py` (2, new). All five sit behind another skip gate
    and cost ~1ms each in the PR gate, so there is no measurable win; the
    convention is what enforces the gate. Status: carried, extended.

## PRs opened by this skill

See `prs.md`. This run opened one fix PR
([#261](https://github.com/meridianlabs-ai/inspect_ai/pull/261), proposal 1) and
this report PR, both on the fork because upstream PR creation is blocked
(proposal 2).
