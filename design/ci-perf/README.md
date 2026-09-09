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
measured job execution time, not GitHub's rounded billed minutes. Skipped jobs
contribute no execution time; GitHub sometimes returns inverted timestamps for
them. Missing or inverted execution times on non-skipped jobs make compute totals
unavailable, with the count recorded in `unavailable_job_timings`. Missing or
inverted workflow wall, job wait, and step observations are excluded from their
distributions and counted in `excluded_timings`. The collector retains step
status so the summarizer can omit skipped steps; legacy raw files lack that
status, and the baseline does not retain step distributions.

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
analysis, and issue publication. For a branch proof, dispatch the actions
workflow with `dry_run=true`, `inspect_ai_ref=main`, and `ci_perf_ref` set to the
fork's tooling branch. `ci_perf_ref` executes that branch's code; workflow
dispatch requires collaborator write access. The dry-run creates only workflow
outputs and artifacts.

Analysis and publication run in one job. Their separation is between tokens:
analysis uses the read-only workflow token, and publication uses the fork write
token on the same runner. Publication runs on the schedule; manual dispatch is
for dry-run verification.
