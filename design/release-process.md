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
   PR bumps the manifest and adds the version's section to `CHANGELOG.md` (see
   [Changelog](#changelog)). `release.yml` then dispatches `build.yml`,
   `changelog-lint.yml` and `release-pr-checks.yml` on the branch. `build.yml`
   and `changelog-lint.yml` provide `main`'s required status checks, which
   every release PR needs.
3. **Checks.** `release-pr-checks.yml` fails the release PR if the version is
   not newer than PyPI's latest or is already tagged, if any sandbox-tools
   artifact pinned in `SHA256SUMS` is not on S3 with its digest, if the PR head
   fails the build gates (`build-dist`), or if rebuilding PyPI's latest version
   no longer matches PyPI (`publish-parity.yml`).
4. **Merge on Monday** by default; merge sooner for an urgent fix. To refresh
   the changelog date first, run the Release workflow from the Actions tab. The
   release PR changes `.release-please-manifest.json`, which
   `.github/CODEOWNERS` assigns to @jjallaire, @dragonstyle and @epatey; with
   code-owner review required on `main`, one of them must approve it.
5. **Release.** Merging tags `X.Y.Z` and creates the GitHub Release, whose
   notes are the version's changelog section. In the same `release.yml` run,
   `build` builds and gates the distributions, and `publish-pypi` (environment
   `pypi`) and `publish-npm` (environment `npm`, via `npm-publish.yml`) each
   wait for an environment reviewer's approval.

## Changelog

Release Please writes `CHANGELOG.md` and the GitHub Release notes from the
squash-merged PR titles since the last release, as in `inspect_scout`. Each
release adds a `## [X.Y.Z](compare link) (YYYY-MM-DD)` section below the
`# Changelog` title, with an entry per commit (linking its PR and commit)
grouped by type: `feat` under Features, `fix` under Bug Fixes, `perf` under
Performance Improvements, `revert` under Reverts. Other types are hidden
(`changelog-sections` in `.release-please-config.json`). Sections before
0.3.279 were curated by hand and keep their format.

Release Please also reads the commit body. The repository's squash merge
default commit message must be "Pull request title and description"
(`squash_merge_commit_title=PR_TITLE`, `squash_merge_commit_message=PR_BODY`,
as in `inspect_scout`), so the commit title is the linted PR title and the
body is the PR description. With GitHub's default, a single-commit PR squashes
to its commit message instead. With the setting:

- a `BREAKING CHANGE:` paragraph is listed under "⚠ BREAKING CHANGES"; it
  runs to the next blank line, so it needs a blank line after it;
- a line that starts with a Conventional Commits header (`fix: ...`) right
  after a blank line adds an entry of its own. The parser splits on a blank
  line followed by a header and does not track Markdown fences, so indenting
  the line prevents the entry and a fence does not when a blank line comes
  before the line inside it;
- `BEGIN_COMMIT_OVERRIDE` ... `END_COMMIT_OVERRIDE` in a merged PR's
  description replaces that commit's message, which is how an entry is
  reworded before the release. Release Please reads it when it next updates
  the release PR. It matches the bare word anywhere in the description and
  takes the text after it, so a description that only mentions it loses its
  entry.

PRs do not edit `CHANGELOG.md`: `changelog-lint.yml` (check
`no-changelog-edits`) runs on every PR and fails one that changes the file,
except the release PR (head branch `release-please--branches--main` in this
repository, or a dispatched run on that branch). Its check is required on
`main`. Edits made to the release
PR's `CHANGELOG.md` are lost the next time Release Please updates the PR.

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
- **Release created, then a later job failed or was cancelled** (build or
  either publish). In order of preference:
  1. *Re-run failed jobs.* This keeps the original run's tag, and when only a
     publish job failed, it re-publishes the build job's original artifact.
  2. *Re-run all jobs*, or re-run a run that failed inside Release Please
     after it created the release. This is supported only when the release
     was created on that run's own commit, which is the normal case: the run
     triggered by merging the release PR. Release Please reports a release
     only once, so the run resumes the release whose tag is on its own commit,
     provided it is a published, non-pre-release GitHub Release and the
     manifest at the tag names it. If a GitHub lookup fails (network, rate
     limit, auth, server error), the job fails rather than finishing green
     without publishing; re-run it.
  3. *Recovery dispatch:* Actions → Release → Run workflow on `main` with `tag`
     set to the release. This skips Release Please and the release PR
     entirely and finishes only that release. The same checks apply, plus the
     tag must be on `main`; a failed check or lookup fails the run. Use this
     whenever the release is not on the re-run's commit.
- **A run that finds no release to finish fails closed.** When nothing is
  resolved, the job's last step checks the latest Release Please release on
  `main`: PyPI must have its wheel and sdist, and npm its version. If either
  is missing and no other Release run is active (one may be waiting for
  publish approval), the job fails with `Release X.Y.Z exists but is not fully
  published (missing ...); re-run the Release workflow with tag=X.Y.Z`. It
  never resumes or picks a release itself. A lookup failure fails the job too.
  Other active runs are found by status on the server, so a run waiting for
  approval counts however many runs came after it. Only the latest release is checked: an older
  release left incomplete behind a newer one has to be found and dispatched
  by hand.
- **A resumed release** rebuilds from the tag (except when only a publish job
  is re-run) and publishes behind the same environment approvals. Its GitHub
  Release notes are the ones Release Please wrote when it created the
  release.
- **Files PyPI already has** are skipped when they match: the same SHA256, or,
  for a rebuild (archive metadata such as timestamps differs between builds),
  the same members with the same contents under the parity rules
  (`compare_archives`, which ignores only the sdist's recorded checkout
  branch). A same-named file with different contents fails the job, since
  PyPI never replaces a file. npm skips a version it already has.
- **A queued Release run can be replaced by a newer push**, so the run that
  creates a release may be on a later commit than the release PR merge. If
  that run fails after creating the release, *Re-run all jobs* cannot find
  it; the re-run fails with the message above, and the `tag` dispatch is the
  recovery. *Re-run failed jobs* still works, because it keeps the tag.

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
`.release-please-manifest.json` to the released version; otherwise the next
release PR proposes the same version and its checks fail. `CHANGELOG.md` gets
no section for that version: its notes are only in the GitHub Release, and
the next release's section lists the commits since its tag.

## Bootstrap

0.3.278 was released by hand through `publish.yml`, with a GitHub Release on
its tag; earlier versions have tags but no GitHub Releases. Release Please
finds the 0.3.278 release and reads commits from there, so the manifest must
equal 0.3.278 when this flow is enabled. A release PR opens on the first push
to `main` with a `fix`, `feat`, `perf` or `revert` commit after 0.3.278.
Commits without a Conventional Commits type do not open one and are left out
of the changelog.
