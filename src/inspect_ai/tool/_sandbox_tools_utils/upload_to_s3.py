#!/usr/bin/env python3
"""Upload sandbox tools executables to S3 for a given version.

Single writer of the vendored ``SHA256SUMS`` file: computes digests of the
four local artifacts, refuses to overwrite a published version with different
bytes, rewrites ``SHA256SUMS`` before uploading, and round-trip verifies each
uploaded object. The rewritten sums file must be committed to the release PR
alongside the version bump. See
``src/inspect_sandbox_tools/design/BINARY_INTEGRITY.md``.
"""

import argparse
import hashlib
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

# Mypy follows the package import; runtime supports both module import and plain-file
# execution.
if TYPE_CHECKING:
    from inspect_ai.tool._sandbox_tools_utils._build_config import (
        SandboxToolsArch,
        SandboxToolsBuildConfig,
        config_to_filename,
    )
    from inspect_ai.tool._sandbox_tools_utils._digests import (
        SHA256SUMS_PATH,
        write_sha256sums,
    )
else:
    try:
        from ._build_config import (
            SandboxToolsArch,
            SandboxToolsBuildConfig,
            config_to_filename,
        )
        from ._digests import SHA256SUMS_PATH, write_sha256sums
    except ImportError:
        from _build_config import (
            SandboxToolsArch,
            SandboxToolsBuildConfig,
            config_to_filename,
        )
        from _digests import SHA256SUMS_PATH, write_sha256sums

BINARIES_DIR = Path(__file__).parent.parent.parent / "binaries"
VERSION_FILE = Path(__file__).parent / "sandbox_tools_version.txt"
S3_BUCKET = "s3://inspect-sandbox-tools/"  # Region: us-east-2
BUCKET_BASE_URL = "https://inspect-sandbox-tools.s3.us-east-2.amazonaws.com"
ARCHS: tuple[SandboxToolsArch, ...] = ("amd64", "arm64")

_CHUNK_SIZE = 1 << 20


def _sha256_of_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _sha256_of_s3_object(filename: str) -> str | None:
    """Return the digest of a published object, or None if it isn't published.

    Objects are public-read, so this needs no credentials.
    """
    try:
        hasher = hashlib.sha256()
        with urllib.request.urlopen(
            f"{BUCKET_BASE_URL}/{filename}", timeout=120
        ) as response:
            for chunk in iter(lambda: response.read(_CHUNK_SIZE), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return None
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload sandbox tools to S3")
    parser.add_argument("version", type=int, help="Version number to upload")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the version guard, hashing, immutability check, and SHA256SUMS "
        "write (all credential-free), but skip the upload and round-trip verify.",
    )
    args = parser.parse_args()

    # Version guard: the sums file is keyed to the committed pinned version, so
    # uploading digests for any other version would desync the two.
    committed_version = VERSION_FILE.read_text().strip()
    if str(args.version) != committed_version:
        print(
            f"Error: version argument v{args.version} does not match the committed "
            f"{VERSION_FILE.name} (v{committed_version}). Bump the version file "
            f"first; the SHA256SUMS this script writes must match it.",
            file=sys.stderr,
        )
        sys.exit(1)

    # All four artifacts: arch x {glibc, musl}. The glibc variants are also
    # bundled into the wheel; the musl variants live on S3 only and are fetched at
    # runtime when a musl sandbox is detected.
    filenames = [
        config_to_filename(
            SandboxToolsBuildConfig(
                arch=arch, version=args.version, suffix=None, musl=musl
            )
        )
        for arch in ARCHS
        for musl in [False, True]
    ]

    # Compute digests (and check existence) of all local artifacts upfront so a
    # missing one aborts before anything is published.
    digests: dict[str, str] = {}
    for filename in filenames:
        filepath = BINARIES_DIR / filename
        if not filepath.exists():
            print(f"Error: {filepath} not found", file=sys.stderr)
            sys.exit(1)
        print(f"Hashing {filename}...")
        digests[filename] = _sha256_of_file(filepath)

    # Immutability guard: a published version's bytes must never change —
    # released wheels vendor its digests forever. Re-uploading identical bytes
    # is fine (idempotent retry after a partial upload). Deliberately no
    # --force escape hatch.
    for filename in filenames:
        print(f"Checking S3 for existing {filename}...")
        existing = _sha256_of_s3_object(filename)
        if existing is not None and existing != digests[filename]:
            print(
                f"Error: {filename} is already published with different bytes "
                f"(published {existing}, local {digests[filename]}). Published "
                f"versions are immutable — bump the version and publish fresh "
                f"artifacts instead of overwriting.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Write the sums file before uploading: a crash mid-upload then leaves a
    # correct committable file, and the CI release gate stays red until the
    # upload is completed/retried.
    write_sha256sums(digests)
    print(f"Wrote {SHA256SUMS_PATH}")

    if args.dry_run:
        print("Dry run: skipping upload and round-trip verify. Not committable")
        print("until a real upload publishes these artifacts.")
        return

    for filename in filenames:
        cmd = [
            "aws",
            "s3",
            "cp",
            str(BINARIES_DIR / filename),
            S3_BUCKET,
            "--acl",
            "public-read",
        ]
        print(f"Uploading {filename}...")
        subprocess.run(cmd, check=True)

    # Round-trip verify: catches truncation and eventual-consistency surprises
    # before the operator walks away.
    for filename in filenames:
        print(f"Verifying uploaded {filename}...")
        uploaded = _sha256_of_s3_object(filename)
        if uploaded != digests[filename]:
            print(
                f"Error: uploaded {filename} does not match the local digest "
                f"(uploaded {uploaded}, local {digests[filename]}). Retry the "
                f"upload before committing SHA256SUMS.",
                file=sys.stderr,
            )
            sys.exit(1)

    print("Done. Now commit the rewritten digest file to the release PR branch:")
    print(f"  git add {SHA256SUMS_PATH}")
    print(f'  git commit -m "Update SHA256SUMS for v{args.version}"')


if __name__ == "__main__":
    main()
