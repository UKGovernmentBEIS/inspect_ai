# CI performance evidence

Recurring CI reports now live in the Actions job summary and on the fork's
"CI performance trend summaries" tracking issue. Implementation findings have
separate issues on meridianlabs-ai/inspect_ai. The analysis run does not push
branches or open PRs.

Raw snapshots, reports, and proposed findings are workflow artifacts with
90-day retention in meridianlabs-ai/actions. No raw snapshots belong in Git.
At one 1.2 MB snapshot every two days, retention is about 54 MB before artifact
compression, plus the much smaller reports and summaries.

`baseline.json` preserves aggregate measurements from the 12 formerly committed
snapshots, collected from 2026-08-04 through 2026-09-01. It is a fixed migration
baseline. New summaries go to tracking-issue comments, not this file. The
baseline retains workflow/job timings, pytest outcomes and wall, sample counts,
and runner minutes. It was generated with `summarize_ci_data.summarize`, then
`slow_tests_seconds` and `slow_steps_seconds` were removed from each summary.
The baseline omits individual runs, steps, and test identities. Recurring
summaries retain the top 15 observed tests and steps. Runner minutes are
measured job execution time, not GitHub's rounded billed minutes.

`report.md` and `prs.md` are historical records. Their snapshot references name
files removed in this migration. Those files remain available in Git history.
Current issue and PR states must be checked on GitHub before acting on an old
proposal. In particular, fork PR #408 carries later snapshots and fixes; its
raw snapshots should not be promoted into the new storage scheme.

The summarizer records successful timing distributions using median and linear
p90 interpolation. Wait-from-run-start includes predecessor time and is not
queue time. Workflow wall uses updated_at, not push-to-all-checks-green. Pytest
outcomes are per job, and unavailable logs are missing observations.

See [the CI skill](../../.claude/skills/ci-perf/SKILL.md) for collection,
analysis, and issue publication. For a branch proof, dispatch the actions
workflow with `dry_run=true`, `inspect_ai_ref=main`, and `ci_perf_ref` set to the
fork's tooling branch. The dry-run creates only workflow outputs and artifacts.
