---
name: release-sandbox-tools
description: Land a PR that requires new inspect-sandbox-tools injectable binaries to be built and published. Use when asked to land/merge a PR that changed code under src/inspect_sandbox_tools/ (typically its slow-tool-tests-release check fails on missing published binaries), or when asked to build/validate/upload sandbox tools binaries.
---

# Landing a PR that ships new sandbox tools injectables

Unblocks landing a PR that changed code under `src/inspect_sandbox_tools/` and
bumped the injectable version: builds the four artifacts (amd64/arm64 ×
glibc/musl) from the PR branch, validates them across Linux distros, publishes
them to S3, and commits the pinned digests back to the PR branch.

The whole procedure is scripted as an interactive wizard:

```sh
scripts/release-sandbox-tools.sh [--dry-run] [--auto]
```

**Agents: run it with `--auto`.** In auto mode every confirmation resolves to
a safe default, and anything that needs a human mid-run (starting Docker,
`aws sso login`) aborts with instructions instead of waiting. Without
`--auto` the prompts need a terminal, so a run from your shell exits
immediately. Before starting, check `aws sts get-caller-identity`; if
credentials are stale, ask the user to run `aws sso login` first — the upload
uses their ambient AWS session. Run the wizard in the background and monitor
it: build plus validation can exceed 20 minutes.

Typically run by a maintainer. The PR is often a contributor's — they can write
the code and bump the version, but they don't have credentials to upload the
binaries to S3, so a maintainer performs this final step.

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
   (exactly one greater than origin/main's) — the wizard requires it and
   won't write it.
2. **Get a checkout of the PR's head branch** (a git worktree is ideal) and
   make sure it's up to date — the binaries must be built from the exact code
   being merged. Offer to set this up.
3. **Run the wizard** from that checkout's repo root:
   `scripts/release-sandbox-tools.sh --auto` (add `--dry-run` to build and
   validate without publishing anything). The wizard itself checks
   preconditions (branch, PR approval, version bump, Docker), builds,
   validates across distros, uploads to S3, commits and pushes the rewritten
   `SHA256SUMS`, and verifies the published bytes — don't redo those steps
   around it. It also resumes: re-runs skip the slow build/validation stages
   when a recorded fingerprint proves they already ran against the current
   source, so stopping and re-running (or dry-run then real run) is cheap.
4. **Confirm CI goes green.** The digest push triggers a fresh run; watch
   `slow-tool-tests-release` pass. If the wizard ended without pushing the
   digests (its closing summary lists the commit as still to do), commit the
   rewritten `SHA256SUMS` to the PR branch and push it yourself — CI stays
   red until it lands. Do not merge the PR — that happens through
   the normal review process. PyPI bundling is also not part of this process:
   the release script pulls the glibc binaries from S3 automatically.

## If the wizard fails or can't be used

The underlying commands and mechanism are documented in
`src/inspect_sandbox_tools/design/RELEASING.md`. Two rules survive any manual
fallback:

- **Published versions are immutable.** If an object for the version already
  exists on S3 with different bytes (the upload script's guard aborts on
  this), never force over it — bump the version and publish fresh artifacts.
- **Binaries must come from the exact PR code.** Artifact filenames only
  encode the version, so files lying around from an earlier review round look
  identical; when in doubt, rebuild.
