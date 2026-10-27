# Releasing `inspect_sandbox_tools`

End-to-end process for shipping a new version of the sandbox tools executables.

## Overview

The sandbox tools are compiled into portable static Linux executables (amd64 + arm64) and distributed via:

1. **S3** — runtime downloads for editable/dev installs
2. **PyPI** — bundled into the `inspect_ai` wheel for pip installs

The version is a simple integer in `src/inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt`.

## Who does what

A sandbox-tools release rides on the PR that changes the injectable. The PR
either comes from a maintainer, on a branch pushed to `UKGovernmentBEIS/inspect_ai`,
or from a contributor, on a branch in their fork. The steps are the same
either way:

| Step | Who |
|------|-----|
| Change `src/inspect_sandbox_tools/` and bump the version (`check-version-bump` requires both in the same PR) | PR author |
| Review and approve | Reviewer |
| Dispatch the CI build at the approved head commit, upload to S3, commit `SHA256SUMS` to the PR branch | Maintainer (S3 credentials), via the wizard |
| Merge once `slow-tool-tests-release` is green | Maintainer |

CI builds the binaries; no one builds release binaries on their own machine.
For a contributor's PR, the maintainer pushes `SHA256SUMS` to the fork's
branch, which needs "Allow edits by maintainers" (on by default).

## Release Steps

Steps 3–6 are scripted as an interactive wizard. Run it from a checkout of
the PR's head branch (`gh pr checkout <N>` for a fork PR) once the PR is
approved, also for a dry run (`--dry-run` gets the CI build and checks it without publishing;
`--auto` answers every prompt with its safe default, for agents/unattended
runs):

```sh
scripts/release-sandbox-tools.sh [--dry-run] [--auto]
```

The sections below document the underlying commands. For a walkthrough of the
flow and every failure with its recovery, see
[sandbox-tools-release-flow.md](sandbox-tools-release-flow.md).

### 1. Make code changes

Edit source code under `src/inspect_sandbox_tools/`.

### 2. Bump the version

Increment the integer in:

```
src/inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt
```

### 3. Build executables in CI

Dispatch `.github/workflows/sandbox-tools-build.yml` from `main` with the PR's
approved head commit:

```bash
gh workflow run sandbox-tools-build.yml --repo UKGovernmentBEIS/inspect_ai --ref main -f sha={PR_HEAD_SHA}
```

Fork PR commits are fetchable by SHA from the upstream repo, so this works for
contributor PRs too. Each of the four variants builds on a runner of its own
arch (`ubuntu-latest`, `ubuntu-24.04-arm`) with
`build_within_container.py --arch {amd64,arm64} [--musl] --dev=false`, which
builds `--onedir` bundles in Docker and tars each bundle tree:

- `inspect-sandbox-tools-amd64-v{VERSION}` (glibc)
- `inspect-sandbox-tools-arm64-v{VERSION}` (glibc)
- `inspect-sandbox-tools-amd64-musl-v{VERSION}` (musl, built via `Dockerfile.pyinstaller.musl`)
- `inspect-sandbox-tools-arm64-musl-v{VERSION}` (musl)

The build jobs run the build scripts with the runner's stdlib `python3` (no
project install), so only the build inputs listed below run before signing.
They hold only `contents: read`, and no job restores a cache. The attest job,
the only one that can sign, writes `SHA256SUMS`, attests the four artifacts'
provenance, and publishes them as the run artifact `sandbox-tools-v{VERSION}`.
Validation (step 4) runs after signing, on each arch's runner; it imports all
of `inspect_ai`, so it runs where anything it changed would fail attestation
verification. Release only from a run that succeeded. The run is titled
`Build sandbox tools at {SHA}`.

Download and verify the artifacts into `src/inspect_ai/binaries/` before
uploading:

```bash
gh run download {RUN_ID} --repo UKGovernmentBEIS/inspect_ai -n sandbox-tools-v{VERSION} -D src/inspect_ai/binaries
gh attestation verify src/inspect_ai/binaries/inspect-sandbox-tools-amd64-v{VERSION} \
  --repo UKGovernmentBEIS/inspect_ai \
  --signer-workflow UKGovernmentBEIS/inspect_ai/.github/workflows/sandbox-tools-build.yml \
  --source-ref refs/heads/main
```

The attestation's `runDetails.metadata.invocationId` names the run that signed
it; check that the run succeeded and that its title names the built commit (the
PR head, or an earlier commit whose build inputs match it). The wizard does
these checks for all four artifacts.

