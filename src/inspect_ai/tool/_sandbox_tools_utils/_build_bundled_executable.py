"""
Bundled executable builder

This module contains the core PyInstaller build logic, separated from environment
setup and CLI concerns. It focuses purely on:
1. Building a --onedir bundle with PyInstaller
2. Packaging that directory tree as a tar artifact
3. Verifying the final build

This module has no knowledge of container structure, volume mounts, or repository
layout. It receives clean, simple parameters and produces a tar of the onedir tree.

A --onedir bundle (rather than --onefile + StaticX) is used so that nothing
self-extracts at runtime: the directory lives on disk in the container and the
launcher runs against the already-extracted ``_internal`` tree. This removes the
per-``exec`` unpack cost. The price is that the bundle relies on the host's matching
libc (glibc or musl), so the build base image sets the portability floor.
"""

import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from inspect_ai.tool._sandbox_tools_utils._build_config import (
        SANDBOX_TOOLS_BASE_NAME,
        SandboxToolsBuildConfig,
        filename_to_config,
    )
else:
    from _build_config import (
        SANDBOX_TOOLS_BASE_NAME,
        SandboxToolsBuildConfig,
        filename_to_config,
    )


def build_bundled_executable(
    entrypoint: Path,
    output_path: Path,
    output_filename: str,
    archive_viewer: bool,
) -> None:
    """
    Build a --onedir PyInstaller bundle and package it as a tar artifact.

    WORKFLOW:
    1. Verify PyInstaller is available
    2. Execute PyInstaller to produce a --onedir bundle (launcher + _internal/)
    3. Pack the bundle's tree into a gzipped tar at output_path
    4. Verify the launcher runs and display compatibility information

    OUTPUT:
    A gzipped tar of the onedir tree. Its entries are rooted at the tree
    contents (the launcher plus the ``_internal`` directory), so extracting with
    ``tar xzf - -C <dir>`` lands the launcher at ``<dir>/inspect-sandbox-tools``.
    The launcher is named with the stable base name (not the versioned filename)
    so its in-container path is version-independent; the versioned filename is only
    the name of the tar artifact.

    COMPATIBILITY:
    - Requires the same libc family as the build variant (glibc or musl) at a version
      compatible with the build image. The build base image therefore sets the runtime
      portability floor.

    Args:
        entrypoint: Path to the main Python script entry point
        output_path: Final path where the tar artifact should be written
        output_filename: Artifact filename to derive build configuration from
        archive_viewer: Whether to generate pyi-archive_viewer output for debugging.
            Creates a .txt file with the same name as the artifact containing
            the launcher's archive contents listing.

    Raises:
        RuntimeError: If PyInstaller fails or the launcher smoke test fails
        FileNotFoundError: If PyInstaller is not available
    """
    # Create build config from filename
    build_config: SandboxToolsBuildConfig = filename_to_config(output_filename)
    print(
        f"Configuration: arch={build_config.arch}, version={build_config.version}, suffix={build_config.suffix}"
    )

    # Verify PyInstaller is available
    _ensure_pyinstaller_available()

    # Build the --onedir bundle. The launcher inside is named with the stable base
    # name so its in-container path does not depend on arch/version.
    dist_dir = _build_executable(entrypoint, SANDBOX_TOOLS_BASE_NAME)

    # Generate pyi-archive_viewer output if requested
    if archive_viewer:
        archive_viewer_txt = _generate_archive_viewer_output(
            dist_dir / SANDBOX_TOOLS_BASE_NAME
        )
        target_txt = output_path.with_suffix(".txt")
        if archive_viewer_txt.exists():
            shutil.copy2(str(archive_viewer_txt), str(target_txt))
            print(f"✅ Archive viewer output copied to: {target_txt}")
        else:
            print(f"⚠️ Archive viewer output not found: {archive_viewer_txt}")

    # Package the onedir tree as a gzipped tar
    print("[5/5] Packaging onedir tree as gzipped tar...")
    _tar_onedir(dist_dir, output_path)

    # Verify the build
    _verify_build(dist_dir, build_config)


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
    launcher_name: str,
) -> Path:
    """
    Execute PyInstaller to create a --onedir bundle.

    The resulting bundle is a directory containing the launcher executable plus an
    ``_internal`` directory of the interpreter, libraries, and frozen modules. Unlike
    --onefile, it does NOT self-extract at runtime — the launcher runs directly
    against the on-disk tree.

    Args:
        entrypoint: Path to the main Python script
        launcher_name: Name for the launcher executable inside the bundle

    Returns:
        Path to the built bundle directory (``dist/<launcher_name>``)
    """
    print("[4/4] Building PyInstaller onedir bundle")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onedir",  # Directory bundle - no per-run self-extraction
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
        launcher_name,
    ] + [str(entrypoint)]

    print("# PyInstaller command:")
    print(" ".join(cmd))

    _run(cmd)

    # Return path to the built onedir bundle directory
    return Path("dist") / launcher_name


def _tar_onedir(dist_dir: Path, output_path: Path) -> None:
    """Pack the onedir tree as a gzipped tar.

    Entries are rooted at the tree contents (the launcher and ``_internal``), not at
    ``dist_dir`` itself, so ``tar xzf - -C <dir>`` lands the launcher directly at
    ``<dir>/inspect-sandbox-tools``. Uses Python's ``tarfile`` so the build is portable
    and file permissions (launcher 0755, libs 0644) are preserved from the filesystem.

    Gzip roughly halves the artifact, which matters for the per-injection base64
    transfer over `sandbox.exec` and for S3 downloads. Injection extracts with
    ``tar xzf``, with a host-side fallback for containers whose ``tar`` lacks gzip
    support (see ``sandbox._extract_tools_tree``).
    """
    if output_path.exists():
        output_path.unlink()
    with tarfile.open(output_path, "w:gz") as tar:
        for entry in sorted(dist_dir.iterdir()):
            tar.add(str(entry), arcname=entry.name)


def _verify_build(dist_dir: Path, build_config: SandboxToolsBuildConfig) -> None:
    """
    Verify the onedir launcher runs and display build information.

    Args:
        dist_dir: Path to the built onedir bundle directory
        build_config: Build configuration for architecture messaging
    """
    launcher = dist_dir / SANDBOX_TOOLS_BASE_NAME

    # Show what we built
    try:
        subprocess.run(["ls", "-lh", str(launcher)], check=True)
        subprocess.run(["file", str(launcher)], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Smoke test: dispatch the in-process `version` method, which needs no server.
    # This confirms the onedir launcher executes Python against its _internal tree.
    print("Smoke-testing onedir launcher...")
    smoke = subprocess.run(
        [str(launcher), "exec"],
        input='{"jsonrpc": "2.0", "method": "version", "id": 1}',
        text=True,
        capture_output=True,
    )
    if smoke.returncode != 0:
        raise RuntimeError(
            f"onedir launcher smoke test failed (exit {smoke.returncode}): {smoke.stderr}"
        )
    print(f"✅ launcher runs: {smoke.stdout.strip()[:200]}")

    arch_word = "ARM64/aarch64" if build_config.arch == "arm64" else "x86_64"
    print(
        f"✅ Portable onedir bundle ready for {arch_word}. "
        "Runs on Linux with glibc >= the build glibc (conda-forge / 2.17)."
    )


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
