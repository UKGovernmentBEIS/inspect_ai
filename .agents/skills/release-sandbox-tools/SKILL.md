---
name: release-sandbox-tools
description: Land a PR that requires new inspect-sandbox-tools injectable binaries to be built and published. Use when asked to land/merge a PR that changed code under src/inspect_sandbox_tools/ (typically its slow-tool-tests-release check fails on missing published binaries), or when asked to build/validate/upload sandbox tools binaries.
---

# Landing a PR that ships new sandbox tools injectables

Unblocks landing a PR that changed code under `src/inspect_sandbox_tools/` and
bumped the injectable version: has CI build and validate the four artifacts
(amd64/arm64 × glibc/musl) at the PR's head commit, verifies their
attestations, publishes them to S3, and commits the pinned digests back to the
PR branch.

The whole procedure is scripted as an interactive wizard:

```sh
scripts/release-sandbox-tools.sh [--dry-run] [--auto]
```

**Agents: run it with `--auto`.** In auto mode every confirmation resolves to
a safe default, and anything that needs a human mid-run (`aws sso login`)
aborts with instructions instead of waiting. Without
`--auto` the prompts need a terminal, so a run from your shell exits
immediately. Before starting, check `aws sts get-caller-identity`; if
credentials are stale, ask the user to run `aws sso login` first — the upload
uses their ambient AWS session. The wizard also needs `gh` authenticated as
someone who can dispatch workflows upstream. Run it in the background and
monitor it: the CI build takes about 10 minutes.

Run by a maintainer, for either kind of PR:

- **Maintainer PR**: the branch is pushed to `UKGovernmentBEIS/inspect_ai`.
  The maintainer writes the code, bumps the version, and after approval runs
  the wizard from that branch.
- **Contributor PR**: the branch lives in the contributor's fork. The
  contributor writes the code and bumps the version; they can't dispatch the
  upstream build or upload to S3, so after approval a maintainer checks out
  the PR (`gh pr checkout <N>`) and runs the wizard. The digest commit is
  pushed to the fork's branch, which needs "Allow edits by maintainers".

Either way CI builds from the PR's head commit (fork commits are fetchable
by SHA upstream), and nobody builds release binaries locally.

**When to run:** once the PR is approved and the only failing CI check is
`slow-tool-tests-release` — it fails at the "Fetch and verify published
non-dev sandbox-tools binaries" step, either on the `SHA256SUMS` lockstep
check or with a message naming the missing S3 object, because the bumped
version's artifacts aren't published (and their digests committed) yet.
Running earlier wastes builds if review rounds change the injectable source.

## What you do

1. **Confirm the trigger.** The PR is approved and `slow-tool-tests-release`
   is the failing check (per "When to run" above). If `check-version-bump` is
   the failing check instead, the fix is a committed version bump in
   `src/inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt`
   (greater than origin/main's; normally one more, but a burned version is
   skipped by bumping further, see below) — the wizard requires it and
   won't write it.
2. **Get a checkout of the PR's head branch** (a git worktree is ideal;
   `gh pr checkout <N>` for a fork PR) at the PR's current head commit — the
   wizard refuses to run otherwise. Offer to set this up.
3. **Run the wizard** from that checkout's repo root:
   `scripts/release-sandbox-tools.sh --auto` (add `--dry-run` to get the CI
   build without publishing anything). The wizard itself checks
   preconditions (branch, PR approval, head commit, version bump, and that
   merging upstream main as of its last fetch leaves the build inputs
   unchanged), dispatches
   `sandbox-tools-build.yml` at the head commit and waits for it, downloads
   and attestation-checks the artifacts, uploads to S3, commits and pushes
   the rewritten `SHA256SUMS`, and verifies the published bytes — don't redo
   those steps around it. It also resumes: a successful build run for the
   same commit is reused, so stopping and re-running (or dry-run then real
   run) is cheap. If the build fails on a flake, re-run the wizard, which
   dispatches a new build; don't use GitHub's re-run buttons, since only a
   run that succeeded on its first attempt counts.
4. **Confirm CI goes green.** The digest push triggers a fresh run; watch
   `slow-tool-tests-release` pass. If the wizard ended without pushing the
   digests (its closing summary lists the commit as still to do), commit the
   rewritten `SHA256SUMS` to the PR branch and push it yourself — CI stays
   red until it lands. Do not merge the PR — that happens through
   the normal review process. PyPI bundling is also not part of this process:
   the release script pulls the glibc binaries from S3 automatically.

## If the wizard fails or can't be used

The underlying commands and mechanism are documented in
`src/inspect_sandbox_tools/design/RELEASING.md`; the end-to-end flow and every
failure with its recovery are in
`src/inspect_sandbox_tools/design/sandbox-tools-release-flow.md`. Two rules
survive any manual fallback:

- **Published versions are immutable.** If an object for the version already
  exists on S3 with different bytes (the upload script's guard aborts on this),
  never force over it. If a build input changed, the version is burned: bump
  past it. If the bytes are from another valid CI build of the same inputs, keep
  them and finish from that run, no bump. See the release flow doc for the
  distinction and the steps.
- **Binaries must come from the exact PR code, built in CI.** Artifact
  filenames only encode the version, so files lying around from an earlier
  review round look identical. Upload only artifacts from a
  `sandbox-tools-build.yml` run whose built commit's build inputs match the
  PR's (normally the PR head), after `gh attestation verify` passes on each
  (RELEASING.md step 3). Never upload a local build.
