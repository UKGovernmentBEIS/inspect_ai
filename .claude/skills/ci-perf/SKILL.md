---
name: ci-perf
description: Assess and improve CI performance for pull requests in this repo. Use whenever the user asks about CI speed, slow CI, how long checks take, queue/runner wait, slow or duplicate tests, CI cost, or asks to run the recurring CI performance report (/ci-perf). Also use when asked to make PR feedback faster or to review workflow efficiency.
---

# CI performance analysis and improvement

Recurring analysis of PR CI: measure where wall-clock time goes, track it
over time, and turn findings into concrete fixes. Runs two ways — manually
in an interactive session, and unattended every ~2 days via the scheduled
workflow in `meridianlabs-ai/actions` (`inspect-ai-ci-perf.yml`); see
"Scheduled (unattended) mode" below for how the rules differ. Each run is
self-contained.

## Objective and ground rules

- **Primary metric: PR wall-clock** — push to all-checks-green. That is
  what contributors feel. Total runner compute-minutes is tracked as a
  secondary metric (it drives queue contention and cost).
- **Queue time and execution time are separate numbers.** Runner-pool
  saturation has historically dominated wall clock here (batches of PRs
  land together; ~13 jobs fan out per PR). Never propose a test speedup to
  fix what is actually queue contention.
- **Two output buckets:**
  - *Safe fixes* — small, low-risk changes the skill prepares as PRs
    (see the fix phase for the category list).
  - *Structural proposals* — anything touching required-check names, job
    topology, or policy. Never a PR from this skill: they rank in the
    report, and ripe ones are filed as issues for a maintainer decision
    (see the fix phase).
- **Never propose trimming the Python version matrix** (e.g. PRs testing
  only 3.11). Explicitly ruled out.
- **Interactive runs: always ask before pushing.** Prepare branch + diff +
  PR body, show the user, push only on their OK. Unattended runs can't ask —
  see "Scheduled (unattended) mode" for what they may push.
- **One PR per run, not per fix.** Every PR costs a full review/approval
  ritual, so combine everything a run produces — snapshot, report, prs.md
  update, and all of the run's safe fixes — into a single PR, one commit
  per logical change. Do not split the run's output across PRs.
  Follow AGENTS.md PR rules (CI-only changes need no CHANGELOG entry;
  test-content changes are product-adjacent — judge per AGENTS.md).

## Phase 1 — Collect

Run the bundled collector (venv active; `gh` must be authenticated):

```bash
python .claude/skills/ci-perf/scripts/collect_ci_data.py \
  --out design/ci-perf/history/$(date +%F).json
```

It snapshots the last ~200 completed PR workflow runs with per-job
timings (execution seconds, wait-from-run-start) and mines recent Build
test-job logs for pytest `--durations` blocks and the final summary line
(total test counts + pytest wall, for suite-size trends).

- If `pytest_durations` comes back empty, CI likely doesn't pass
  `--durations` yet — proposing that one-line workflow change is the
  standing first safe fix.
- If a snapshot for today already exists, overwrite it (re-runs same day
  are fine); history keeps one file per day.

## Repo slow-test policy (context for analysis and fixes)

- **Definition:** any test that uses docker or hits a real (unmocked)
  external service is by definition slow and must carry
  `@pytest.mark.slow`. A fully-mocked test may also be marked slow when
  its cost is inherent (e.g. crossing the S3 1000-key page boundary means
  1001+ real HTTP PUTs to the in-process moto server) — say why in the
  test's docstring.
- **Where slow tests run:** they are skipped in the PR-gate `test` jobs
  (no `--runslow`) and run every ~2 hours by the scheduled suite in
  `meridianlabs-ai/actions` (`inspect-ai-scheduled-tests.yml`, runner
  label `slow_test_runner`, `pytest --runslow --runapi`). Marking a test
  slow moves its coverage there — it does not delete it. Prefer the PR
  gate for regression guards on core logic when the test can be made
  cheap; prefer slow for anything matching the definition above.
- **The docker trap:** docker is preinstalled and running on GitHub
  `ubuntu-latest`, so nothing technically stops a docker test running in
  the PR gate — `skip_if_no_docker` does not skip in CI. The slow mark is
  the only enforcement, by convention: `@skip_if_no_docker` and
  `@pytest.mark.slow` belong together. When durations data shows a
  multi-second test, check for this pairing violation first (two found so
  far: the 38s sandbox-init test, fixed in #4760, and
  `test_docker_read_file.py` at 42s of fixture setup). Aggregate `setup`
  and `teardown` phases as well as `call` — fixture-heavy offenders hide
  outside `call`.

## Phase 2 — Analyze

