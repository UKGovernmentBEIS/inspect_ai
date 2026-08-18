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
| [#4848](https://github.com/UKGovernmentBEIS/inspect_ai/pull/4848) | 2026-08-12 | Mark 43s docker `read_file` test slow, `blob:none` on the Viewer `check-schema-and-types` checkout, collector hardening (dedupe/sort/gap warning) | merged | Verified 2026-08-18, mixed. Viewer half held: `check-schema-and-types` 74→54s median, checkout max 216→16s, Viewer wall 82→67s. Test half missed: predicted −15–40s on `test` exec, measured 442→445s — the 45s it removed from the durations tail (194→150s per job) was fully absorbed by six days of suite growth |
| [#4932](https://github.com/UKGovernmentBEIS/inspect_ai/pull/4932) | 2026-08-18 | Scheduled unattended mode, suite-size analysis (`pytest_summaries` in the collector), this ledger; companion workflow [meridianlabs-ai/actions#93](https://github.com/meridianlabs-ai/actions/pull/93) | merged | n/a (tooling) — its `pytest_summaries` produced the suite-size baseline in the 2026-08-18 report |
| [meridianlabs-ai/inspect_ai#255](https://github.com/meridianlabs-ai/inspect_ai/pull/255) | 2026-08-18 | Report + snapshot for 2026-08-18 (first fully unattended run) | open | n/a (report) — opened against the **fork**, not upstream: the scheduled token has `pull` only on `UKGovernmentBEIS/inspect_ai`, so creating the upstream PR returns 403 |

## Prepared but not opened

The 2026-08-18 scheduled run prepared two safe fixes it could not push: the
marvin token is a fine-grained PAT without the Workflows permission, so any
branch touching `.github/workflows/**` is rejected by both `git push` and the
`gh api` git-data path. (The same token also has `pull` only on upstream, so
it cannot open a PR there at all.) Both fixes are specified with exact diffs
in `report.md` (proposals 1 and 2); proposal 3 is the credential fix.

| Fix | Measured basis | Expected impact |
|---|---|---|
| `pytest -n auto` → `-n logical` in the `test` job | Local A/B on an identical 4-vCPU runner: 449.3s → 333.8s, identical results; CI's report-log artifact shows only 2 workers | `test` exec 445 → ~330s, i.e. ~2 min off nearly every PR |
| `filter: "blob:none"` on the last four full-history checkouts | Snapshot step timings: 56s / 29s / 28s checkouts vs ~5s everywhere else | ~75s off the serialized sandbox-tools chain |
