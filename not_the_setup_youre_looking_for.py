#!/usr/bin/env python3
"""Custom setup.py to build executables during package creation."""

import subprocess
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithExecutables(build_py):
    """Custom build command that creates executables before packaging."""

    def run(self):
        """Run the custom build process."""
        self.build_executables()
        super().run()

    def build_executables(self):
        """Build the tool support executables for all architectures."""
        build_script_path = Path("src/inspect_tool_support/build_within_container.py")

        if not build_script_path.exists():
            self.announce(
                f"Warning: Build script not found at {build_script_path}. "
                "Skipping executable build.",
                level=2,
            )
            return

        self.announce("Building tool support executables...", level=1)

        try:
            subprocess.run(
                [sys.executable, str(build_script_path), "--all"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.announce(
                "Successfully built executables for all architectures", level=1
            )

        except subprocess.CalledProcessError as e:
            self.announce(
                f"Failed to build executables: {e}\nstdout: {e.stdout}\nstderr: {e.stderr}",
                level=3,
            )
            raise
        except Exception as e:
            self.announce(f"Error building executables: {e}", level=3)
            raise


# Use the custom build command
setup(cmdclass={"build_py": BuildWithExecutables})