Read the fresh snapshot plus the previous few in `design/ci-perf/history/`
(trend needs at least one prior; on the first run, report absolute numbers
only). Compute:

1. **Queue vs execution split.** `wait_from_run_start_seconds` is true
   queue time only for jobs without `needs`; for dependent jobs, subtract
   the predecessor's `completed_at` first. Get the dependency map by
   reading `.github/workflows/*.yml` (`needs:` keys) — don't hardcode it;
   workflows change.
2. **Critical path per workflow.** Which chain of jobs determines wall
   clock, and how much of it is waiting? (Historically: `changes` → `test`
   serialization in build.yml put a full queue+start cycle in front of the
   longest job.)
3. **Trends and regressions.** Median/p90 wall clock per workflow vs prior
   snapshots; tests newly appearing in the slowest list or significantly
   slower than before.
4. **Slowest tests** from `pytest_durations` (aggregate across runs;
   median per test). For top offenders, read the test source and classify:
   genuinely heavy, real sleeps/timers that a mock clock or event would
   remove, duplicate coverage, or a candidate for `@pytest.mark.slow`.
5. **Waste.** Cancelled superseded runs and how long they held runners
   before dying; jobs whose checkout/setup overhead exceeds their useful
   work; unconditional `fetch-depth: 0` where history/tags are unused;
   cache effectiveness.
6. **Step-level breakdown of the heavy jobs — always at p90, not just
   median.** The snapshot carries per-step timings; sum each step name's
   median AND p90 across runs. A step can look fine in one sample and be
   the wall-clock lottery across many: `fetch-depth: 0` checkouts fetch
   every branch and tag at full history (a ~400MB pack here), taking 30s
   or 4min depending on GitHub's server-side pack cache. Rule of thumb:
   any always-run step whose p90 exceeds ~2x its median is a variance
   problem, not a size problem — hunt for the erratic dependency
   (pack cache, registry, external download). For checkouts specifically,
   `filter: "blob:none"` keeps setuptools_scm working (refs + commit
   graph) while skipping historical file contents; only jobs that read
   old blob contents (e.g. `git diff main -- <paths>` over sources) need
   care, and even those lazy-fetch on demand.
7. **Suite size — step back from the slow tail.** `pytest_summaries` in
   the snapshot carries total test counts and total pytest wall per job.
   Individual slow tests are only half the story: once the outliers are
   fixed, sheer test count becomes the long pole (N tests × small median
   cost, growing every week). Each run:
   - Report total count and total pytest seconds, and the trend vs prior
     snapshots (absolute and per-week growth rate).
   - Estimate the split: how much of pytest wall is the slow tail
     (durations data) vs the body of ordinary tests? When the body
     dominates, per-test fixes stop paying and the leverage is fewer or
     cheaper tests.
   - Hunt duplicate coverage: several tests exercising the same code path
     with cosmetic variations (candidates for parametrize or deletion),
     new tests added next to older ones that already assert the same
     behavior, and whole files whose subject is also covered elsewhere.
     Sample a few of the fastest-growing test files rather than trying to
     read everything.
   - Hunt low-value tests: asserting trivialities (constructors,
     passthroughs, framework behavior), tests that can't fail unless an
     adjacent test also fails, over-broad matrix legs.
   - Deleting or merging tests is coverage-sensitive: exact duplicates are
     safe fixes; anything judgement-based is a report proposal for a
     maintainer.

## Phase 3 — Report

Rewrite `design/ci-perf/report.md` (full replacement each run; history
lives in the snapshots and git). Structure:

```markdown
# CI performance report — YYYY-MM-DD
Data: N runs, DATE..DATE. Snapshot: history/YYYY-MM-DD.json

## Summary
2–4 sentences: wall-clock medians per workflow, trend arrow, the one
dominant bottleneck right now.

## Queue vs execution
Table per workflow/job: median exec, median queue, p90 wall.

## Slowest tests
Top ~15 with median seconds and classification. "(no data — --durations
not in CI)" if empty.

## Suite size
Total tests / total pytest seconds per job, trend vs prior snapshots,
slow-tail vs body split, duplicate-coverage and low-value findings
(or what was sampled and came up clean).

## Regressions since last report
Or "none".

## Waste
Cancelled-run runner-minutes, overhead-dominated jobs, etc.

## Proposals (ranked)
Each: what / est. wall-clock impact / disruption (safe-fix vs structural)
/ status (new, PR opened #N, done, declined).
Carry forward prior proposals with updated status — don't drop them.

## PRs opened by this skill
See prs.md.
```

