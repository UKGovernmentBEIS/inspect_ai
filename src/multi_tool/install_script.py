#!/usr/bin/env python3
"""
Post-installation script for inspect-multi-tool package.
Copies the container files to /opt/inspect and the web_browser_back_compat files to /app/web_browser.
"""

import os
import shutil
import sys
from pathlib import Path


def copy_files():
    """Copy files to their intended locations."""
    # Get the source directory (where this script is located)
    # Get the source package directory
    import inspect_multi_tool
    src_dir = Path(inspect_multi_tool.__file__).parent.absolute()
    
    # Copy container files to /opt/inspect
    container_src = src_dir / "container"
    container_dest = Path("/opt/inspect")
    
    # Copy web_browser_back_compat files to /app/web_browser
    web_browser_src = src_dir / "web_browser_back_compat"
    web_browser_dest = Path("/app/web_browser")
    
    # Create destination directories if they don't exist
    os.makedirs(container_dest, exist_ok=True)
    os.makedirs(web_browser_dest, exist_ok=True)
    
    # Copy container files
    print(f"Copying files from {container_src} to {container_dest}")
    for item in container_src.glob("**/*"):
        if item.is_file():
            rel_path = item.relative_to(container_src)
            dest_file = container_dest / rel_path
            os.makedirs(dest_file.parent, exist_ok=True)
            shutil.copy2(item, dest_file)
            print(f"Copied {item} to {dest_file}")
    
    # Copy web_browser_back_compat files
    print(f"Copying files from {web_browser_src} to {web_browser_dest}")
    for item in web_browser_src.glob("**/*"):
        if item.is_file():
            rel_path = item.relative_to(web_browser_src)
            dest_file = web_browser_dest / rel_path
            os.makedirs(dest_file.parent, exist_ok=True)
            shutil.copy2(item, dest_file)
            print(f"Copied {item} to {dest_file}")


if __name__ == "__main__":
    try:
        copy_files()
        print("Files copied successfully.")
    except Exception as e:
        print(f"Error during installation: {e}", file=sys.stderr)
        sys.exit(1)