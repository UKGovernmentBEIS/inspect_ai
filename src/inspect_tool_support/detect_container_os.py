#!/usr/bin/env python3

# TODO: This file has been replaced by src/inspect_ai/tool/_tool_support_sandbox.py
# this one remains simply for the test_distros.sh shell script. Migrate that script
# to use _tool_support_sandbox.py

import argparse
import json
import subprocess
import sys
from typing import Any, Dict, Optional


def run_docker_exec(container_id: str, command: str) -> Optional[str]:
    """Execute a command in the container and return the output."""
    try:
        result = subprocess.run(
            ["docker", "exec", container_id, "sh", "-c", command],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
        FileNotFoundError,
    ):
        return None


def detect_architecture(container_id: str) -> str:
    """Detect the architecture of the container."""
    arch_cmd = """
if command -v uname >/dev/null 2>&1; then
    uname -m
else
    echo "unknown"
fi
"""

    arch_output = run_docker_exec(container_id, arch_cmd)
    if not arch_output:
        return "Unknown (uname not available)"

    arch = arch_output.lower()
    arch_mapping = {
        "x86_64": "x86_64 (amd64)",
        "amd64": "x86_64 (amd64)",
        "aarch64": "aarch64 (arm64)",
        "arm64": "aarch64 (arm64)",
        "armv7l": "armv7l (armhf)",
        "armhf": "armv7l (armhf)",
        "i386": "i386",
        "i686": "i386",
    }

    return arch_mapping.get(arch, arch)


def detect_windows(container_id: str) -> Optional[Dict[str, Any]]:
    """Detect Windows OS information."""
    # Check if cmd is available
    if not run_docker_exec(
        container_id, "command -v cmd >/dev/null 2>&1 && echo 'found'"
    ):
        return None

    result = {"os": "Windows"}

    # Try to get version info
    version_cmd = "cmd /c ver 2>/dev/null"
    version_output = run_docker_exec(container_id, version_cmd)
    if version_output:
        result["version"] = version_output
    else:
        # Try PowerShell version
        ps_cmd = 'powershell -Command "$PSVersionTable.PSVersion" 2>/dev/null'
        ps_output = run_docker_exec(container_id, ps_cmd)
        if ps_output:
            result["version"] = ps_output

    # Get architecture
    arch_cmd = 'powershell -Command "echo $env:PROCESSOR_ARCHITECTURE" 2>/dev/null'
    arch_output = run_docker_exec(container_id, arch_cmd)
    if arch_output:
        result["architecture"] = arch_output
    else:
        result["architecture"] = "Unknown (PowerShell not available)"

    return result


def detect_macos(container_id: str) -> Optional[Dict[str, Any]]:
    """Detect macOS information."""
    if not run_docker_exec(
        container_id, "command -v sw_vers >/dev/null 2>&1 && echo 'found'"
    ):
        return None

    result = {"os": "macOS"}

    sw_vers_output = run_docker_exec(container_id, "sw_vers")
    if sw_vers_output:
        result["version_info"] = sw_vers_output

    result["architecture"] = detect_architecture(container_id)

    return result


def detect_linux(container_id: str) -> Dict[str, Any]:
    """Detect Linux distribution information."""
    result = {"os": "Linux"}

    # Check /etc/os-release first
    os_release_cmd = """
if [ -f /etc/os-release ]; then
    cat /etc/os-release
else
    echo "not_found"
fi
"""

    os_release_output = run_docker_exec(container_id, os_release_cmd)
    if os_release_output and os_release_output != "not_found":
        # Parse os-release file
        os_info = {}
        for line in os_release_output.split("\n"):
            if "=" in line:
                key, value = line.split("=", 1)
                os_info[key] = value.strip('"')

        distro_id = os_info.get("ID", "").lower()
        name = os_info.get("NAME", "Unknown")
        version = os_info.get("VERSION", "Unknown")

        if distro_id == "ubuntu":
            result["distribution"] = "Ubuntu"
        elif distro_id == "debian":
            result["distribution"] = "Debian"
        elif distro_id == "kali":
            result["distribution"] = "Kali Linux"
        else:
            result["distribution"] = f"Other Linux ({name})"

        result["version"] = version
        result["architecture"] = detect_architecture(container_id)
        return result

    # Fallback: check for Kali version file
    kali_version = run_docker_exec(
        container_id, "[ -f /etc/kali_version ] && cat /etc/kali_version"
    )
    if kali_version:
        result["distribution"] = "Kali Linux"
        result["version"] = kali_version
        result["architecture"] = detect_architecture(container_id)
        return result

    # Fallback: check for Debian version file
    debian_version = run_docker_exec(
        container_id, "[ -f /etc/debian_version ] && cat /etc/debian_version"
    )
    if debian_version:
        result["distribution"] = "Debian-based"
        result["version"] = debian_version
        result["architecture"] = detect_architecture(container_id)
        return result

    # Last resort: try uname
    result["distribution"] = "Other/Unknown"
    result["architecture"] = detect_architecture(container_id)

    uname_output = run_docker_exec(container_id, "uname -a 2>/dev/null")
    if uname_output:
        result["uname"] = uname_output
    else:
        result["uname"] = "Could not determine OS"

    return result


def detect_container_os(container_id: str) -> Dict[str, Any]:
    """Main function to detect the OS and architecture of a container."""
    # Try Windows first
    windows_info = detect_windows(container_id)
    if windows_info:
        return windows_info

    # Try macOS
    macos_info = detect_macos(container_id)
    if macos_info:
        return macos_info

    # Default to Linux detection
    return detect_linux(container_id)


def format_output(info: Dict[str, Any], output_format: str = "text") -> str:
    """Format the output in the specified format."""
    if output_format == "json":
        return json.dumps(info, indent=2)

    # Text format (similar to original script)
    lines = []

    # For Linux distributions, show the distribution as the OS (like the original script)
    if "distribution" in info:
        lines.append(f"OS: {info['distribution']}")
    elif "os" in info:
        lines.append(f"OS: {info['os']}")

    if "version" in info:
        lines.append(f"Version: {info['version']}")

    if "version_info" in info:
        lines.append(info["version_info"])

    if "architecture" in info:
        lines.append(f"Architecture: {info['architecture']}")

    if "uname" in info:
        lines.append(info["uname"])

    return "\n".join(lines)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Detect the OS and architecture of a Docker container",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example: python detect_container_os.py my_container",
    )
    parser.add_argument("container_id", help="Docker container ID or name")
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress error messages")

    args = parser.parse_args()

    try:
        # Check if Docker is available
        subprocess.run(["docker", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        if not args.quiet:
            print("Error: Docker is not available or not running", file=sys.stderr)
        sys.exit(1)

    try:
        info = detect_container_os(args.container_id)
        output = format_output(info, args.format)
        print(output)
    except Exception as e:
        if not args.quiet:
            print(f"Error detecting container OS: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
