# CI performance evidence

Recurring CI reports live in the Actions job summary and on the fork's
"CI performance trend summaries" tracking issue. Implementation findings have
separate issues on meridianlabs-ai/inspect_ai. The publisher applies the `auto`
label to start implementation; a marker comment prevents repeat triggers even
if a maintainer later removes the label. The analysis run does not push
branches or open PRs. A finding gets full evidence on its first occurrence on an
issue, then a short still-observed comment with the run link. Findings whose only
proposed change requires a human omit the automation label.

Raw snapshots, reports, and proposed findings are workflow artifacts with
90-day retention in meridianlabs-ai/actions. No raw snapshots belong in Git.
At one 1.2 MB snapshot every two days, retention is about 54 MB before artifact
compression, plus the much smaller reports and summaries.

`baseline.json` preserves aggregate measurements from 12 historical
snapshots, collected from 2026-08-04 through 2026-09-01. It is a fixed
baseline. New summaries go to tracking-issue comments, not this file. The
baseline retains workflow/job timings, pytest outcomes and wall, sample counts,
and runner minutes. It was generated with `summarize_ci_data.summarize`, then
`slow_tests_seconds` and `slow_steps_seconds` were removed from each summary.
The baseline omits individual runs, steps, and test identities. Recurring
summaries retain the top 15 observed tests and steps. Runner minutes are
measured job execution time, not GitHub's rounded billed minutes. Jobs are
collected with `filter=all`, so every re-run attempt's execution counts;
`rerun_runner_minutes` isolates attempts after the first, and carried-over jobs
(a new id each attempt but the same runner and start time) are counted once. In
a legacy raw file that predates the per-job attempt, a re-run's carried-over and
re-run jobs cannot be told apart, so `rerun_runner_minutes` is reported unknown
(null) rather than guessed from the run's attempt. This holds for any legacy
re-run that has job records, including one whose jobs were all skipped or
cancelled while queued: the old collector listed only the latest attempt, so an
earlier attempt's compute may be absent from the file. A re-run run records only its
latest attempt's start, so re-run runs are excluded from workflow wall and
job-wait distributions and counted in `rerun_runs`. Skipped jobs
contribute no execution time; GitHub sometimes returns inverted timestamps for
them. A non-skipped job that never got a runner (cancelled or failed while
still queued, so `runner_name` is null or empty — or, in legacy raw files,
with no steps) adds no runner time and is counted in `unstarted_jobs`. Missing or inverted execution times on non-skipped jobs make compute totals
unavailable, with the count recorded in `unavailable_job_timings`. Missing or
inverted workflow wall, job wait, and step observations are excluded from their
distributions and counted in `excluded_timings`. The collector retains step
status so the summarizer can omit skipped steps; legacy raw files lack that
status, and the baseline does not retain step distributions. `--limit` counts
kept runs: the collector keeps only runs whose PR head repository is upstream or
the Meridian fork and whose conclusion is not `action_required` (never started),
paging until it has that many, and records the excluded counts in
`excluded_untrusted_runs` and `excluded_action_required_runs` (both scoped to
the analyzed window). Each summary's `window` also carries its span in hours and,
against the most recent retained summary, `new_runs`/`overlap_runs`. That split is
by run start time against the previous window's end; because the collector fetches
completed runs only, a run that started before that end but finished after the
previous collection is counted in `overlap_runs` even though the earlier snapshot
did not hold it.

`report.md` and `prs.md` are historical records. Their referenced snapshots
are available in Git history.
Current issue and PR states must be checked on GitHub before acting on an old
proposal. In particular, fork PR #408 carries later snapshots and fixes; its
raw snapshots should not be committed.

The summarizer records successful timing distributions using median and linear
p90 interpolation. Wait-from-run-start includes predecessor time and is not
queue time. Workflow wall uses updated_at, not push-to-all-checks-green. Pytest
outcomes are per job, and unavailable logs are missing observations.

See [the CI skill](../../.claude/skills/ci-perf/SKILL.md) for collection,
analysis, and issue publication. The actions workflow has two dispatch inputs:
`inspect_ai_ref`, an upstream branch, tag, or commit (default `main`), and
`dry_run` (default `true`). The skill's tooling and the analyzed source both
come from that one upstream checkout. For a tooling branch proof, set
`inspect_ai_ref` to an upstream branch or `refs/pull/NNN/head` with `dry_run=true`;
workflow dispatch requires collaborator write access. A dry run creates only
workflow outputs and artifacts.

Analysis and publication run in one job. Their separation is between tokens:
analysis uses the read-only workflow token, and publication uses the fork write
token on the same runner. Publication runs on the schedule; manual dispatch is
for dry-run verification.
