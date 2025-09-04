#!/usr/bin/env python3
"""
PORTABLE PYINSTALLER BUILD SCRIPT

PURPOSE:
This script uses PyInstaller to create a fully self-contained, portable executable
from a Python application. It supports optional browser integration via Playwright
and Chromium. When browser support is enabled (via build configuration), it
delegates to playwright_hackery.py to handle the complex dependency bundling
required for Chromium.

WORKFLOW:
1. Parse build configuration to determine if browser support is needed
2. Prepare build environment (copy source and install package)
3. Conditionally call playwright_hackery() for browser dependencies
4. Bundle everything into a single executable with PyInstaller
5. Apply StaticX for maximum portability

OUTPUT:
A single executable file that contains:
- Embedded python interpreter
- The python application code
- Optionally: Playwright library and Chromium browser with all dependencies

COMPATIBILITY:
- Requires same or newer glibc version as build system (core glibc libraries are
  excluded to maintain ABI compatibility)
- For true cross-distribution compatibility, StaticX is applied by default
"""

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from inspect_ai.tool.tool_support._playwright_support import (
    stage_playwright_dependencies,
)

# Import build configuration
try:
    from ._tool_support_build_config import BuildConfig, filename_to_config
except ImportError:
    # Handle direct execution or when run from Docker
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

        # Conditionally install browser and collect dependencies
        extra_arguments = (
            stage_playwright_dependencies(build_working_dir)
            if build_config.browser
            else []
        )

        # Build the executable
        temp_output = _build_executable(extra_arguments, entrypoint, executable_name)

        # Apply staticx by default for maximum portability (matching build_executable.py)
        if args.no_staticx:
            print("[5/5] Skipping staticx (--no-staticx specified)")
            # Just move the file to final location
            if temp_output != output_path:
                shutil.move(temp_output, output_path)
        else:
            print("[5/5] Applying staticx for maximum portability...")
            _apply_staticx(temp_output, output_path)

        output_path.chmod(0o755)

        # Verify the build (matching build_executable.py verification)
        _verify_build(output_path, executable_name, build_config)

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


def _build_executable(
    extra_arguments: list[str], entrypoint: Path, executable_name: str
) -> Path:
    """
    Execute PyInstaller to create the final executable.

    The resulting executable will self-extract to a temporary directory
    at runtime and set up the library paths appropriately.

    Args:
        extra_arguments: List of --add-binary arguments for shared libraries
        entrypoint: Path to the main Python script
        executable_name: Name for the output executable

    Returns:
        Path to the built executable
    """
    print("[4/4] Building PyInstaller onefile binary")

    # Set environment to use package-local browser
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = "0"

    # Construct the full PyInstaller command
    cmd = (
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",  # Single executable output
            "--noupx",  # Don't compress - prevents driver corruption
            # "--strip",  # REMOVED - can break node binary (consider re-enabling if issues are resolved)
            "--optimize",
            "2",
            "--collect-all",  # Collect all files from the playwright package
            "playwright",  # Package name for --collect-all
            "--hidden-import=psutil",
            "--copy-metadata=inspect_tool_support",
            "--copy-metadata=playwright",  # Include playwright metadata
            "--exclude-module",
            "tkinter",
            "--exclude-module",
            "test",
            "--exclude-module",
            "unittest",
            "--exclude-module",
            "pdb",
            "--name",
            executable_name,
        ]
        + extra_arguments
        + [str(entrypoint)]
    )  # --add-binary arguments + entry point

    print("# PyInstaller command:")
    print(" ".join(cmd))

    # Run PyInstaller in the current directory (temp directory for container builds)
    _run(cmd, env=env)

    # Return path to built executable
    return Path("dist") / executable_name


def _apply_staticx(input_path: Path, output_path: Path) -> None:
    _run(
        [
            "staticx",
            "--strip",
            str(input_path),
            str(output_path),
        ]
    )


def _verify_build(
    output_path: Path, executable_name: str, build_config: BuildConfig
) -> None:
    """
    Verify the built executable and display build information.

    This matches build_executable.py's verification approach exactly.

    Args:
        output_path: Path to the final executable
        executable_name: Name of the executable
        build_config: Build configuration for architecture messaging
    """
    # Verify portability (matching build_executable.py lines 112-123)
    print("Verifying portability...")
    try:
        result = subprocess.run(
            ["ldd", str(output_path)], capture_output=True, text=True
        )
        if result.returncode != 0:
            print("✅ Fully static - maximum portability achieved")
        else:
            print(result.stdout)
    except FileNotFoundError:
        # ldd not available
        print("⚠️ ldd not available - portability could not be verified")

    # Show what we built (matching build_executable.py lines 125-127)
    try:
        subprocess.run(["ls", "-lh", str(output_path)], check=True)
        subprocess.run(["file", str(output_path)], check=True)
    except subprocess.CalledProcessError:
        # Commands might not be available in some environments
        pass

    # Final success messages (matching build_executable.py lines 129-130)
    print(f"✅ Portable executable ready: {executable_name}")

    # Architecture-specific compatibility message
    if build_config.arch == "arm64":
        print("This should run on any Linux ARM64/aarch64 system from ~2016 onwards")
    else:
        print("This should run on any Linux x86_64 system from ~2016 onwards")


if __name__ == "__main__":
    # Entry point when running as a script
    main()
