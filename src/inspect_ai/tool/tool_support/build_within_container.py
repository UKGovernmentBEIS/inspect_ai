#!/usr/bin/env python3

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path


def get_script_dir() -> Path:
    """Get the directory containing this script."""
    return Path(__file__).parent.absolute()


def read_version() -> str:
    """Read version from VERSION.txt."""
    version_file = Path("VERSION.txt")
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
    platform: str, arch_suffix: str, image_name: str, version: str
) -> None:
    """Run the Docker container to build the executable."""
    print("Starting container and building executable...")

    # Ensure binaries directory exists
    Path("../inspect_ai/binaries").mkdir(exist_ok=True)

    # Find repository root (should be 3 levels up from this script)
    repo_root = get_script_dir().parent.parent.parent

    cmd = [
        "docker",
        "run",
        "--rm",
        "--platform",
        platform,
        "-v",
        f"{repo_root}:/workspace:rw",
        "-w",
        "/workspace/src/inspect_tool_support",
        "-e",
        f"ARCH_SUFFIX={arch_suffix}",
        image_name,
        "python3",
        "/workspace/src/inspect_ai/tool/tool_support/build_executable.py",
        "--version",
        version,
    ]

    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build inspect-tool-support executables in containers"
    )
    parser.add_argument(
        "--arch", choices=["amd64", "arm64"], help="Build for specific architecture"
    )
    parser.add_argument(
        "--all", action="store_true", help="Build for both amd64 and arm64"
    )
    parser.add_argument(
        "--dev",
        type=lambda x: x.lower() == "true",
        default=True,
        nargs="?",
        const=True,
        help="Build development version (adds -dev suffix). Use --dev=false for production builds.",
    )

    args = parser.parse_args()

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
        run_docker_container(platform, arch_suffix, image_name, version)

        print(
            f"Build completed. Executable(s) available in container_build/inspect-tool-support-{arch_suffix}"
        )

    finally:
        # Restore original directory
        os.chdir(original_dir)


if __name__ == "__main__":
    main()