**The built commit may never be on `main`.** PRs are squash-merged, so the
commit CI built (the PR head) is not an ancestor of the merge commit; it stays
fetchable through `refs/pull/N/head`. What `main` gets is the same *files*: the
branch must be up to date to merge, so the squash commit's tree is the PR's. So
the guarantee is about build inputs, not commits: `slow-tool-tests-release`
verifies each published object's attestation, checks the attesting run
succeeded on its first attempt (a re-run's result can come from a different
attempt than the one that signed the binaries), reads the built commit from its title, and fails unless the build
inputs at that commit match the PR's. The build inputs are whole directories,
since the build scripts run with their own directory first on `sys.path`:
`src/inspect_sandbox_tools/` (except `design/` and `tests/`, which the wheel
never contains), `src/inspect_ai/tool/_sandbox_tools_utils/`
(except `SHA256SUMS`), and `src/inspect_ai/binaries/` (gitignored, so normally
empty). Any change there after the build, even to runtime code such as
`sandbox.py`, needs a new build. Symlinks there fail the gate, since the
comparison sees only a link's target path while the build reads its content. Limits:

- The commit is tied to the signature through the run title rather than
  signed itself, so the check trusts GitHub's record of which inputs started
  the run.
- The check runs after upload, so a failure means the published version is
  burned: its bytes can no longer match the PR. Recovery is to bump past the
  burned number and publish fresh. See
  [sandbox-tools-release-flow.md](sandbox-tools-release-flow.md) for the
  triggers and steps.
- A `.gitattributes` file above the build-input directories (none exists
  today) can change how checkout writes those files, and the comparison
  doesn't cover it.
- `slow-tool-tests-release` is not a required check, so a red result blocks
  the merge only because maintainers don't merge on red.
- A change to the build files alone (a lockfile, a Dockerfile) is not
  "injectable source" to `check-version-bump`, so it can't be released without
  also changing `src/inspect_sandbox_tools/`. Until that rule covers the build
  files, ship such a change together with an injectable change.

The same script builds a single variant locally (`--arch {amd64,arm64} [--musl]`,
`-dev` suffix by default), as the runtime's local-build fallback and the
`slow-tool-tests-dev` CI job do.

#### Build inputs

The builders install only pinned inputs, so a build doesn't depend on what
PyPI or conda-forge serve that day. Everything below lives in
`src/inspect_ai/tool/_sandbox_tools_utils/`:

- **Base images** are pinned by digest in `Dockerfile.pyinstaller` and
  `Dockerfile.pyinstaller.musl`. The `apt-get`/`apk` build tools are not
  pinned. None of them is bundled, but binutils' `strip` rewrites the bundled
  libraries (PyInstaller runs with `--strip`), so the glibc builder's binutils
  version can affect the bytes. Alpine 3.16's package repository no longer
  changes.
- **The glibc builder's CPython** and the runtime libraries bundled with it
  (openssl, libffi, ...) come from `conda-{amd64,arm64}.lock`, explicit conda
  lockfiles with a sha256 per package. Dependabot does not support conda;
  regenerate them, after changing the base image or to take updates, with
  `python src/inspect_ai/tool/_sandbox_tools_utils/lock_conda_env.py`, which
  lists any package published in the last 7 days for review.
