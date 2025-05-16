"""Cleanup functions for Firecracker sandbox environments.

This module provides functions for cleaning up Firecracker VMs and 
associated Docker resources used for rootfs creation.
"""

import os
import tempfile
from logging import getLogger
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from inspect_ai._util.trace import trace_message
from inspect_ai.util._display import display_type
from inspect_ai.util._subprocess import subprocess

# For simplicity, we'll import and reuse functions from the Docker sandbox provider
# for Docker Compose cleanup
from ..docker.cleanup import (
    cli_cleanup,
    project_cleanup,
    project_cleanup_shutdown,
    project_cleanup_startup,
    project_record_auto_compose,
    project_startup,
)

# Just re-export the functions directly
__all__ = [
    "cli_cleanup",
    "project_cleanup",
    "project_cleanup_shutdown",
    "project_cleanup_startup",
    "project_record_auto_compose",
    "project_startup",
]

logger = getLogger(__name__)