**Also maintain `design/ci-perf/prs.md`** — the permanent ledger of every
change and PR this skill has produced. Unlike the report it is never
rewritten, only appended to and updated in place: one entry per PR (number,
date, one-line description, status open/merged/closed, measured impact once
verified). Each run: add entries for any PRs opened, refresh the status of
open ones (`gh pr view`), and record verified impact from the impact-check
phase.

Leave report + snapshot + prs.md as uncommitted working-tree changes; ask
the user whether to commit them at the end of the run.

## Phase 4 — Fix

From the ranked proposals, prepare the top safe fixes (typically 1–3 per
run, shipped together with the report in the run's single PR):

**Safe-fix categories** (auto-PR eligible, still ask-first):
- Workflow hygiene: add `--durations=50` to pytest, drop unneeded
  `fetch-depth: 0` / `fetch-tags`, cache tuning, merging trivially small
  jobs, removing needless `needs:` serialization.
- Trivial test fixes: real `sleep(...)` waits replaced by mock clocks or
  events, removal of exact-duplicate tests, marking genuinely slow tests
  `@pytest.mark.slow` where an equivalent fast path exists.

**Structural proposals** (never a PR from this skill): renaming/merging
required checks (branch protection), moving checks between workflows,
retry/concurrency policy changes, anything a reviewer could reasonably
object to on grounds other than correctness. They rank in the report, and
when one is **ripe** — a concrete change with measured impact, worth doing
on the evidence, and no open question the next snapshot would answer —
write it up as an issue on `meridianlabs-ai/inspect_ai` (the org's tracking
repo, same as test-failure triage) so it gets a maintainer decision instead
of scrolling by in successive reports. Before filing, search for an
existing issue (`gh issue list --repo meridianlabs-ai/inspect_ai
--state all --search "<key phrase>"`, plus the issue links already in the
report): if one exists, add the new evidence as a comment rather than
filing a duplicate. Record the issue link in the proposal's status line.
Speculative or still-maturing proposals stay report-only.

Procedure: one branch off `main` for the whole run. Each fix is its own
commit — make the single change, run the relevant local validation
(`ruff check`, `mypy` for touched Python; the affected tests for test
fixes) — with the snapshot/report/prs.md commits alongside. Write one PR
body per `.github/pull_request_template.md` covering everything the run
ships, then **show the user the diff and PR body and wait for their OK
before any push**. After opening, watch CI per AGENTS.md. Record the PR
number in the report and prs.md.

## Verifying impact

Each run, check the proposals marked "PR opened/done" in the previous
report against the new snapshot: did the metric move as predicted? Say so
in the report — honest misses are how estimates get better. Record the
verified (or missed) impact on the PR's entry in prs.md.

## Scheduled (unattended) mode

The workflow `inspect-ai-ci-perf.yml` in `meridianlabs-ai/actions` runs
this skill every ~2 days with no user present (it sets `CI_PERF_SCHEDULED=1`
and says so in the prompt). Differences from an interactive run:

- **Don't ask — act, within these bounds.** Commit the snapshot, report,
  prs.md updates, and up to 2 safe fixes (safe-fix categories only, one
  commit each, local validation run and passing) on one branch and open
  ONE PR — the run's entire output ships as a single PR. Structural
  proposals are never shipped as changes; ripe ones are filed as issues
  per the fix phase (the fork tracking repo accepts marvin's issue writes
  even while upstream PRs are blocked).
- **Check the previous run's PR first** (`gh pr list --author i-am-marvin`
  plus the open entries in prs.md). If it is still open, push this run's
  commits onto its branch instead of opening a second PR. Never re-ship a
  fix that's already sitting in the open PR, and respect the AGENTS.md
  open-PR limit (4 per account).
- **Contribution-policy compliance:** the marvin account is recorded as a
  qualified contributor in `.github/qualified.yml`, which satisfies the PR
  gate; the substantive rules still apply — the PR body must carry the
  measured evidence from the snapshot for every fix it ships (AGENTS.md
  rule 7).
- **Push mechanics:** the token is the marvin machine account, which has
  write access on the `meridianlabs-ai/inspect_ai` fork but not upstream.
  Push branches to the fork and open PRs against
  `UKGovernmentBEIS/inspect_ai` following the "Opening an upstream PR from
  an org fork" section of AGENTS.md (`gh api` with `head_repo`).
- **Skip anything doubtful.** If local validation fails, the fix touches
  more than intended, or the change is only arguably in a safe-fix
  category, drop it to a report proposal instead of shipping it. An
  unattended run that ships zero fixes is a fine outcome; one that ships
  a wrong fix is not.
- Record the opened PR in prs.md before the run ends, and disclose agent
  involvement in the PR body per AGENTS.md (including the scheduled-run
  context and a link to the workflow run).
