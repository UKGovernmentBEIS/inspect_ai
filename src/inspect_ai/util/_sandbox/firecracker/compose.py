"""Docker Compose helpers for Firecracker rootfs creation.

This module provides functions for interacting with Docker Compose to create
rootfs images that will be used by Firecracker micro VMs. It re-uses the
Docker Compose functionality from the Docker sandbox provider.
"""

import json
import os
import shlex
from logging import getLogger
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.trace import trace_message
from inspect_ai.util._display import display_type
from inspect_ai.util._subprocess import ExecResult, subprocess

# For simplicity, we'll import and reuse functions from the Docker sandbox provider
# In a real implementation, you might want to adapt these to your specific needs
from ..docker.compose import (
    compose_build,
    compose_check_running,
    compose_cleanup_images,
    compose_command,
    compose_cp,
    compose_down,
    compose_exec,
    compose_ls,
    compose_ps,
    compose_pull,
    compose_services,
    compose_up,
)

# Just re-export the functions directly
__all__ = [
    "compose_build",
    "compose_check_running",
    "compose_cleanup_images",
    "compose_command",
    "compose_cp",
    "compose_down",
    "compose_exec",
    "compose_ls",
    "compose_ps",
    "compose_pull",
    "compose_services",
    "compose_up",
]

logger = getLogger(__name__)