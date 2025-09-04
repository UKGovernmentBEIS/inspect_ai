#!/usr/bin/env python3
"""
PORTABLE PYINSTALLER BUILD SCRIPT - CLI AND ENVIRONMENT SETUP

PURPOSE:
This script serves as the command-line interface and environment coordinator for
building portable executables. It handles container-specific setup, argument parsing,
and build environment preparation, then delegates the actual PyInstaller build
process to the _pyinstaller_builder module.

RESPONSIBILITIES:
1. Parse command line arguments and build configuration
2. Handle container-specific paths and volume mounts
3. Prepare build environment (copy source and install package in containers)
4. Delegate to _pyinstaller_builder for all build logic including browser dependencies

CONTAINER USAGE:
Called by build_within_container.py inside Docker containers with the repository
mounted at /inspect_ai. Handles the container-specific workflow of copying source
to /tmp and installing the package before building.

DIRECTORY STRUCTURE REQUIREMENTS:
This script expects to run in a Docker container with the following volume mount:
- inspect_ai repository root mounted at: /inspect_ai

Temporary directories used during build:
- Working copy: /tmp/inspect_tool_support-copy (source copied here to avoid mutation)
- PyInstaller output: /tmp/inspect_tool_support-copy/dist/ (temporary staging)

BUILD OUTPUT:
Final executable is always placed at: /inspect_ai/src/inspect_ai/binaries/<filename>
This ensures the built executable persists back to the host system via the volume mount.
"""

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from inspect_ai.tool.tool_support._pyinstaller_builder import build_executable

# Directory where this build script is located
SCRIPT_DIR = Path(__file__).parent.resolve()

# Entry point for the tool support executable
ENTRY_POINT = "src/inspect_tool_support/src/inspect_tool_support/_cli/main.py"

# Temporary directory where collected libraries will be staged before bundling
BUILD_LIBS = SCRIPT_DIR / "build_libs"


@dataclass
class BuildArgs:
    """Strongly typed representation of command line arguments."""

    output_filename: str
    no_staticx: bool


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
    to run with or without Playwright and Chromium on any compatible Linux system.
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

    build_working_dir = _prepare_build_environment()

    build_executable(
        entrypoint=entrypoint,
        output_path=output_path,
        output_filename=args.output_filename,
        build_working_dir=build_working_dir,
        no_staticx=args.no_staticx,
    )


def _parse_args() -> BuildArgs:
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Build portable inspect-tool-support executable"
    )
    parser.add_argument(
        "output_filename",
        help="Executable filename (e.g., 'inspect-tool-support-amd64-v667-dev')",
    )
    parser.add_argument(
        "--no-staticx",
        action="store_true",
        help="Skip staticx processing (reduces portability but faster build)",
    )

    args = parser.parse_args()

    # Convert the untyped Namespace to strongly typed BuildArgs
    return BuildArgs(
        output_filename=args.output_filename,
        no_staticx=args.no_staticx,
    )


def _prepare_build_environment() -> Path:
    """
    Prepare the build environment by copying source and installing package.

    This matches the workflow from build_executable.py:
    1. Copy /inspect_ai/src/inspect_tool_support to /tmp/inspect_tool_support-copy
    2. Change to the copy directory
    3. Run pip install . to install the package

    Returns:
        Path to the working directory for the build
    """
    # Container paths (matching build_executable.py)
    repo_dir = Path("/inspect_ai")
    source_dir = repo_dir / "src" / "inspect_tool_support"
    copy_dir = Path("/tmp/inspect_tool_support-copy")

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
    print("  (This avoids mutating the mounted repo)")

    # Make a copy into /tmp to avoid mutating the mounted repo
    shutil.copytree(source_dir, copy_dir)

    # Change to the copy directory
    os.chdir(copy_dir)
    print(f"Changed working directory to: {copy_dir}")

    # Install the package
    print("Installing package...")
    _run([sys.executable, "-m", "pip", "install", "."])

    return copy_dir


def _run(
    cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None
) -> str:
    return subprocess.run(
        cmd, cwd=cwd, env=env, text=True, capture_output=True, check=True
    ).stdout


if __name__ == "__main__":
    # Entry point when running as a script
    main()
