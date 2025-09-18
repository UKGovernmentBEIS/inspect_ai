#!/usr/bin/env python3
"""
PYINSTALLER BUILD SCRIPT FOR CONTAINER EXECUTION

This script runs inside Docker build containers to create portable executables for
the inspect_sandbox_tools package. It is typically launched by build_within_container.py
which sets up the container environment and mounts the repository.

EXECUTION CONTEXT:
- Runs inside PyInstaller-equipped Docker containers (linux/amd64 or linux/arm64)
- Repository is mounted at /inspect_ai via Docker volume mount
- Launched by build_within_container.py with appropriate arguments

RESPONSIBILITIES:
1. Parse command line arguments and build configuration
2. Copy source code to temporary directory to avoid mutating mounted repo
3. Install inspect_sandbox_tools package in container environment
4. Delegate PyInstaller executable creation to _build_bundled_executable module
5. Place final executable back into mounted binaries directory

BUILD WORKFLOW:
1. build_within_container.py creates Docker container with PyInstaller environment
2. Repository mounted at /inspect_ai, this script executed inside container
3. Source copied to /tmp/inspect_sandbox_tools-copy for safe building
4. Package installed via pip to ensure all dependencies available
5. PyInstaller creates single-file executable with StaticX for portability
6. Final executable placed at /inspect_ai/src/inspect_ai/binaries/<filename>

The volume mount ensures the built executable persists back to the host system.
"""

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from inspect_ai.tool._sandbox_tools_utils._build_bundled_executable import (
        build_bundled_executable,
    )
else:
    from _build_bundled_executable import build_bundled_executable

# Directory where this build script is located
SCRIPT_DIR = Path(__file__).parent.resolve()

# Entry point for the tool support executable
ENTRY_POINT = "src/inspect_sandbox_tools/src/inspect_sandbox_tools/_cli/main.py"

# Temporary directory where collected libraries will be staged before bundling
BUILD_LIBS = SCRIPT_DIR / "build_libs"


@dataclass
class BuildArgs:
    """Strongly typed representation of command line arguments."""

    output_filename: str
    no_staticx: bool
    archive_viewer: bool


def main() -> None:
    """
    Main orchestration function that runs the complete build process.

    This function coordinates all steps in sequence:
    1. Parse command line arguments and build configuration
    2. Prepare build environment (copy source and install package)
    3. Delegate to the build module for PyInstaller execution

    The build module handles all PyInstaller-specific concerns including:
    - PyInstaller availability verification
    - Browser dependency staging (if enabled)
    - Executable creation with PyInstaller
    - StaticX application for maximum portability

    The result is a portable executable that includes everything needed
    to run on any compatible Linux system.
    """
    args = _parse_args()

    executable_name = args.output_filename
    print(f"\nBuilding portable executable for {executable_name}...\n")

    # Determine entry point (resolve relative to current working directory)
    entrypoint = Path(ENTRY_POINT)
    if not entrypoint.is_absolute():
        entrypoint = Path.cwd() / entrypoint
    entrypoint = entrypoint.resolve()  # Convert to absolute path

    print(f"Using entry point: {entrypoint}")

    # Determine output directory and path
    output_dir = Path("/inspect_ai/src/inspect_ai/binaries")

    output_path = output_dir / executable_name
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Output will be: {output_path}")

    _prepare_build_environment()

    build_bundled_executable(
        entrypoint=entrypoint,
        output_path=output_path,
        output_filename=args.output_filename,
        no_staticx=args.no_staticx,
        archive_viewer=args.archive_viewer,
    )


def _parse_args() -> BuildArgs:
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Build portable inspect-sandbox-tools executable"
    )
    parser.add_argument(
        "output_filename",
        help="Executable filename (e.g., 'inspect-sandbox-tools-amd64-v667-dev'),",
    )
    parser.add_argument(
        "--no-staticx",
        action="store_true",
        help="Skip staticx processing (reduces portability but faster build)",
    )
    parser.add_argument(
        "--archive-viewer",
        action="store_true",
        help="Generate pyi-archive_viewer output for debugging (creates .txt file with archive contents)",
    )

    args = parser.parse_args()

    # Convert the untyped Namespace to strongly typed BuildArgs
    return BuildArgs(
        output_filename=args.output_filename,
        no_staticx=args.no_staticx,
        archive_viewer=args.archive_viewer,
    )


def _prepare_build_environment() -> None:
    """
    Prepare the build environment by copying source and installing package.

    This matches the workflow from build_executable.py:
    1. Copy /inspect_ai/src/inspect_sandbox_tools to /tmp/inspect_sandbox_tools-copy
    2. Change to the copy directory
    3. Run pip install . to install the package
    """
    # Container paths (matching build_executable.py)
    repo_dir = Path("/inspect_ai")
    source_dir = repo_dir / "src" / "inspect_sandbox_tools"
    copy_dir = Path("/tmp/inspect_sandbox_tools-copy")

    # Verify we're in a container environment
    if not source_dir.exists():
        raise FileNotFoundError(
            f"Expected container source directory not found: {source_dir}\n"
            "This function requires the container environment setup."
        )

    # Remove existing copy directory to allow multiple runs
    if copy_dir.exists():
        shutil.rmtree(copy_dir)

    print(f"Copying source from {source_dir} to {copy_dir}")

    # Make a copy into /tmp to avoid mutating the mounted repo
    shutil.copytree(source_dir, copy_dir, ignore=shutil.ignore_patterns(".venv"))

    # Change to the copy directory
    os.chdir(copy_dir)
    print(f"Changed working directory to: {copy_dir}")

    # Install the package
    print("Installing package...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "."],
        check=True,
        stdout=None,
        stderr=None,
    )


if __name__ == "__main__":
    # Entry point when running as a script
    main()
