#!/usr/bin/env python3
"""
Distribution compatibility validator for inspect-sandbox-tools executables.

This script validates that built executables work across different Linux distributions
by running them in Docker containers with the 'healthcheck' command.

USAGE:
    python -m inspect_ai.tool._sandbox_tools_utils.validate_distros

NOTE: Must be run as a module (with -m flag) to ensure proper package imports.
Run from the inspect_ai source root or with the package installed.
"""

import subprocess
import sys
from pathlib import Path
from typing import List

from inspect_ai.util._sandbox._cli import SANDBOX_TOOLS_BASE_NAME


class Colors:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    BLUE = "\033[0;34m"
    NC = "\033[0m"  # No Color


def print_colored(message: str, color: str = Colors.NC) -> None:
    """Print a colored message to stdout."""
    print(f"{color}{message}{Colors.NC}")


def test_distro(distro: str, executable_path: Path) -> bool:
    """Test a single distro with the given executable."""
    print_colored(f"Testing {distro} with {executable_path.name}", Colors.BLUE)

    # Docker command to test the executable
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{executable_path}:/app/executable:ro",
        distro,
        "bash",
        "-c",
        """
        cd /app
        ./executable healthcheck
        """,
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=False)
        print_colored(f"✓ {distro}: SUCCESS", Colors.GREEN)
        return True
    except subprocess.CalledProcessError:
        print_colored(f"✗ {distro}: FAILED", Colors.RED)
        return False


def find_executables() -> List[Path]:
    """Find available executables in the binaries directory."""
    binaries_dir = Path(__file__).parent.parent.parent / "binaries"
    executables = []

    # Find all executables matching the prefix pattern
    for executable in binaries_dir.glob(f"{SANDBOX_TOOLS_BASE_NAME}-*"):
        # Check if it's for a supported architecture
        if "amd64" in executable.name or "arm64" in executable.name:
            executables.append(executable)

    return executables


def main() -> None:
    """Main execution function."""
    distros = [
        "ubuntu:20.04",
        "ubuntu:22.04",
        "ubuntu:24.04",
        "debian:11",
        "debian:12",
        "kalilinux/kali-rolling:latest",
    ]

    print_colored(
        "Starting compatibility tests across multiple Linux distributions...",
        Colors.BLUE,
    )

    # Find available executables
    executables = find_executables()

    if not executables:
        print_colored(
            "No executables found in binaries/. Run build_within_container.py first.",
            Colors.RED,
        )
        sys.exit(1)

    executable_names = [exe.name for exe in executables]
    print_colored(f"Found executables: {', '.join(executable_names)}", Colors.BLUE)

    # Test results tracking
    total_tests = 0
    passed_tests = 0

    # Test each executable against each distro
    for executable in executables:
        print_colored(f"\n=== Testing {executable.name} ===", Colors.BLUE)

        for distro in distros:
            total_tests += 1
            if test_distro(distro, executable):
                passed_tests += 1
            print()  # Blank line for readability

    # Summary
    print_colored("\n=== TEST SUMMARY ===", Colors.BLUE)
    print(f"Total tests: {total_tests}")
    print_colored(f"Passed: {passed_tests}", Colors.GREEN)
    print_colored(f"Failed: {total_tests - passed_tests}", Colors.RED)

    if passed_tests == total_tests:
        print_colored(
            "\n🎉 All tests passed! Executables are compatible across all tested distributions.",
            Colors.GREEN,
        )
        sys.exit(0)
    else:
        print_colored(
            "\n❌ Some tests failed. Check the output above for details.", Colors.RED
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
