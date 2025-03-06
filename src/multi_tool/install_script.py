#!/usr/bin/env python3
"""
Post-installation script for inspect-multi-tool package.

Copies the multi_tool files to /opt/inspect and the back_compat/web_browser files to /app/web_browser.
"""

import os
import shutil
import sys
from pathlib import Path


def copy_files():
    """Copy files to their intended locations."""
    try:
        # First try to import from the installed package
        import inspect_multi_tool
        src_dir = Path(inspect_multi_tool.__file__).parent.absolute()
    except ImportError:
        # If not installed, use the script's location
        src_dir = Path(__file__).parent.absolute()

    # Copy multi_tool files to /opt/inspect
    multi_tool_dest = Path("/opt/inspect")

    # Copy back_compat/web_browser files to /app/web_browser
    web_browser_src = src_dir / "back_compat" / "web_browser"
    web_browser_dest = Path("/app/web_browser")

    # Create destination directories if they don't exist
    os.makedirs(multi_tool_dest, exist_ok=True)
    os.makedirs(web_browser_dest, exist_ok=True)

    # Copy multi_tool files - copying all Python files and related modules
    print(f"Copying files from {src_dir} to {multi_tool_dest}")
    
    # List of files to copy directly
    files_to_copy = [
        "__init__.py",
        "_constants.py",
        "_load_tools.py",
        "multi_tool_v1.py",
        "server.py"
    ]
    
    # List of directories to copy recursively
    dirs_to_copy = [
        "_in_process_tools",
        "_remote_tools",
        "_util"
    ]
    
    # Copy individual files
    for file_name in files_to_copy:
        src_file = src_dir / file_name
        if src_file.exists():
            dest_file = multi_tool_dest / file_name
            shutil.copy2(src_file, dest_file)
            print(f"Copied {src_file} to {dest_file}")
            
            # Make Python files executable
            if dest_file.suffix == '.py':
                os.chmod(dest_file, 0o755)
    
    # Copy directories recursively
    for dir_name in dirs_to_copy:
        dir_src = src_dir / dir_name
        dir_dest = multi_tool_dest / dir_name
        
        if dir_src.exists():
            # Create destination directory
            os.makedirs(dir_dest, exist_ok=True)
            
            # Copy files recursively
            for item in dir_src.glob("**/*"):
                if item.is_file() and not any(part.startswith('.') for part in item.parts):
                    rel_path = item.relative_to(dir_src)
                    dest_file = dir_dest / rel_path
                    os.makedirs(dest_file.parent, exist_ok=True)
                    shutil.copy2(item, dest_file)
                    print(f"Copied {item} to {dest_file}")
                    
                    # Make Python files executable
                    if dest_file.suffix == '.py':
                        os.chmod(dest_file, 0o755)

    # Copy web_browser_back_compat files
    print(f"Copying files from {web_browser_src} to {web_browser_dest}")
    if web_browser_src.exists():
        for item in web_browser_src.glob("**/*"):
            if item.is_file() and not any(part.startswith('.') for part in item.parts):
                rel_path = item.relative_to(web_browser_src)
                dest_file = web_browser_dest / rel_path
                os.makedirs(dest_file.parent, exist_ok=True)
                shutil.copy2(item, dest_file)
                print(f"Copied {item} to {dest_file}")
                
                # Make Python files executable
                if dest_file.suffix == '.py':
                    os.chmod(dest_file, 0o755)

    # Create necessary __init__.py files in target directories
    for base_dir in [multi_tool_dest, web_browser_dest]:
        for root, dirs, _ in os.walk(base_dir):
            root_path = Path(root)
            for dir_name in dirs:
                init_file = root_path / dir_name / "__init__.py"
                if not init_file.exists():
                    init_file.touch()
                    print(f"Created {init_file}")


if __name__ == "__main__":
    try:
        copy_files()
        print("Files copied successfully.")
    except Exception as e:
        print(f"Error during installation: {e}", file=sys.stderr)
        sys.exit(1)
