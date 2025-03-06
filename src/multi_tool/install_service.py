#!/usr/bin/env python3
"""Script to install the multi-tool-server systemd service."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def install_service():
    """Install the systemd service for multi-tool-server."""
    # Get the source directory (where this script is located)
    src_dir = Path(__file__).parent.absolute()
    service_file = src_dir / "multi-tool-server.service"

    # Define the systemd service directory
    systemd_dir = Path("/etc/systemd/system")

    # Create destination directory if it doesn't exist
    if not systemd_dir.exists():
        print(f"Creating directory: {systemd_dir}")
        os.makedirs(systemd_dir, exist_ok=True)

    # Copy service file
    dest_file = systemd_dir / "multi-tool-server.service"
    print(f"Copying {service_file} to {dest_file}")
    shutil.copy2(service_file, dest_file)

    # Reload systemd
    print("Reloading systemd daemon")
    subprocess.run(["systemctl", "daemon-reload"], check=True)

    # Enable and start the service
    print("Enabling and starting multi-tool-server service")
    subprocess.run(["systemctl", "enable", "multi-tool-server"], check=True)
    subprocess.run(["systemctl", "start", "multi-tool-server"], check=True)

    # Check service status
    result = subprocess.run(
        ["systemctl", "status", "multi-tool-server"],
        check=False,
        capture_output=True,
        text=True,
    )
    print(result.stdout)


if __name__ == "__main__":
    # Check if running as root
    if os.geteuid() != 0:
        print("This script must be run as root", file=sys.stderr)
        sys.exit(1)

    try:
        install_service()
        print("Service installed and started successfully.")
    except Exception as e:
        print(f"Error during service installation: {e}", file=sys.stderr)
        sys.exit(1)
