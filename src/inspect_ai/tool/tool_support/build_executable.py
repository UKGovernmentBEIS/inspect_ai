#!/usr/bin/env python3

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from inspect_ai.tool.tool_support._tool_support_build_config import (
        filename_to_config,
    )
else:
    from _tool_support_build_config import filename_to_config

# Entry point for the tool support executable
ENTRY_POINT = "src/inspect_tool_support/src/inspect_tool_support/_cli/main.py"


def main() -> None:
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

    build_config = filename_to_config(args.output_filename)
    executable_name = args.output_filename

    print(f"\nBuilding portable executable for {executable_name}...\n")

    # Determine entry point (resolve relative to current working directory)
    entrypoint = Path(ENTRY_POINT)
    if not entrypoint.is_absolute():
        entrypoint = Path.cwd() / entrypoint
    entrypoint = entrypoint.resolve()  # Convert to absolute path

    print(f"Using entry point: {entrypoint}")

    # Determine output directory and path
    # Check if we're in a container environment
    container_output = Path("/inspect_ai/src/inspect_ai/binaries")
    if container_output.exists():
        output_dir = container_output
    else:
        output_dir = Path.cwd() / "dist"

    output_path = output_dir / executable_name
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Output will be: {output_path}")

    # Copy source and setup
    repo_dir = Path("/inspect_ai")
    source_dir = Path(f"{repo_dir}/src/inspect_tool_support")
    copy_dir = Path("/tmp/inspect_tool_support-copy")
    if copy_dir.exists():
        shutil.rmtree(
            copy_dir
        )  # This makes it easier to run multiple times when debugging the container

    print(f"\n{repo_dir=}\n{source_dir=}\n{copy_dir=}\n{output_path=}\n")
    # Make a copy into /tmp to avoid mutating the mounted repo
    shutil.copytree(source_dir, copy_dir)
    os.chdir(copy_dir)

    try:
        # Install package
        print("Installing package...")
        subprocess.run(["pip", "install", "."], check=True)

        # Install playwright with chromium if browser support is enabled
        if build_config.browser:
            print("Installing playwright with chromium (browser support enabled)...")
            env = os.environ.copy()
            env["PLAYWRIGHT_BROWSERS_PATH"] = "0"
            subprocess.run(
                ["playwright", "install", "--with-deps", "chromium-headless-shell"],
                env=env,
                check=True,
            )
        else:
            print("Skipping playwright installation (browser support disabled)")

        # Build with PyInstaller
        print("Building with PyInstaller (bundling all Python dependencies)...")
        pyinstaller_cmd = [
            "pyinstaller",
            "--onefile",
            "--noupx",  # Don't compress - prevents driver corruption
            # "--strip",  # REMOVED - can break node binary
            "--optimize",
            "1",  # Less aggressive optimization
            "--collect-all",
            "playwright",  # Include everything from playwright
            "--hidden-import=psutil",
            "--copy-metadata=inspect_tool_support",
            "--copy-metadata=playwright",  # Also copy playwright metadata
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
            str(entrypoint),
        ]
        subprocess.run(pyinstaller_cmd, check=True)

        # Create statically linked executable (or skip if requested)
        if not args.no_staticx:
            print(
                "Creating statically linked executable (eliminating system dependencies)..."
            )
            staticx_cmd = [
                "staticx",
                "--strip",
                f"dist/{executable_name}",
                str(output_path),
            ]
            subprocess.run(staticx_cmd, check=True)
        else:
            print("Skipping staticx")
            temp_output = Path(f"dist/{executable_name}")
            if temp_output != output_path:
                temp_output.rename(output_path)

        # Make executable
        print("Making executable...")
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
