"""
Bundled executable builder

This module contains the core PyInstaller/StaticX build logic, separated from environment
setup and CLI concerns. It focuses purely on:
1. Building executables with PyInstaller
2. Applying StaticX for portability
3. Verifying the final build

This module has no knowledge of container structure, volume mounts, or repository
layout. It receives clean, simple parameters and produces a portable executable.
"""

import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from inspect_ai.tool._sandbox_tools_utils._build_config import (
        SandboxToolsBuildConfig,
        filename_to_config,
    )
else:
    from _build_config import (
        SandboxToolsBuildConfig,
        filename_to_config,
    )


def build_bundled_executable(
    entrypoint: Path,
    output_path: Path,
    output_filename: str,
    no_staticx: bool,
    archive_viewer: bool,
) -> None:
    """
    Build a portable executable using PyInstaller.

    WORKFLOW:
    1. Verify PyInstaller is available
    2. Execute PyInstaller to bundle Python application and all dependencies
    3. Apply StaticX for maximum cross-distribution portability (unless requested not to)
    4. Verify the final executable and display compatibility information

    OUTPUT:
    A single executable file that contains:
    - Embedded Python interpreter
    - The Python application code
    - All required shared libraries and dependencies

    COMPATIBILITY:
    - Requires same or newer glibc version as build system (core glibc libraries are
      excluded to maintain ABI compatibility)
    - StaticX creates fully static executables for maximum portability across
      different Linux distributions

    Args:
        entrypoint: Path to the main Python script entry point
        output_path: Final path where the executable should be placed
        output_filename: Executable filename to derive build configuration from
        no_staticx: Whether to skip StaticX for faster builds
        archive_viewer: Whether to generate pyi-archive_viewer output for debugging.
            Creates a .txt file with the same name as the executable containing
            the full archive contents listing.

    Raises:
        RuntimeError: If PyInstaller fails or StaticX processing fails
        FileNotFoundError: If required tools (PyInstaller, StaticX) are not available
    """
    # Create build config from filename
    build_config: SandboxToolsBuildConfig = filename_to_config(output_filename)
    print(
        f"Configuration: arch={build_config.arch}, version={build_config.version}, suffix={build_config.suffix}"
    )

    # Verify PyInstaller is available
    _ensure_pyinstaller_available()

    # Build the executable with PyInstaller
    temp_output = _build_executable(entrypoint, output_path.name)

    # Generate pyi-archive_viewer output if requested
    if archive_viewer:
        archive_viewer_txt = _generate_archive_viewer_output(temp_output)
        # Copy the archive viewer output (.txt) to the output directory
        target_txt = output_path.with_suffix(".txt")
        if archive_viewer_txt.exists():
            shutil.copy2(str(archive_viewer_txt), str(target_txt))
            print(f"✅ Archive viewer output copied to: {target_txt}")
        else:
            print(f"⚠️ Archive viewer output not found: {archive_viewer_txt}")

    # Apply staticx for maximum portability (or just move if skipping)
    if not no_staticx:
        print("[5/5] Applying staticx for maximum portability...")
        _apply_staticx(temp_output, output_path)
    else:
        print("[5/5] Skipping staticx")
        if temp_output != output_path:
            shutil.move(str(temp_output), str(output_path))

    # Set executable permissions
    output_path.chmod(0o755)

    # Verify the build
    _verify_build(output_path, output_path.name, build_config)


def _ensure_pyinstaller_available() -> None:
    """Verify that PyInstaller is available in the current environment."""
    try:
        # Try to run PyInstaller as a module to check if it's available
        _run([sys.executable, "-m", "PyInstaller", "--version"])
    except RuntimeError as e:
        # Provide helpful error message with installation command
        raise RuntimeError(
            "PyInstaller not found in this Python environment. "
            f"Install it with:\n  {sys.executable} -m pip install pyinstaller"
        ) from e


def _build_executable(
    entrypoint: Path,
    executable_name: str,
) -> Path:
    """
    Execute PyInstaller to create the final executable.

    The resulting executable will self-extract to a temporary directory
    at runtime and set up the library paths appropriately.

    Args:
        extra_arguments: List of additional PyInstaller arguments (--add-binary, --exclude-module, etc.)
        entrypoint: Path to the main Python script
        executable_name: Name for the output executable
        custom_env: Optional dictionary of environment variables to use during build

    Returns:
        Path to the built executable
    """
    print("[4/4] Building PyInstaller onefile binary")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",  # Single executable output
        "--noupx",  # Don't compress - prevents driver corruption
        # "--strip",  # REMOVED - can break node binary (consider re-enabling if issues are resolved)
        "--optimize",
        "2",
        "--hidden-import=psutil",
        "--copy-metadata=inspect_sandbox_tools",
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
    ] + [str(entrypoint)]

    print("# PyInstaller command:")
    print(" ".join(cmd))

    _run(cmd)

    # Return path to built executable
    return Path("dist") / executable_name


def _apply_staticx(input_path: Path, output_path: Path) -> None:
    """Apply StaticX to make the executable fully static."""
    # Use a temporary output path in the same directory as input to avoid cross-device issues
    temp_output = input_path.parent / f"{input_path.name}.staticx"

    _run(
        [
            "staticx",
            # "--strip",  # REMOVED - can break node binary (matches PyInstaller --strip removal)
            str(input_path),
            str(temp_output),
        ]
    )

    # Manually copy the result to the final destination
    shutil.copy2(temp_output, output_path)

    # Clean up temporary file
    temp_output.unlink()


def _verify_build(
    output_path: Path, executable_name: str, build_config: SandboxToolsBuildConfig
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


def _generate_archive_viewer_output(output_path: Path) -> Path:
    """Generate a text file with pyi-archive_viewer output for debugging."""
    # Create the .txt file path with the same base name as the executable
    txt_path = output_path.with_suffix(".txt")

    print(f"Generating pyi-archive_viewer output: {txt_path.resolve()}")

    # Run pyi-archive_viewer and capture its output
    result = _run(["pyi-archive_viewer", "--list", "--recursive", str(output_path)])

    # Write the output to the .txt file
    txt_path.write_text(result)
    print(f"✅ Archive viewer output saved to: {txt_path}")

    return txt_path


def _run(
    cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None
) -> str:
    """Run a subprocess command and return stdout."""
    # Stream output to console for user visibility, but still capture for return value
    try:
        result = subprocess.run(
            cmd, cwd=cwd, env=env, text=True, capture_output=True, check=True
        )
        # Print stdout and stderr to console so user sees the output
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return result.stdout
    except subprocess.CalledProcessError as e:
        # Print captured output even when command fails
        if e.stdout:
            print(e.stdout, end="")
        if e.stderr:
            print(e.stderr, end="", file=sys.stderr)
        # Re-raise the exception to preserve error handling
        raise
