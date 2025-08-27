#!/usr/bin/env python3

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from ._tool_support_build_config import filename_to_config
except ImportError:
    # Handle direct execution or when run from Docker
    from _tool_support_build_config import filename_to_config


def main() -> None:
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Build portable inspect-tool-support executable"
    )
    parser.add_argument(
        "filename",
        help="Executable filename (e.g., 'inspect-tool-support-amd64-v667-dev')",
    )

    args = parser.parse_args()

    build_config = filename_to_config(args.filename)
    executable_name = args.filename

    print(f"\nBuilding portable executable for {executable_name}...\n")

    # Copy source and setup
    copy_dir = Path("/tmp/inspect_tool_support-copy")
    if copy_dir.exists():
        shutil.rmtree(
            copy_dir
        )  # This makes it easier to run multiple times when debugging the container

    # Copy from the working directory (should be /workspace/inspect_tool_support)
    shutil.copytree(".", copy_dir)
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
            f"/workspace/inspect_ai/binaries/{executable_name}",
        ]
        subprocess.run(staticx_cmd, check=True)

        # Make executable
        print("Making executable...")
        output_path = Path(f"/workspace/inspect_ai/binaries/{executable_name}")
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
