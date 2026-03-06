#!/usr/bin/env python3
"""
Docker-based executable build orchestrator for inspect_sandbox_tools.

This module coordinates the multi-architecture build process for creating portable
Linux executables. It handles Docker container setup, architecture validation, and
delegates the actual build work to build_executable.py running inside containers.

TYPICAL FLOW:
1. Developer/CI runs: python build_within_container.py [--arch amd64|arm64|--all]
2. This script creates PyInstaller-equipped Docker containers for target architectures
3. Mounts repository at /inspect_ai and executes build_executable.py inside container
4. build_executable.py copies source, installs package, and creates executable
5. Final executables placed in src/inspect_ai/binaries/ for runtime injection

EXECUTION CONTEXTS:
- CI/CD pipelines (GitHub Actions)
- Runtime executable rebuilding when binaries missing
- Direct developer usage for testing/development

Supports both amd64 and arm64 Linux architectures with cross-compilation capability.
"""

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Literal

# IMPORT CONTEXT HANDLING:
# This script runs in three different execution contexts:
# 1. GitHub Actions CI/CD - runs from source checkout, package not installed
# 2. inspect_ai runtime - called when executables missing, package installed
# 3. Direct developer usage - various working directories possible
#
# Unlike build_executable.py/_bundled_executable_builder.py (which only run in containers),
# this script needs to work at runtime in both installed and source contexts.
# TYPE_CHECKING pattern won't work here because both import paths need to work
# at runtime, not just during static analysis.
try:
    from ._build_config import SandboxToolsBuildConfig, config_to_filename
except ImportError:
    # Handle direct execution or source checkout contexts
    from _build_config import SandboxToolsBuildConfig, config_to_filename


def get_script_dir() -> Path:
    """Get the directory containing this script."""
    return Path(__file__).parent.absolute()


def read_version() -> str:
    version_file = Path("./sandbox_tools_version.txt")
    try:
        return version_file.read_text().strip()
    except FileNotFoundError:
        print(f"Version file not found: {version_file}", file=sys.stderr)
        sys.exit(1)


def detect_host_architecture() -> tuple[str, str]:
    """Detect host architecture and return (arch_suffix, platform)."""
    arch = platform.machine().lower()
    if arch == "x86_64":
        return "amd64", "linux/amd64"
    elif arch in ("aarch64", "arm64"):
        return "arm64", "linux/arm64"
    else:
        print(f"Unsupported architecture: {arch}", file=sys.stderr)
        sys.exit(1)


def validate_target_architecture(target_arch: str) -> tuple[str, str]:
    """Validate target architecture and return (arch_suffix, platform)."""
    if target_arch == "amd64":
        return "amd64", "linux/amd64"
    elif target_arch == "arm64":
        return "arm64", "linux/arm64"
    else:
        print(f"Unsupported target architecture: {target_arch}", file=sys.stderr)
        print("Supported: amd64, arm64", file=sys.stderr)
        sys.exit(1)


def run_docker_build(platform: str, image_name: str, dockerfile: str) -> None:
    """Build the Docker image."""
    print("Building Docker image...")
    cmd = [
        "docker",
        "build",
        "--platform",
        platform,
        "-t",
        image_name,
        "-f",
        dockerfile,
        ".",
    ]
    subprocess.run(cmd, check=True)


def run_docker_container(
    platform: str,
    arch_suffix: str,
    image_name: str,
    version: str,
    passthrough_args: list[str] | None = None,
) -> None:
    """Run the Docker container to build the executable."""
    print("Starting container and building executable...")

    # Ensure binaries directory exists
    Path("../../binaries").mkdir(exist_ok=True)

    # Find repository root (should be 4 levels up from this script)
    repo_root = get_script_dir().parent.parent.parent.parent

    # Parse version to extract numeric version and suffix
    parts = version.split("-", 1)
    version_num = int(parts[0])
    suffix = parts[1] if len(parts) > 1 else None

    # Validate arch_suffix for BuildConfig
    if arch_suffix not in ["amd64", "arm64"]:
        raise ValueError(
            f"Unexpected architecture suffix '{arch_suffix}'. Only 'amd64' and 'arm64' are supported."
        )

    # Validate suffix for BuildConfig
    if suffix is not None and suffix != "dev":
        raise ValueError(
            f"Unexpected version suffix '{suffix}'. Only 'dev' is supported."
        )

    # Type annotations for BuildConfig literals
    arch: Literal["amd64", "arm64"] = arch_suffix  # type: ignore
    validated_suffix: Literal["dev"] | None = suffix  # type: ignore

    # Create BuildConfig and generate filename
    config = SandboxToolsBuildConfig(
        arch=arch,
        version=version_num,
        suffix=validated_suffix,
    )
    filename = config_to_filename(config)

    cmd = [
        "docker",
        "run",
        "--rm",
        "--platform",
        platform,
        "-v",
        f"{repo_root}:/inspect_ai:rw",
        "-w",
        "/inspect_ai",
        image_name,
        "python3",
        "./src/inspect_ai/tool/_sandbox_tools_utils/build_executable.py",
        filename,
    ]

    # Add passthrough arguments if provided
    if passthrough_args:
        cmd.extend(passthrough_args)

    # Stream output from container to console so user can see build progress
    subprocess.run(cmd, check=True, stdout=None, stderr=None)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build inspect-sandbox-tools executables in containers",
        epilog="Arguments after '--' will be passed through to the script run within the container",
    )
    parser.add_argument(
        "--arch", choices=["amd64", "arm64"], help="Build for specific architecture"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Build for all architectures (amd64/arm64)",
    )
    parser.add_argument(
        "--dev",
        type=lambda x: x.lower() == "true",
        default=True,
        nargs="?",
        const=True,
        help="Build development version (adds -dev suffix). Use --dev=false for production builds.",
    )
    # Container tools does not support browser functionality

    # Parse known args to allow pass-through arguments after "--"
    args, passthrough_args = parser.parse_known_args()

    # Remove any standalone "--" from passthrough args
    passthrough_args = [arg for arg in passthrough_args if arg != "--"]

    # Save original directory
    original_dir = Path.cwd()

    try:
        # Change to script directory
        script_dir = get_script_dir()
        os.chdir(script_dir)

        # Read version and determine if dev build
        base_version = read_version()
        version = f"{base_version}-dev" if args.dev else base_version

        # Handle --all flag or no parameters (default behavior)
        if args.all or (not args.arch):
            print("Building for all architectures...")
            # Recursively call this script for each architecture
            for arch in ["amd64", "arm64"]:
                cmd = [sys.executable, __file__, "--arch", arch]
                if not args.dev:
                    cmd.append("--dev=false")
                # Add passthrough arguments if any
                if passthrough_args:
                    cmd.append("--")
                    cmd.extend(passthrough_args)
                print(f"Building {arch}...")
                subprocess.run(cmd, check=True)
            return

        # Determine target architecture (only when --arch is explicitly specified)
        arch_suffix, platform = validate_target_architecture(args.arch)

        image_name = f"pyinstaller-build-{arch_suffix}"
        dockerfile = "Dockerfile.pyinstaller"

        print(f"Building for architecture: {arch_suffix} (platform: {platform})")

        # Build Docker image
        run_docker_build(platform, image_name, dockerfile)

        # Run container to build executable
        run_docker_container(
            platform, arch_suffix, image_name, version, passthrough_args
        )

        print("Build completed. Executable available in src/inspect_ai/binaries/")

    finally:
        # Restore original directory
        os.chdir(original_dir)


if __name__ == "__main__":
    main()
