# Release process

`inspect_ai` releases are cut by [Release Please](https://github.com/googleapis/release-please)
and published to PyPI and npm by GitHub Actions with trusted publishing.

## Normal release

1. **PR titles set the version.** PRs are squash-merged and their titles follow
   Conventional Commits (enforced by `pr-title-lint.yml`). Since the last
   release, any `fix`, `feat`, `perf` or `revert` makes the next release a patch
   (0.3.x); a breaking change (`feat!:`) makes it a minor (0.x.0). Other types
   make no release on their own. Config: `.release-please-config.json`; the
   last released version: `.release-please-manifest.json`.
2. **Release PR.** On every push to `main`, `release.yml` runs Release Please,
   which opens or updates the release PR (branch
   `release-please--branches--main`, title `chore(main): release X.Y.Z`). The
   PR bumps the manifest only; Release Please does not touch `CHANGELOG.md`.
   `release.yml` then runs `.github/scripts/release_changelog.py prepare` on the
   branch, which renames `## Unreleased` to `## X.Y.Z (DD Month YYYY)` (today,
   UTC) and adds an empty `## Unreleased` above it, and dispatches `build.yml`
   and `release-pr-checks.yml` on the branch.
3. **Checks.** `release-pr-checks.yml` fails the release PR if the changelog
   section is missing, undated or empty, if the version is not newer than
   PyPI's latest, if any sandbox-tools artifact pinned in `SHA256SUMS` is not on
   S3 with its digest, if the PR head fails the build gates (`build-dist`), or if
   rebuilding PyPI's latest version no longer matches PyPI (`publish-parity.yml`).
4. **Merge on Monday** by default; merge sooner for an urgent fix. To refresh
   the changelog date first, run the Release workflow from the Actions tab. The
   release PR changes `.release-please-manifest.json`, which
   `.github/CODEOWNERS` assigns to @jjallaire, @dragonstyle and @epatey; with
   code-owner review required on `main`, one of them must approve it.
5. **Release.** Merging tags `X.Y.Z` and creates the GitHub Release. In the same
   `release.yml` run, `release-notes` replaces the release body with the
   changelog section, `build` builds and gates the distributions, and
   `publish-pypi` (environment `pypi`) and `publish-npm` (environment `npm`,
   via `npm-publish.yml`) each wait for an environment reviewer's approval.

## Why everything runs in `release.yml`

The workflow uses the built-in `GITHUB_TOKEN`. Pushes, tags and releases made
with it trigger no other workflows, so:

- the release PR's checks would never run; `release.yml` dispatches them
  (`workflow_dispatch` is exempt);
- the GitHub Release does not trigger `publish.yml` or `npm-publish.yml`;
  `release.yml` publishes itself, with the same composite actions
  (`.github/actions/build-dist`, `.github/actions/publish-dist`) and
  `npm-publish.yml` as a called workflow, so the two paths cannot drift.

Trusted publishers: PyPI matches the workflow file that runs the publishing
job, so `release.yml` and `publish.yml` each need a PyPI publisher. npm matches
the calling workflow, so `release.yml` and `npm-publish.yml` each need an npm
publisher. The `pypi` and `npm` environments must allow deployments from
`main` (release.yml) and from version tags (break-glass).

## Retries and recovery

Re-running the Release workflow is safe at any point.

- **Release PR checks missing** (a dispatch failed): re-run the failed Release
  job, or run the Release workflow on `main` with no `tag`. It dispatches each
  check workflow that has no run yet on the release PR's head commit. Closing
  and reopening the release PR also runs them, as the person who reopened it.
- **Release created, then a later job failed or was cancelled** (notes, build,
  either publish). In order of preference:
  1. *Re-run failed jobs.* This keeps the original run's tag, and when only a
     publish job failed, it re-publishes the build job's original artifact.
  2. *Re-run all jobs*, or re-run a run that failed inside Release Please
     after it created the release. Release Please reports a release only once,
     so the run resumes the release whose tag is on the run's own commit,
     provided it is a published, non-pre-release GitHub Release and the
     manifest at the tag names it. It never picks up a newer release. If a
     GitHub lookup fails (network, rate limit, auth, server error), the job
     fails rather than finishing green without publishing; re-run it.
  3. *Recovery dispatch:* Actions → Release → Run workflow on `main` with `tag`
     set to the release. This skips Release Please and the release PR
     entirely and finishes only that release. The same checks apply, plus the
     tag must be on `main`; a failed check or lookup fails the run.
- **A resumed release**:
  - restores the release notes from `CHANGELOG.md`;
  - rebuilds from the tag (except when only a publish job is re-run);
  - publishes behind the same environment approvals.
- **Files PyPI already has** are skipped when they match: the same SHA256, or,
  for a rebuild (archive metadata such as timestamps differs between builds),
  the same members with the same contents under the parity rules
  (`compare_archives`, which ignores only the sdist's recorded checkout
  branch). A same-named file with different contents fails the job, since
  PyPI never replaces a file. npm skips a version it already has.
- **A queued Release run can be replaced by a newer push**, so the run that
  creates a release may be on a later commit than the release PR merge. To
  resume that release, re-run that later run, or use the `tag` input.

## Break-glass

- **Publish a GitHub Release by hand** (`gh release create X.Y.Z --verify-tag`)
  on a version tag: `publish.yml` and `npm-publish.yml` run on the release
  event.
- **Dispatch `publish.yml`** on the tag, typing the tag to confirm; this may
  publish a tag that is not on `main`. Dispatch `npm-publish.yml` on the tag
  with dry-run unchecked.
- **Local:** `python scripts/pypi-release.py release X.Y.Z` (PyPI only; its
  tag push no longer triggers npm, so dispatch `npm-publish.yml`).

After any release made outside the release PR, open a PR that sets
`.release-please-manifest.json` to the released version and renames
`## Unreleased` by hand; otherwise the next release PR proposes the same
version and its checks fail.

## Bootstrap

The repository has version tags but no GitHub Releases. Release Please finds
no release, falls back to the tag matching the manifest version, and reads
commits from there. The manifest must therefore equal the latest released tag
when this flow is enabled. A release PR opens on the first push to `main` with
a `fix`, `feat`, `perf` or `revert` commit since that tag; PRs merged with
their branch history already brought some after 0.3.277, so the merge that
enables this flow opens one. It releases everything under `## Unreleased`,
including entries from PRs merged before titles were linted.
