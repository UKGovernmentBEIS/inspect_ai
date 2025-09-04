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
"""

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from inspect_ai.tool.tool_support._pyinstaller_builder import build

if TYPE_CHECKING:
    from inspect_ai.tool.tool_support._tool_support_build_config import (
        BuildConfig,
        filename_to_config,
    )
else:
    from _tool_support_build_config import BuildConfig, filename_to_config

# Directory where this build script is located
SCRIPT_DIR = Path(__file__).parent.resolve()

# Temporary directory where collected libraries will be staged before bundling
BUILD_LIBS = SCRIPT_DIR / "build_libs"


@dataclass
class BuildArgs:
    """Strongly typed representation of command line arguments."""

    entry_point: str
    output_filename: str
    output_dir: str | None
    no_staticx: bool
    working_dir: str | None


def main() -> None:
    """
    Main orchestration function that runs the complete build process.

    This function coordinates all steps in sequence:
    1. Parse command line arguments and build configuration
    2. Verify PyInstaller is available
    3. Conditionally install Chromium into the package directory
    4. Find the headless_shell binary (if browser support enabled)
    5. Collect all required libraries
    6. Build the final executable with PyInstaller
    7. Optionally apply staticx for maximum portability

    The result is a portable executable that includes everything needed
    to run with or without Playwright and Chromium on any compatible Linux system.
    """
    args = _parse_args()

    # Handle output_filename argument and build config
    build_config: BuildConfig = filename_to_config(args.output_filename)
    executable_name = args.output_filename

    print(f"\nBuilding portable executable for {executable_name}...\n")
    print(
        f"Configuration: arch={build_config.arch}, version={build_config.version}, browser={build_config.browser}, suffix={build_config.suffix}"
    )

    # Determine entry point (resolve relative to current working directory)
    entrypoint = Path(args.entry_point)
    if not entrypoint.is_absolute():
        entrypoint = Path.cwd() / entrypoint
    entrypoint = entrypoint.resolve()  # Convert to absolute path

    print(f"Using entry point: {entrypoint}")

    # Determine output directory and path
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        # Check if we're in a container environment
        container_output = Path("/inspect_ai/src/inspect_ai/binaries")
        if container_output.exists():
            output_dir = container_output
        else:
            output_dir = SCRIPT_DIR / "dist"

    output_path = output_dir / executable_name
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Output will be: {output_path}")

    # Handle working directory for container builds
    original_cwd = None
    if args.working_dir:
        original_cwd = Path.cwd()
        working_path = Path(args.working_dir)
        if working_path.exists():
            os.chdir(working_path)
            print(f"Changed working directory to: {working_path}")

    try:
        # Verify build environment
        _ensure_pyinstaller_available()

        # Prepare build environment (copy source and install package)
        build_working_dir = _prepare_build_environment()

        # Build the executable using the new builder module
        build(
            entrypoint=entrypoint,
            output_path=output_path,
            build_config=build_config,
            build_working_dir=build_working_dir,
            apply_staticx=not args.no_staticx,
        )

    finally:
        # Restore original working directory
        if original_cwd:
            os.chdir(original_cwd)


def _parse_args() -> BuildArgs:
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Build portable inspect-tool-support executable"
    )
    parser.add_argument(
        "entry_point",
        help="Path to main.py entry point (relative to current directory or absolute)",
    )
    parser.add_argument(
        "output_filename",
        help="Executable filename (e.g., 'inspect-tool-support-amd64-v667-dev')",
    )
    parser.add_argument(
        "--output-dir", help="Output directory for the built executable"
    )
    parser.add_argument(
        "--no-staticx",
        action="store_true",
        help="Skip staticx processing (reduces portability but faster build)",
    )
    parser.add_argument(
        "--working-dir",
        help="Working directory for the build (for container-based builds)",
    )

    args = parser.parse_args()

    # Convert the untyped Namespace to strongly typed BuildArgs
    return BuildArgs(
        entry_point=args.entry_point,
        output_filename=args.output_filename,
        output_dir=args.output_dir,
        no_staticx=args.no_staticx,
        working_dir=args.working_dir,
    )


def _run(
    cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None
) -> str:
    return subprocess.run(
        cmd, cwd=cwd, env=env, text=True, capture_output=True, check=True
    ).stdout


def _ensure_pyinstaller_available() -> None:
    try:
        # Try to run PyInstaller as a module to check if it's available
        _run([sys.executable, "-m", "PyInstaller", "--version"])
    except RuntimeError as e:
        # Provide helpful error message with installation command
        raise RuntimeError(
            "PyInstaller not found in this Python environment. "
            f"Install it with:\n  {sys.executable} -m pip install pyinstaller"
        ) from e


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


if __name__ == "__main__":
    # Entry point when running as a script
    main()
