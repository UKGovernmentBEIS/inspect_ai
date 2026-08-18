# PRs opened by the ci-perf skill

Permanent ledger of every change and PR produced by the ci-perf skill
(`.claude/skills/ci-perf/SKILL.md`). Appended/updated each run — never
rewritten. One entry per PR: number, date opened, what it changed, status,
and measured impact once a later snapshot verifies it.

| PR | Opened | Change | Status | Measured impact |
|---|---|---|---|---|
| [#4746](https://github.com/UKGovernmentBEIS/inspect_ai/pull/4746) | 2026-08-04 | Add `--durations=50` to Build pytest for per-test timing visibility | merged | Enabled the durations data all later runs analyze |
| [#4747](https://github.com/UKGovernmentBEIS/inspect_ai/pull/4747) | 2026-08-04 | Remove `changes` → `test` serialization from Build critical path | merged | Verified 2026-08-05: full queue+start cycle removed from the longest job's critical path |
| [#4748](https://github.com/UKGovernmentBEIS/inspect_ai/pull/4748) | 2026-08-04 | The ci-perf skill itself (collector script + SKILL.md) | merged | n/a (tooling) |
| [#4760](https://github.com/UKGovernmentBEIS/inspect_ai/pull/4760) | 2026-08-05 | Two slow-test fixes (38s sandbox-init test, S3 pagination test), `filter: blob:none` checkouts, pre-install of tests/test_package, slow-test policy docs | merged | Verified 2026-08-12: −68s `test` exec, −20–25s each shorter job; erratic 30s–4min fetches gone (checkout now 4–5s median); predicted −60s, held |
| [#4848](https://github.com/UKGovernmentBEIS/inspect_ai/pull/4848) | 2026-08-12 | Mark 43s docker `read_file` test slow, `blob:none` on the Viewer `check-schema-and-types` checkout, collector hardening (dedupe/sort/gap warning) | merged | Pending — verify against next snapshot (predicted: −15–40s `test` exec; Viewer 74→~50s median, 216s tail gone) |
| [#4932](https://github.com/UKGovernmentBEIS/inspect_ai/pull/4932) | 2026-08-18 | Scheduled unattended mode, suite-size analysis (`pytest_summaries` in the collector), this ledger; companion workflow [meridianlabs-ai/actions#93](https://github.com/meridianlabs-ai/actions/pull/93) | open | n/a (tooling) |
