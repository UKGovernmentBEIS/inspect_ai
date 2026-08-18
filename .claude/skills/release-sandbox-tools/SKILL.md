---
name: release-sandbox-tools
description: Land a PR that requires new inspect-sandbox-tools injectable binaries to be built and published. Use when asked to land/merge a PR that changed code under src/inspect_sandbox_tools/ (typically its slow-tool-tests-release check fails on missing published binaries), or when asked to build/validate/upload sandbox tools binaries.
---

# Landing a PR that ships new sandbox tools injectables

Unblocks landing a PR that changed code under `src/inspect_sandbox_tools/` and
bumped the injectable version: builds the four artifacts (amd64/arm64 ×
glibc/musl) from the PR branch, validates them across Linux distros, and
publishes them to S3.
Background: `src/inspect_sandbox_tools/design/RELEASING.md`.

Typically run by a maintainer. The PR is often a contributor's — they can write
the code and bump the version, but they don't have credentials to upload the
binaries to S3, so a maintainer performs this final step.

**When to run:** once the PR is approved and the only failing CI check is
`slow-tool-tests-release` — it fails at the "Fetch published non-dev
sandbox-tools binaries (glibc + musl)" step with a message naming the missing
S3 object, because the bumped version's artifacts aren't published yet.
Running earlier wastes builds if review rounds change the injectable source.

**Be on the right branch:** run every step below from a checkout of the PR's
head branch (a git worktree of it is ideal) — the binaries must be built from
the exact code being merged. Building from main or a stale checkout silently
publishes wrong binaries under the new version number.

All commands run from the repo root using the repo venv (`.venv/bin/python` —
do not use `uv run` or system python).

## 1. Preconditions

- Docker must be running with multi-arch (buildx) support: `docker info` succeeds.
- The version must be bumped. It's a plain integer in
  `src/inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt`; the
  required bump is whatever the `check-version-bump` CI job accepts (currently
  exactly one greater than main's):

  ```sh
  git show origin/main:src/inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt
  ```

  In the trigger scenario above the bump already exists —
  `slow-tool-tests-release` only runs once `check-version-bump` passes. If the
  bump is missing, the failing check is `check-version-bump`, not this one;
  the bump is a committed source change that rides in the PR.

Call the bumped value `{V}` below.

## 2. Build

```sh
.venv/bin/python src/inspect_ai/tool/_sandbox_tools_utils/build_within_container.py --all --dev=false
```

Slow (Docker builds for 4 variants; can exceed 10 minutes) — run it in the
background and monitor. On success, verify all four artifacts exist in
`src/inspect_ai/binaries/`:

- `inspect-sandbox-tools-amd64-v{V}`
- `inspect-sandbox-tools-arm64-v{V}`
- `inspect-sandbox-tools-amd64-musl-v{V}`
- `inspect-sandbox-tools-arm64-musl-v{V}`

(These are gitignored — never commit them.)

Be aware that other checkouts may hold stale binaries with the same version
name from earlier review rounds. The upload script doesn't glob across
checkouts — it takes whatever file matches in the binaries dir of the checkout
whose script you invoke — so build fresh and run the upload from this same
checkout.

## 3. Validate across distros

```sh
.venv/bin/python -m inspect_ai.tool._sandbox_tools_utils.validate_distros
```

Must be run with `-m` (module mode) for imports to work. It runs each artifact's
healthcheck in Docker containers: glibc variants on Ubuntu 16.04–24.04, Debian
11/12, Kali; musl variants on Alpine 3.16/3.18/latest. Also slow — background it.
Every distro must pass; any failure blocks the release.

## 4. Upload to S3 (user runs this — not the agent)

The upload needs the user's AWS credentials (SSO session). **Do not run it
yourself**; instead ask the user to run it in-session so the output lands in the
conversation:

> Uploading needs your AWS credentials. If your SSO session is stale, run
> `aws sso login` in a terminal first. Then type this in the prompt:
>
> `! .venv/bin/python src/inspect_ai/tool/_sandbox_tools_utils/upload_to_s3.py {V}`

The `!` prefix runs the command inside the session. It uploads all four
artifacts to `s3://inspect-sandbox-tools/` (us-east-2) with `--acl public-read`.

The script shells out to plain `aws` with no profile; users on AWS SSO may
need `--profile <profile>` on the login and an `AWS_PROFILE=<profile>` prefix
on the upload command.

## 5. Verify the upload (no credentials needed)

Objects are public-read, so confirm each returns HTTP 200:

```sh
for f in amd64 arm64 amd64-musl arm64-musl; do
  curl -sI -o /dev/null -w "%{http_code} inspect-sandbox-tools-$f-v{V}\n" \
    "https://inspect-sandbox-tools.s3.us-east-2.amazonaws.com/inspect-sandbox-tools-$f-v{V}"
done
```

As a sanity check that the right bytes were published, the `content-length`
from a HEAD request (`curl -sI`) can be compared against the local file sizes.

## 6. Get CI green

Re-run the failing `slow-tool-tests-release` job (from the PR's checks page,
or `gh run rerun <run-id> --failed`) and confirm it passes. This skill ends
here — do not merge the PR; that happens through the normal review process.

PyPI bundling is also not part of this process — the `inspect_ai` release
script (`scripts/pypi-release.py`) pulls the glibc binaries from S3
automatically at release time. Once the PR merges, nothing more is needed.
