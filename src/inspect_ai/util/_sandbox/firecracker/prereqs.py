"""Prerequisite validation for Firecracker sandbox environments.

This module provides functions to check if the necessary prerequisites for
using Firecracker are available in the environment.
"""

import os
import re
import subprocess
from logging import getLogger

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._subprocess import subprocess

# For Docker Compose validation
from ..docker.prereqs import validate_docker_compose

logger = getLogger(__name__)

FIRECRACKER_BINARY = "/usr/bin/firecracker"


async def validate_prereqs() -> None:
    """Validates Firecracker and Docker Compose prerequisites.
    
    This function:
    1. Checks if Firecracker binary is available
    2. Verifies KVM permissions
    3. Validates Docker and Docker Compose (for rootfs creation)
    
    Raises:
        PrerequisiteError: If any prerequisites are not met
    """
    # Check if Firecracker is installed
    if not os.path.exists(FIRECRACKER_BINARY):
        try:
            result = await subprocess(["which", "firecracker"], capture_output=True)
            if not result.success:
                raise PrerequisiteError(
                    "Firecracker binary not found. Please install Firecracker."
                )
        except Exception:
            raise PrerequisiteError(
                "Firecracker binary not found. Please install Firecracker."
            )
    
    # Check KVM access
    if not os.path.exists("/dev/kvm"):
        raise PrerequisiteError(
            "/dev/kvm does not exist. KVM support is required for Firecracker."
        )
    
    try:
        # Check if current user has access to /dev/kvm
        result = await subprocess(["test", "-r", "/dev/kvm"], capture_output=True)
        if not result.success:
            raise PrerequisiteError(
                "Current user does not have read access to /dev/kvm. "
                "Please add the user to the kvm group or grant appropriate permissions."
            )
        
        result = await subprocess(["test", "-w", "/dev/kvm"], capture_output=True)
        if not result.success:
            raise PrerequisiteError(
                "Current user does not have write access to /dev/kvm. "
                "Please add the user to the kvm group or grant appropriate permissions."
            )
    except Exception as e:
        raise PrerequisiteError(f"Failed to check KVM permissions: {e}")
    
    # Validate Docker Compose (for rootfs creation)
    await validate_docker_compose()