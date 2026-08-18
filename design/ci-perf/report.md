# CI performance report — 2026-08-18

Data: 200 PR runs, 2026-08-18 00:58 .. 20:47 UTC. Snapshot:
`history/2026-08-18.json`. Previous: 2026-08-12 (200 runs / 20.6h; this
window is 200 runs / 19.8h, so throughput is comparable). Produced by the
unattended scheduled run
([workflow run](https://github.com/meridianlabs-ai/actions/actions/runs/32184876737)).

## Summary

**The PR-gate test job has been running on half the runner.** `pytest -n auto`
resolves to *physical* cores when `psutil` is importable — and `psutil` is a
runtime dependency of `inspect_ai`, so it always is. An `ubuntu-latest` runner
is 4 logical / 2 physical cores, so CI uses 2 xdist workers on a 4-vCPU box.
CI's own `test-report-log.jsonl` artifact confirms it: only `gw0` and `gw1`
appear. Measured locally on an identical runner, `-n logical` cuts the suite
from 449.3s to 333.8s with identical pass/skip/fail counts — roughly **2 minutes off
nearly every PR**, since `test` determined Build wall clock in 41 of 50
successful Build runs this window.

Execution times are otherwise flat (`test` 442 → 445s). Build median wall
clock rose 461 → 485s and p90 534 → 713s, entirely from queue contention
during a 01:00–02:00 UTC push burst (66 runs in two hours; job queue median
163s at 02:00 against 3s for the rest of the day).

The `test` saving that #4848 delivered (−45s of measured test time) was
**completely absorbed by six days of suite growth**: the pytest step is
unchanged at ~415s. Suite size, not the slow tail, is now the structural
problem.

**This run opened no fix PRs, and could not open its report PR upstream
either.** Both prepared fixes modify `.github/workflows/build.yml`, which the
scheduled run's token may not write (`refusing to allow a Personal Access
Token to create or update workflow .github/workflows/build.yml without
workflow scope`; the `gh api` git-data path is rejected too), and the same
token has read-only access to upstream, so creating a PR there returns 403.
The fixes are prepared, validated, and written out below with exact diffs
(proposals 1 and 2); the report PR went to the fork
([meridianlabs-ai/inspect_ai#255](https://github.com/meridianlabs-ai/inspect_ai/pull/255)).
Proposal 3 is the credential fix that unblocks all of it.

## Queue vs execution

Median execution / queue, successful runs. Queue for dependent jobs is
measured from predecessor completion (`needs` map read from the workflow
files).

| Workflow | Job | n | exec med | exec p90 | queue med | queue p90 |
|---|---|---|---|---|---|---|
| Build | slow-tool-tests-dev | 4 | 779s | 926s | 3s | 3s |
| Build | test (per matrix leg) | 100 | 445s | 497s | 3s | 50s |
| Build | docs (when docs change) | 12 | 376s | 394s | 2s | 3s |
| Build | slow-tests | 2 | 224s | 233s | 2s | 3s |
| Build | sandbox-tools-unit | 1 | 176s | — | 2s | 2s |
| Build | mypy (per matrix leg) | 100 | 90s | 95s | 3s | 38s |
| Viewer | viewer-tests | 62 | 60s | 68s | 3s | 68s |
| Viewer | check-schema-and-types | 62 | 54s | 63s | 3s | 22s |
| Build | pre-commit | 50 | 34s | 37s | 3s | 27s |
| Build | check-version-bump | 4 | 31s | 36s | 2s | 3s |
| Build | package | 50 | 30s | 34s | 3s | 64s |
| Viewer | dist-validation | 62 | 28s | 32s | 3s | 54s |
| Build | ruff | 50 | 11s | 14s | 3s | 38s |
| Viewer | submodule-on-main | 62 | 9s | 11s | 3s | 32s |
| Build | changes | 50 | 8s | 9s | 3s | 42s |
| Build | detect-slow | 50 | 8s | 10s | 3s | 79s |
| Changelog Lint | entries-under-unreleased | 45 | 6s | 8s | 3s | 36s |

Workflow wall clock: Build 485s median / 713s p90 (was 461 / 534); Viewer 67s
/ 134s (was 82 / 102); Changelog Lint 10s / 42s.

### Queue is bursty again, not saturated

Across the 897 independent-job samples: median 3s, p75 6s, **p90 60s, p95
169s, max 410s**. 13.7% of jobs waited more than 30s; 56 waited more than
120s. That is not spread evenly — it is one burst:

| Hour (UTC) | runs started | queue med | queue p90 | queue max |
|---|---|---|---|---|
| 00 | 2 | 69s | 103s | 107s |
| 01 | 45 | 3s | 65s | 410s |
| 02 | 21 | 163s | 287s | 324s |
| 03–13 | 3–13/hr | 3s | ≤5s | ≤16s |
| 14 | 15 | 3s | 60s | 61s |
| 15 | 12 | 3s | 70s | 87s |
| 16–20 | 2–17/hr | 3s | ≤35s | ≤35s |

The 2026-08-12 window simply had no comparable burst (p90 14s). Nothing
regressed; the pool is still ~13 jobs/PR wide and still saturates when a batch
of PRs lands together. See proposal 4.

### Critical path

- **Ordinary PR:** `test` is the whole story — it was the last job to finish
  in 41 of 50 successful Build runs (`docs` 3, `mypy` 2). 445s exec against a
  485s Build wall, and inside `test`, 416s is the pytest step (10s install, 5s
  checkout).
- **Sandbox-tools PR:** the long path is
  `detect-slow` → `check-version-bump` → `slow-tool-tests-dev` (779s) →
  `slow-tool-tests-release`, serialized by `needs`. The four longest Build
  runs in the window (805–1105s) all ended on `slow-tool-tests-dev`;
  `slow-tool-tests-release` was skipped in each (it only runs on a version
  bump), so this window does not exercise the full two-suite chain.
- **After proposal 1 lands**, `test` drops to roughly 330s and `docs` (376s)
  becomes the critical path on docs-touching PRs. That promotes proposal 7.

## Slowest tests

Median seconds across 20 CI test jobs, `call` + `setup` + `teardown`
combined. 131 tests captured (`--durations-min=1`), 150s total per job spread
across the (two) xdist workers.

| Median | Test | Classification |
|---|---|---|
| 7.8s | `test_eval_set.py::test_retry_attempt_killed_mid_sweep_leaves_completed_samples_reusable` | new (only in 2 of 20 jobs — landed mid-window); full eval-set retry flow, genuinely heavy |
| 6.7s | `test_eval_set_scanner.py::test_scout_scan_resume_reruns_failed_scans` | genuinely heavy (eval_set + scout scan resume); was 8.8s, now 6.7s |
| 6.6s | `_control/test_launch_handoff.py::test_eval_detach_via_dotenv_detaches_exactly_once` | real CLI subprocess + control-server handshake |
| 6.5s | `_control/test_launch_handoff.py::test_eval_detach_hands_off_and_leaves_eval_running` | (as above) |
| 5.8s | `test_eval_set.py::test_eval_set_previous_task_args` | **real sleeps**: two eval_set passes over `sleep_for_3_task`/`sleep_for_1_task` with a `keyboard_interrupt(2)` timer — ~5s of the 5.8s is sleeping |
| 5.3s | `test_eval_set_scanner.py::test_scanner_resume_...[s3]` | moto S3 + full eval-set resume |
| 4.8s | `_control/test_launch_handoff.py::test_eval_json_redirects_subprocess_stdout_to_stderr` | real CLI subprocess (documented: needs real fds) |
| 4.8s | `agent/test_agent_bridge.py::test_google_bridge_streaming_not_supported` | full `eval()` per test; cost is bridge/SDK import + eval startup |
| 4.8s | `agent/test_agent_bridge.py::test_google_bridge_computer_use_incompatible_model` | (as above) |
| 4.6s | `log/test_eval_log_config.py::test_eval_log_run_config_round_trip` | round-trips a full run config through eval |
| 4.3s | `_control/test_pause.py::test_eval_hard_pause_time_limit_reap_reparks_grader` | real timers inherent to pause/limit semantics |
| 4.2s | `test_sample_limits.py::test_working_limit` | real waits inherent to limit tests |
| 4.0s | `test_sample_shuffle.py::test_sample_shuffle` | two full evals; overlaps `test_sample_shuffle_limit` (2.4s) — same determinism property |
| 3.9s | `_control/test_launch_handoff.py::test_eval_detach_fails_when_control_bind_fails` | real CLI subprocess |
| 3.4s | `test_sample_limits.py::test_solver_timeout_not_scored` | real waits |

The 43s docker `read_file` test from the last report is gone (marked slow in
#4848). No test in the current tail is a policy violation: nothing in the top
30 uses docker or an unmocked external service.

## Suite size

Per matrix leg (from the pytest summary line, 20 CI jobs): **13,245 tests
collected — 9,447 passed, 3,798 skipped**, in 407s median (min 350s, max
511s). The `Test with pytest` step, which also carries collection and the
`-rA` report, is 416s median.

Full per-test data from the `test-report-log.jsonl` artifact of Build run
32184208771 (`test (3.11)`):

- **631s of test-phase time** (call 600s, setup 18s, teardown 12s) across
  **exactly 2 workers**, 315.4s and 315.3s — balanced to within 0.1s and 97%
  busy. Wall for the test phase was 325s; the other ~90s of the step is
  collection and startup.
- **Tail vs body:** 6 tests ≥5s = 37s (5.8% of test time); 122 tests ≥1s =
  243s (38.5%); the remaining **13,123 tests = 388s (61.5%)**. Median test
  1.8ms, mean 48ms.
- **Heaviest files:** `test_eval_set_scanner.py` 47.7s/104 tests,
  `test_eval_set.py` 41.5s/68, `_control/test_eval_set_integration.py`
  36.7s/47, `_control/test_launch_handoff.py` 35.6s/41,
  `test_sample_limits.py` 31.1s/33 — the top 5 files are 192s, 30% of all
  test time.
- **By directory:** `_control` 88.4s (1,115 tests), `agent` 69.7s (2,598),
  `scorer` 50.4s (689), `util` 42.8s (1,883), `model` 38.8s (3,016), `log`
  33.9s (1,011). `model` and `agent` carry the most tests but are cheap
  per test; `_control` is both large and expensive.

### Growth is outrunning per-test fixes

No prior snapshot carries summary data (`pytest_summaries` arrived in #4932),
so the trend comes from the durations tail and the step timing:

| Metric | 2026-08-12 | 2026-08-18 |
|---|---|---|
| Captured ≥1s tail, per job | 194.3s | 149.5s |
| `Test with pytest` step, median | 415s | 416s |

#4848 removed 45s of measured test time and the step did not move. In the same
six days, `tests/` took 106 commits and +4,803 / −646 lines. At that rate the
suite is adding back roughly 20s of wall clock per week (~2.5 min/month) —
which is why the leverage has moved from individual slow tests to worker count
(proposal 1) and to test-volume policy (proposal 5).

### Duplicate-coverage and low-value sampling

Sampled the fastest-growing test files (`tests/_control/*`, 5,681 net lines in
`test_ctl.py` alone over six weeks) plus the two clusters visible in the
durations tail:

- `test_sample_shuffle` (4.0s) and `test_sample_shuffle_limit` (2.4s) assert
  the same property — two evals produce identical sample order for a given
  seed — with and without `limit=20`. Merging them into one parametrized test
  would save ~2.4s of worker time. Judgement-based, so a proposal, not a
  safe fix.
- The `test_launch_handoff.py` cluster (5 tests, 35.6s) each spawns the real
  CLI in a subprocess. Costs are inherent to what they assert (fd/stdout
  behavior, SIGTERM, detached-child lifetime); unchanged verdict from the last
  report.
- The `_control` tests are large but not redundant on inspection — they cover
  distinct lifecycle states.

No exact duplicates found, so no test deletions were eligible as safe fixes
this run.

## Impact verification (previous run's PRs)

**#4848 — partly confirmed, one honest miss.**

| Prediction | Outcome |
|---|---|
| `blob:none` on the Viewer checkout: `check-schema-and-types` 74 → ~50s | **Held.** 54s median; the checkout step is 7s median / 16s max, against 30s median / 216s max before |
| Viewer wall clock | 82 → 67s median |
| Mark the 43s docker `read_file` test slow: −15 to −40s on `test` exec | **Missed.** `test` exec 442 → 445s; the pytest step 415 → 416s. The saving is real and visible in the tail (194 → 150s of captured test time) but was entirely absorbed by six days of new tests |
| Collector hardening (dedupe/sort/gap warning) | Worked as designed for internal gaps — but a *different* stale-page failure hit this run's first collection (see proposal 6) |

The miss is the useful result: at ~2 workers and ~20s/week of test growth, a
one-off 45s tail saving has a half-life of about two weeks.

## Regressions since last report

- **Build p90 wall 534 → 713s.** Queue contention in the 01:00–02:00 UTC
  burst, not execution: every job's exec median is within 3s of last week.
- No individual test grew by more than 1s.
  `test_scout_scan_resume_reruns_failed_scans`, flagged last time at 6.6 →
  8.8s, came back down to 6.7s.

## Waste

- Cancelled superseded runs: 5/200, 19 runner-min (previous: 4/200, 24 min).
- Failed jobs burned 48.6 runner-min, 40.3 of it in `test` (6 failed legs).
- Compute: 1,573 runner-min total (Build 1,404; Viewer 163; Changelog Lint 5),
  up from 1,353 — mostly the sandbox-tools chain: `slow-tool-tests-dev` ran
  11 times this window (10 success, 1 cancelled) against 6 last window, at
  ~13 min each.
- Run conclusions: 157 success, 17 failure, 21 `action_required` (PR-gate
  approval), 5 cancelled.
- Four `fetch-depth: 0` checkouts still fetch the full ~400MB pack:
  `slow-tests` (56s median), `slow-tool-tests-dev` (29s),
  `check-version-bump` (28s), `slow-tool-tests-release` (proposal 2).
- `docs` job: 317s Quarto render, still uncached (proposal 7).
- Documentation-only PRs that aren't markdown run the full suite: the `test`
  job's `code` filter excludes `docs/**` and `**/*.md` but not `design/**`
  (proposal 11).

## Proposals (ranked)

1. **Run pytest on all 4 runner cores (`-n auto` → `-n logical`).** `auto`
   means physical cores whenever psutil is importable, and psutil is a
   runtime dependency, so the PR gate has been using 2 of 4 vCPUs. Measured
   locally on a 4-vCPU / 15GB `ubuntu-latest` runner, same command and
   commit: **449.3s → 333.8s of pytest wall (−26%)**, identical results
   (9,446 passed / 3,799 skipped / 0 failed in both). CPU utilisation goes
   from 1.43 to 2.57 cores busy. The scheduled slow-test suite in
   `meridianlabs-ai/actions` already runs `-n logical`. Expected: `test` exec
   445 → ~330s, Build wall 485 → ~370s. Safe fix, prepared and validated;
   **could not be pushed** (proposal 3). Diff:
   ```diff
   -        run: uv run pytest -rA --doctest-modules --color=yes -n auto --timeout=900 …
   +        run: uv run pytest -rA --doctest-modules --color=yes -n logical --timeout=900 …
   ```
   Risk to weigh: meridianlabs-ai/inspect_ai#232 (silent xdist worker deaths,
   OOM among the hypotheses) is still open, and more workers means more memory.
   Measured: peak summed resident set of the pytest process tree, sampled at
   1Hz, is **5.99GB with 2 workers and 7.29GB with 4** — +22%, not +100%,
   because the peak is set by individual heavy tests rather than by per-worker
   baseline. That is 49% of the runner's 15GB. Timing was reproduced: two
   independent 2-worker runs gave 449.3s and 445.7s.
   Status: new, ready to open.

2. **Finish the `blob:none` rollout** on the last four full-history
   checkouts (`check-version-bump`, `slow-tool-tests-dev`,
   `slow-tool-tests-release`, `slow-tests`). Every other Build checkout moved
   in #4760/#4848 and now takes ~5s; these take 28–56s. Three of them are
   serialized by `needs` on the sandbox-tools path, so this is ~75s off the
   805–1105s runs. Both history-reading steps stay correct under a lazy
   fetch: `git show origin/<base>:…/sandbox_tools_version.txt` pulls one
   blob, and `_check_main_divergence` pulls only the injectable-source blobs
   it diffs. Safe fix, prepared; **could not be pushed** (proposal 3). Diff —
   the same three lines under each of those four `actions/checkout@v7` blocks:
   ```diff
            fetch-depth: 0
            fetch-tags: true
   +        filter: "blob:none"
            submodules: true
   ```
   (`check-version-bump` has no `submodules: true`; the filter goes after
   `fetch-tags` there too.) Status: new, ready to open.

3. **Fix the scheduled run's credentials.** The marvin token is a
   fine-grained PAT and hits two separate walls:
   - *No Workflows permission* — `git push` and the `gh api` git-data path
     both refuse any branch touching `.github/workflows/**`. Every safe fix
     this skill has shipped so far (#4746, #4747, #4760, #4848) would have
     been blocked by this; the two ready fixes above are.
   - *No write on upstream* — its permissions on
     `UKGovernmentBEIS/inspect_ai` are `pull` only, so
     `POST /repos/UKGovernmentBEIS/inspect_ai/pulls` returns
     `403 Resource not accessible by personal access token` even with
     `head_repo` set as AGENTS.md prescribes. Fine-grained PATs cannot be
     scoped to a repository the account doesn't own, so this is a token-type
     problem, not a settings toggle.

   Until both are fixed, an unattended run can push branches to the fork and
   nothing else. This run's report PR was therefore opened against the fork
   ([meridianlabs-ai/inspect_ai#255](https://github.com/meridianlabs-ai/inspect_ai/pull/255)).
   Fix: mint a GitHub App token (or a classic PAT with `repo` + `workflow`)
   for the scheduled workflow. Structural (credentials). Status: new —
   **blocking everything else this skill produces**.

4. **Runner pool size for burst absorption.** Queue is 3s median and 287s
   median inside the 02:00 UTC burst; execution fixes cannot touch that. With
   ~13 jobs fanning out per PR, a batch of 20 PRs is 260 concurrent jobs.
   Options are a larger hosted pool, self-hosted capacity, or fewer jobs per
   PR (proposal 8). Structural/cost. Status: carried, re-evidenced.

5. **Test-volume policy.** The body of ordinary tests is 61.5% of test time
   and growing ~20s/week; per-test fixes now have a two-week half-life. Worth
   a maintainer decision on what the PR gate should cost — e.g. a budget for
   `tests/_control` (88s, the most expensive directory), moving the heaviest
   integration flows (`test_eval_set*`, `test_eval_set_integration`, 126s
   combined) to the scheduled slow suite, or parametrizing the near-duplicate
   pairs noted above. Structural. Status: new.

6. **Collector: detect a stale *head* page, not just internal gaps.** This
   run's first collection produced a snapshot whose newest run was 8.7h older
   than the collection time — the API served page 1 shifted, so the newest
   ~100 runs were silently dropped off the front. `warn_on_time_gap` didn't
   fire because the window was internally contiguous. A second run collected
   cleanly (that is the snapshot analyzed here). Fix: after sorting, compare
   `now - newest_run_start` against the window's own median inter-run gap
   (e.g. `> max(1h, 20× median gap)`), warn and refetch up to 3 times. Not
   applied: `.claude/**` is not writable from the scheduled sandbox. Status:
   new, report-only.

7. **Cache the Quarto render for `docs`** (317s, uncached). Currently below
   `test`'s 445s and therefore off the critical path — but proposal 1 puts
   `test` at ~330s, which makes `docs` the longest Build job on any
   docs-touching PR. Structural. Status: carried, **upgraded**.

8. **Un-serialize `slow-tool-tests-release` from `slow-tool-tests-dev`** —
   release consumes no output from dev (it downloads the published artifact
   and re-runs the same suite), so the `needs` edge is pure ordering. Would
   cut ~13 min off *version-bump* sandbox-tools PRs — the only ones where
   `release` runs at all; it was skipped in all 11 `dev` runs this window,
   which caps how much this is worth. Cost: when dev fails, release burns
   ~14 runner-min instead of being skipped. The sequence is deliberate and
   documented in `design/sandbox-tools-ci-gates.md`. Structural. Status:
   carried.

9. **Merge the 4 Viewer jobs into 1–2** — required-check rename. Worth
   revisiting only as burst-load reduction (proposal 4), not wall clock: the
   Viewer path is 67s median. Structural. Status: carried, downgraded.

10. **Real-sleep and near-duplicate test cleanups** —
    `test_eval_set_previous_task_args` spends ~5s of its 5.8s sleeping
    (`sleep_for_3_task` + a `keyboard_interrupt(2)` timer); merging
    `test_sample_shuffle`/`test_sample_shuffle_limit` saves ~2.4s. Both are
    judgement calls about coverage rather than mechanical fixes, so they are
    proposals, not safe fixes. Combined worth ~7s of worker time. Status:
    new, low priority.

11. **Exclude `design/**` from the `test` job's `code` filter.** The filter
    is `'**'` minus `docs/**` and `**/*.md`, so a documentation-only change
    that isn't markdown counts as code. This report's own PR is the
    demonstration: it changes three files under `design/ci-perf/` (one of
    them a JSON snapshot) and triggers the full 13-job fan-out — both test
    matrix legs included, ~25 runner-minutes to test a data file. Adding
    `'!design/**'` would skip it. Small and mechanical, but it changes what a
    required check covers, so it is a maintainer call rather than a safe fix.
    Status: new.

12. **Policy consistency: 3 docker tests lack `@pytest.mark.slow`** —
    `test_docker_compose_config.py`. They only shell out to `docker compose
    config` and cost <1s each, so there is no measurable win; the convention
    is what enforces the gate. Status: carried, report-only.

## PRs opened by this skill

See `prs.md`. This run opened one PR (this report); the two safe fixes it
prepared are blocked on proposal 3.
