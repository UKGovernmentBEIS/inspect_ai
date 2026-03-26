#!/usr/bin/env python3
"""Upload sandbox tools executables to S3 for a given version."""

import argparse
import subprocess
import sys
from pathlib import Path

BINARIES_DIR = Path(__file__).parent.parent / "binaries"
S3_BUCKET = "s3://inspect-sandbox-tools/"  # Region: us-east-2
ARCHS = ["amd64", "arm64"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload sandbox tools to S3")
    parser.add_argument("version", type=int, help="Version number to upload")
    args = parser.parse_args()

    for arch in ARCHS:
        filename = f"inspect-sandbox-tools-{arch}-v{args.version}"
        filepath = BINARIES_DIR / filename
        if not filepath.exists():
            print(f"Error: {filepath} not found", file=sys.stderr)
            sys.exit(1)

        cmd = [
            "aws", "s3", "cp",
            str(filepath),
            S3_BUCKET,
            "--acl", "public-read",
        ]
        print(f"Uploading {filename}...")
        subprocess.run(cmd, check=True)

    print("Done.")


if __name__ == "__main__":
    main()
