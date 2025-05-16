"""Firecracker sandbox provider for Inspect AI.

This package implements a sandbox provider using Firecracker micro VMs
with Docker Compose to build the rootfs.
"""

from .firecracker import FirecrackerSandboxEnvironment

__all__ = ["FirecrackerSandboxEnvironment"]