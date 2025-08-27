#!/usr/bin/env python3

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

from ._tool_support_build_config import BuildConfig, config_to_filename


def parse_version(version_str: str) -> tuple[int, str | None]:
    """
    Parse version string to extract numeric version and suffix.

    Examples:
        "2" -> (2, None)
        "2-dev" -> (2, "dev")
        "123-dev" -> (123, "dev")
    """
    parts = version_str.split("-", 1)
    try:
        numeric_version = int(parts[0])
    except ValueError:
        print(
            f"Error: Invalid version format '{version_str}'. Expected numeric version optionally followed by -suffix"
        )
        sys.exit(1)

    suffix = parts[1] if len(parts) > 1 else None
    return numeric_version, suffix


def main() -> None:
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Build portable inspect-tool-support executable"
    )
    parser.add_argument(
        "--version", required=True, help="Version string (e.g., '2' or '2-dev')"
    )

    args = parser.parse_args()

    # Get architecture suffix from environment (set by build_within_container.py)
    raw_arch_suffix = os.environ.get("ARCH_SUFFIX", "unknown")

    # Validate and normalize arch_suffix
    if raw_arch_suffix not in ["amd64", "arm64"]:
        raise ValueError(f"Warning: Unexpected ARCH_SUFFIX '{raw_arch_suffix}'")

    # TODO: WTF Python
    arch: Literal["amd64", "arm64"] = raw_arch_suffix  # type: ignore

    # Parse version
    version_num, version_suffix = parse_version(args.version)

    # Validate suffix (must be "dev" or None for BuildConfig)
    if version_suffix is not None and version_suffix != "dev":
        raise ValueError(f"Warning: Unexpected suffix '{version_suffix}'")

    # TODO: WTF Python
    suffix: Literal["dev"] | None = version_suffix  # type: ignore

    # Create build configuration
    # Note: browser flag is not currently used but part of BuildConfig
    config = BuildConfig(
        arch=arch,
        version=version_num,
        browser=False,  # not currently used
        suffix=suffix,
    )

    # Generate executable name using the config
    executable_name = config_to_filename(config)

    print(f"\nBuilding portable executable for {executable_name}...\n")

    # Copy source and setup
    copy_dir = Path("/tmp/inspect_tool_support-copy")
    if copy_dir.exists():
        shutil.rmtree(
            copy_dir
        )  # This makes it easier to run multiple times when debugging the container

    shutil.copytree("/workspace/src/inspect_tool_support", copy_dir)
    os.chdir(copy_dir)

    try:
        # Install package
        print("Installing package...")
        subprocess.run(["pip", "install", "."], check=True)

        # Install playwright with chromium
        env = os.environ.copy()
        env["PLAYWRIGHT_BROWSERS_PATH"] = "0"
        subprocess.run(
            ["playwright", "install", "--with-deps", "chromium"], env=env, check=True
        )

        # Build with PyInstaller
        print("Building with PyInstaller (bundling all Python dependencies)...")
        pyinstaller_cmd = [
            "pyinstaller",
            "--onefile",
            "--strip",
            "--optimize",
            "2",
            "--hidden-import=psutil",
            "--copy-metadata=inspect_tool_support",
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
            "src/inspect_tool_support/_cli/main.py",
        ]
        subprocess.run(pyinstaller_cmd, check=True)

        # Create statically linked executable
        print(
            "Creating statically linked executable (eliminating system dependencies)..."
        )
        staticx_cmd = [
            "staticx",
            "--strip",
            f"dist/{executable_name}",
            f"/workspace/src/inspect_ai/binaries/{executable_name}",
        ]
        subprocess.run(staticx_cmd, check=True)

        # Make executable
        print("Making executable...")
        output_path = Path(f"/workspace/src/inspect_ai/binaries/{executable_name}")
        output_path.chmod(0o755)

        # Verify portability
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
            print("✅ Fully static - maximum portability achieved")

        # Show what we built
        subprocess.run(["ls", "-lh", str(output_path)], check=True)
        subprocess.run(["file", str(output_path)], check=True)

        print(f"✅ Portable executable ready: {executable_name}")
        print("This should run on any Linux x86_64 system from ~2016 onwards")

    except subprocess.CalledProcessError as e:
        print(f"Error during build process: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
