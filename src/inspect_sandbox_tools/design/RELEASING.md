# Releasing `inspect_sandbox_tools`

End-to-end process for shipping a new version of the sandbox tools executables.

## Overview

The sandbox tools are compiled into portable static Linux executables (amd64 + arm64) and distributed via:

1. **S3** — runtime downloads for editable/dev installs
2. **PyPI** — bundled into the `inspect_ai` wheel for pip installs

The version is a simple integer in `src/inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt`.

## Release Steps

### 1. Make code changes

Edit source code under `src/inspect_sandbox_tools/`.

### 2. Bump the version

Increment the integer in:

```
src/inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt
```

### 3. Build executables

Build production binaries for both architectures:

```bash
python src/inspect_ai/tool/_sandbox_tools_utils/build_within_container.py --all --dev=false
```

This creates Docker containers with PyInstaller, builds static executables via StaticX, and places them in `src/inspect_ai/binaries/`:

- `inspect-sandbox-tools-amd64-v{VERSION}`
- `inspect-sandbox-tools-arm64-v{VERSION}`

Requires Docker with multi-architecture support.

### 4. Validate across distros

```bash
python -m inspect_ai.tool._sandbox_tools_utils.validate_distros
```

Tests both executables across Ubuntu, Debian, and Kali Linux containers.

### 5. Upload to S3

Manually upload the built binaries to the S3 bucket:

```bash
aws s3 cp src/inspect_ai/binaries/inspect-sandbox-tools-amd64-v{VERSION} s3://inspect-sandbox-tools/ --acl public-read
aws s3 cp src/inspect_ai/binaries/inspect-sandbox-tools-arm64-v{VERSION} s3://inspect-sandbox-tools/ --acl public-read
```

- **Bucket:** `inspect-sandbox-tools`
- **Region:** `us-east-2`
- **URL pattern:** `https://inspect-sandbox-tools.s3.us-east-2.amazonaws.com/inspect-sandbox-tools-{arch}-v{version}`
- Files must be world-readable (`--acl public-read`) so runtime S3 downloads work without credentials

### 6. Merge the PR

The GitHub Actions workflow (`.github/workflows/build_sandbox_tools.yml`) can build executables on PR, but is currently manual-trigger only (`workflow_dispatch`).

### 7. PyPI release (when releasing inspect_ai)

The `inspect_ai` release script automatically pulls sandbox tools from S3:

```bash
python scripts/pypi-release.py release v{INSPECT_AI_VERSION}
```

This downloads the binaries from S3 into `src/inspect_ai/binaries/`, bundles them into the wheel as package data, and publishes to PyPI.

## How binaries are resolved at runtime

`src/inspect_ai/tool/_sandbox_tools_utils/sandbox.py` uses a three-tier fallback:

1. **Local** — looks for the executable in `inspect_ai/binaries/`
2. **S3 download** — if the install is "clean" (no local edits to sandbox tools), downloads from S3
3. **Local build** — prompts the user to build locally via Docker

The install state detection (`_get_install_state`) determines which tiers are attempted:

- **pypi** install → expects binary in package, warns if missing
- **clean** editable install → tries S3 download
- **edited** editable install → builds a `-dev` suffixed binary locally

## Key files

| File | Purpose |
|------|---------|
| `src/inspect_ai/tool/_sandbox_tools_utils/sandbox_tools_version.txt` | Version (simple integer) |
| `src/inspect_ai/tool/_sandbox_tools_utils/build_within_container.py` | Build orchestrator |
| `src/inspect_ai/tool/_sandbox_tools_utils/build_executable.py` | Runs inside Docker container |
| `src/inspect_ai/tool/_sandbox_tools_utils/validate_distros.py` | Cross-distro validation |
| `src/inspect_ai/tool/_sandbox_tools_utils/sandbox.py` | Runtime resolution and injection |
| `.github/workflows/build_sandbox_tools.yml` | CI build workflow |
| `scripts/pypi-release.py` | PyPI release script (downloads from S3) |
