---
name: release-sandbox-tools
description: Build, validate, and publish a new version of the inspect-sandbox-tools injectable executables. Use when code under src/inspect_sandbox_tools/ changed and a new injectable version must ship, or when asked to build/validate/upload sandbox tools binaries.
---

# Releasing sandbox tools injectables

Builds the four injectable artifacts (amd64/arm64 × glibc/musl), validates them
across Linux distros, and publishes them to S3. Background:
`src/inspect_sandbox_tools/design/RELEASING.md`.

All commands run from the repo root using the repo venv (`.venv/bin/python` —
do not use `uv run` or system python).

## 1. Preconditions

- Docker must be running with multi-arch (buildx) support: `docker info` succeeds.
- The version must be bumped. It's a plain integer in
  `src/inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt` and must be
  greater than main's:

  ```sh
  git show origin/main:src/inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt
  ```

  If not yet bumped, increment it by 1 (this is a committed source change — it
  rides in the same PR as the sandbox tools code change).

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

## 5. Verify the upload (no credentials needed)

Objects are public-read, so confirm each returns HTTP 200:

```sh
for f in amd64 arm64 amd64-musl arm64-musl; do
  curl -sI -o /dev/null -w "%{http_code} inspect-sandbox-tools-$f-v{V}\n" \
    "https://inspect-sandbox-tools.s3.us-east-2.amazonaws.com/inspect-sandbox-tools-$f-v{V}"
done
```

## 6. Nothing else to do here

PyPI bundling is not part of this process — the `inspect_ai` release script
(`scripts/pypi-release.py`) pulls the glibc binaries from S3 automatically at
release time. Merging the PR with the version bump completes the release.