- **Python packages** (the package's dependencies plus PyInstaller and the
  build backend) come from `requirements.txt`, installed with
  `--require-hashes --no-deps`, followed by `pip check`. `jsonrpcserver`
  publishes no wheel and builds from its hash-checked sdist (on musl, through
  the base image's pip 23 and its legacy `setup.py install` path). The
  binaries are released rarely, so there is no Dependabot entry for this file:
  GitHub's security alerts flag vulnerable pins in it, and updates are made by
  hand, as a fix for an alert or when preparing a release. `--no-config`
  skips the root `pyproject.toml`, so the command repeats its cooldown
  exemption for certifi, whose releases remove compromised CA roots:

  ```bash
  cd src/inspect_ai/tool/_sandbox_tools_utils
  uv pip compile --no-config --universal --python-version 3.10 --generate-hashes \
    --exclude-newer "7 days" --exclude-newer-package certifi=false --upgrade \
    ../../../inspect_sandbox_tools/pyproject.toml requirements.in -o requirements.txt
  ```

### 4. Validate across distros

CI runs this on each arch's runner, after signing:

```bash
python -m inspect_ai.tool._sandbox_tools_utils.validate_distros
```

Routes each artifact to the matching distro set: glibc variants across Ubuntu/Debian/Kali, the musl variant across Alpine.

### 5. Upload to S3

```bash
python src/inspect_ai/tool/_sandbox_tools_utils/upload_to_s3.py {VERSION}
```

Uploads all four artifacts (amd64/arm64 × glibc/musl) to the `inspect-sandbox-tools` bucket (us-east-2) with public-read ACL so runtime S3 downloads work without credentials.

The script refuses to run unless `{VERSION}` matches the committed `sandbox_tools_version.txt`, refuses to overwrite a published version with different bytes (published S3 objects are immutable — if a published object is wrong, bump the version and publish fresh artifacts; never fix a problem by re-uploading), rewrites `src/inspect_ai/tool/_sandbox_tools_utils/SHA256SUMS` with the digests of the four local artifacts (the downloaded CI artifacts, so it matches the run's `SHA256SUMS`) before uploading, and round-trip verifies each uploaded object.

**URL pattern:** `https://inspect-sandbox-tools.s3.us-east-2.amazonaws.com/inspect-sandbox-tools-{arch}[-musl]-v{version}`

### 6. Commit the digest file

Commit the rewritten `SHA256SUMS` to the release PR branch (the upload script prints the exact commands). The digests must land in the same PR as the version bump: every consumer (runtime S3 download, `pypi-release.py`, the `slow-tool-tests-release` CI gate) verifies fetched bytes against them, and the release gate stays red until both the upload completes and the sums are pushed.

Fail-closed window: while a version bump is merged (or installed non-editably from the PR branch) with the sums not yet rewritten, clean/pypi runtime downloads treat the missing sums entry as a fatal integrity failure. Once the rewritten sums are committed but before the S3 objects land, downloads 404 and fall back to the local-build prompt; the upload-before-commit ordering makes that window hard to reach. After upload, a digest mismatch anywhere is a stop-the-line signal — investigate; never re-upload over a published object.

### 7. Merge the PR

Once `slow-tool-tests-release` is green, merge through the normal review process.

### 8. PyPI release (when releasing inspect_ai)

`inspect_ai` releases go through Release Please (see `design/release-process.md`). Its release PR runs `.github/workflows/release-pr-checks.yml`, which fails if any artifact pinned in `SHA256SUMS` is not on S3 with its pinned digest (`pypi-release.py verify-sandbox-tools-published`), so publish the sandbox tools before merging the release PR. Merging it runs `.github/workflows/release.yml`, which pulls sandbox tools from S3 with the release script's `prepare` command and checks the built wheel with `verify-dist` before uploading to PyPI. The build and upload steps live in `.github/actions/build-dist` and `.github/actions/publish-dist`, shared with the break-glass `.github/workflows/publish.yml` (a GitHub Release published by a person for a version tag such as `0.3.278`, no `v` prefix) and with `.github/workflows/publish-parity.yml`, which rebuilds the latest PyPI version and compares it with PyPI's files (`verify-parity`). The local break-glass path runs the same gates:

```bash
python scripts/pypi-release.py release {INSPECT_AI_VERSION}
```

Either path downloads the **glibc** binaries from S3 into `src/inspect_ai/binaries/`, bundles them into the wheel as package data, and publishes to PyPI. The musl variants are intentionally **not** bundled — they live on S3 and are fetched at runtime when a musl sandbox is detected (keeps the wheel small for the common case).

## How binaries are resolved at runtime

Injection first detects the sandbox's arch and libc (`recon.detect_sandbox_os` →
`architecture` + `libc`) and resolves the matching artifact name (adding `-musl` for
musl sandboxes). `src/inspect_ai/tool/_sandbox_tools_utils/sandbox.py` then uses a
three-tier fallback:

1. **Local** — looks for the executable in `inspect_ai/binaries/` (only the glibc variants are bundled into the wheel)
2. **S3 download** — if the install is "clean" (no local edits to sandbox tools), downloads from S3, verified against the vendored `SHA256SUMS` (this is the normal path for the musl variants)
3. **Local build** — prompts the user to build locally via Docker (`--musl` for the musl variant)

The install state detection (`_get_install_state`) determines which tiers are attempted:

- **pypi** install → expects binary in package, warns if missing
- **clean** editable install → tries S3 download
- **edited** editable install → builds a `-dev` suffixed binary locally

## Key files

| File | Purpose |
|------|---------|
| `src/inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt` | Version (simple integer) |
| `src/inspect_ai/tool/_sandbox_tools_utils/SHA256SUMS` | Pinned digests for the four published artifacts (written by `upload_to_s3.py`; see `BINARY_INTEGRITY.md`) |
| `.github/workflows/sandbox-tools-build.yml` | Release build (dispatched by a maintainer) |
| `src/inspect_ai/tool/_sandbox_tools_utils/build_within_container.py` | Build orchestrator |
| `src/inspect_ai/tool/_sandbox_tools_utils/Dockerfile.pyinstaller{,.musl}` | Builder images (base images pinned by digest) |
| `src/inspect_ai/tool/_sandbox_tools_utils/requirements.{in,txt}` | Hashed lock of the Python packages the builders install |
| `src/inspect_ai/tool/_sandbox_tools_utils/conda-{amd64,arm64}.lock`, `lock_conda_env.py` | The glibc builder's conda env, and its regenerate script |
| `src/inspect_ai/tool/_sandbox_tools_utils/build_executable.py` | Runs inside Docker container |
| `src/inspect_ai/tool/_sandbox_tools_utils/validate_distros.py` | Cross-distro validation |
| `src/inspect_ai/tool/_sandbox_tools_utils/sandbox.py` | Runtime resolution and injection |
| `scripts/pypi-release.py` | PyPI release script (downloads from S3) |
