"""
PYINSTALLER BUILDER MODULE

This module contains the core PyInstaller build logic, separated from environment
setup and CLI concerns. It focuses purely on:
1. Building executables with PyInstaller
2. Applying StaticX for portability
3. Verifying the final build

This module has no knowledge of container structure, volume mounts, or repository
layout. It receives clean, simple parameters and produces a portable executable.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from inspect_ai.tool.tool_support._playwright_support import (
        stage_playwright_dependencies,
    )
    from inspect_ai.tool.tool_support._tool_support_build_config import BuildConfig
else:
    from _playwright_support import stage_playwright_dependencies
    from _tool_support_build_config import BuildConfig


def build(
    entrypoint: Path,
    output_path: Path,
    build_config: BuildConfig,
    build_working_dir: Path,
    apply_staticx: bool = True,
) -> None:
    """
    Build a portable executable using PyInstaller with optional browser support.

    WORKFLOW:
    1. Stage browser dependencies if browser support is enabled (via playwright_support)
    2. Execute PyInstaller to bundle Python application and all dependencies
    3. Optionally apply StaticX for maximum cross-distribution portability
    4. Verify the final executable and display compatibility information

    OUTPUT:
    A single executable file that contains:
    - Embedded Python interpreter
    - The Python application code
    - All required shared libraries and dependencies
    - Optionally: Playwright library and Chromium browser with all dependencies

    COMPATIBILITY:
    - Requires same or newer glibc version as build system (core glibc libraries are
      excluded to maintain ABI compatibility)
    - StaticX creates fully static executables for maximum portability across
      different Linux distributions

    Args:
        entrypoint: Path to the main Python script entry point
        output_path: Final path where the executable should be placed
        build_config: Build configuration specifying architecture, browser support, etc.
        build_working_dir: Working directory where temporary build files are staged
        apply_staticx: Whether to apply StaticX for maximum portability (default: True)

    Raises:
        RuntimeError: If PyInstaller fails or StaticX processing fails
        FileNotFoundError: If required tools (PyInstaller, StaticX) are not available
    """
    # Stage playwright dependencies if browser support is enabled
    extra_dependencies = (
        stage_playwright_dependencies(build_working_dir) if build_config.browser else []
    )

    # Build the executable with PyInstaller
    temp_output = _build_executable(extra_dependencies, entrypoint, output_path.name)

    # Apply staticx for maximum portability (or just move if skipping)
    if apply_staticx:
        print("[5/5] Applying staticx for maximum portability...")
        _apply_staticx(temp_output, output_path)
    else:
        print("[5/5] Skipping staticx")
        if temp_output != output_path:
            temp_output.rename(output_path)

    # Set executable permissions
    output_path.chmod(0o755)

    # Verify the build
    _verify_build(output_path, output_path.name, build_config)


def _run(
    cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None
) -> str:
    """Run a subprocess command and return stdout."""
    return subprocess.run(
        cmd, cwd=cwd, env=env, text=True, capture_output=True, check=True
    ).stdout


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

    # Run PyInstaller in the current directory
    _run(cmd, env=env)

    # Return path to built executable
    return Path("dist") / executable_name


def _apply_staticx(input_path: Path, output_path: Path) -> None:
    """Apply StaticX to make the executable fully static."""
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
