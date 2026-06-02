#!/usr/bin/env python3
"""Upload sandbox tools executables to S3 for a given version."""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal

# Run as a plain file (python upload_to_s3.py), so the runtime import is the bare
# sibling module; mypy follows the absolute import (matches _build_bundled_executable.py).
if TYPE_CHECKING:
    from inspect_ai.tool._sandbox_tools_utils._build_config import (
        SandboxToolsBuildConfig,
        config_to_filename,
    )
else:
    from _build_config import SandboxToolsBuildConfig, config_to_filename

BINARIES_DIR = Path(__file__).parent.parent.parent / "binaries"
S3_BUCKET = "s3://inspect-sandbox-tools/"  # Region: us-east-2
ARCHS: list[Literal["amd64", "arm64"]] = ["amd64", "arm64"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload sandbox tools to S3")
    parser.add_argument("version", type=int, help="Version number to upload")
    args = parser.parse_args()

    # Upload all four artifacts: arch x {glibc, musl}. The glibc variants are also
    # bundled into the wheel; the musl variants live on S3 only and are fetched at
    # runtime when a musl sandbox is detected.
    for arch in ARCHS:
        for musl in [False, True]:
            filename = config_to_filename(
                SandboxToolsBuildConfig(
                    arch=arch, version=args.version, suffix=None, musl=musl
                )
            )
            filepath = BINARIES_DIR / filename
            if not filepath.exists():
                print(f"Error: {filepath} not found", file=sys.stderr)
                sys.exit(1)

            cmd = [
                "aws",
                "s3",
                "cp",
                str(filepath),
                S3_BUCKET,
                "--acl",
                "public-read",
            ]
            print(f"Uploading {filename}...")
            subprocess.run(cmd, check=True)

    print("Done.")


if __name__ == "__main__":
    main()
