"""Utility functions and classes for Firecracker sandbox environments.

This module provides:
1. ComposeProject class for Docker Compose project management (rootfs creation)
2. FirecrackerVM class for managing Firecracker micro VMs
3. Helper functions for project naming and validation
"""

import asyncio
import json
import os
import random
import socket
import string
import tempfile
import time
import uuid
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from typing_extensions import Literal

from inspect_ai._util.content import is_text
from inspect_ai._util.trace import trace_message
from inspect_ai.util._subprocess import ExecResult, subprocess

# Import after all stdlib imports
# pylint: disable=wrong-import-order
from .._subprocess import ExecResult

logger = getLogger(__name__)


def task_project_name(name: str) -> str:
    """Generates a unique identifier for a sandbox project.
    
    This function creates a project name for Docker Compose that includes
    the task name and a random suffix to ensure uniqueness.
    
    Args:
        name: Base name for the project (usually task name)
        
    Returns:
        str: Unique project name including random suffix
    """
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    return f"inspect-ai-fc-{name}-{suffix}"


def is_inspect_project(name: str) -> bool:
    """Determines if a project name belongs to an inspect-ai sandbox.
    
    This function checks if a project name follows the inspect-ai project naming 
    convention, which is used to identify sandbox projects for cleanup.
    
    Args:
        name: Project name to check
        
    Returns:
        bool: True if this is an inspect-ai project
    """
    return name.startswith("inspect-ai-fc-")


@dataclass
class ComposeProject:
    """Represents a Docker Compose project for building rootfs images.
    
    This class encapsulates information about a Docker Compose project that 
    will be used to build rootfs images for Firecracker VMs. It includes
    the project name, configuration path, and environment variables.
    """

    name: str
    """Project name for Docker Compose."""

    config: Optional[str]
    """Path to Compose configuration file."""

    env: Optional[Dict[str, str]] = None
    """Environment variables for Docker Compose."""

    sample_id: Optional[str] = None
    """Optional sample ID (for naming)."""

    epoch: Optional[int] = None
    """Optional epoch number (for naming)."""

    @classmethod
    async def create(
        cls,
        name: str,
        config: Any,
        sample_id: Optional[str] = None,
        epoch: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> "ComposeProject":
        """Creates a Docker Compose project for rootfs creation.
        
        This factory method sets up a Docker Compose project that will be used
        to build rootfs images for Firecracker VMs. It handles configuration
        files and environment variables.
        
        Args:
            name: Project name for Docker Compose
            config: Path to configuration file or config object
            sample_id: Optional sample ID for naming
            epoch: Optional epoch number for naming
            env: Optional environment variables
            
        Returns:
            ComposeProject: Configured project for building rootfs
        """
        # Placeholder implementation for now
        # In a real implementation, this would handle config resolution
        # The functionality is similar to the Docker provider's ComposeProject.create
        
        # Create a ComposeProject
        if isinstance(config, str) and os.path.exists(config):
            return cls(
                name=name,
                config=config,
                sample_id=sample_id,
                epoch=epoch,
                env=env,
            )
        else:
            return cls(
                name=name,
                config=None,
                sample_id=sample_id,
                epoch=epoch,
                env=env,
            )


class FirecrackerVM:
    """Manages a Firecracker MicroVM instance.
    
    This class provides an interface to create, manage, and interact with
    Firecracker micro VMs. It handles VM lifecycle, resource configuration,
    file operations, and command execution.
    """

    def __init__(
        self, 
        vm_id: str, 
        rootfs_path: str, 
        kernel_path: str,
        socket_path: Optional[str] = None,
        vcpus: int = 1,
        mem_mib: int = 512
    ) -> None:
        """Initializes a Firecracker VM.
        
        Args:
            vm_id: Unique identifier for the VM
            rootfs_path: Path to the rootfs image
            kernel_path: Path to the kernel image
            socket_path: Optional custom path to the Firecracker socket
            vcpus: Number of virtual CPUs
            mem_mib: Memory allocation in MiB
        """
        self.id = vm_id
        self.rootfs_path = rootfs_path
        self.kernel_path = kernel_path
        self.socket_path = socket_path or f"/tmp/firecracker-{vm_id}.socket"
        self.vcpus = vcpus
        self.mem_mib = mem_mib
        self.process = None
        self.ip_address = None  # This would be assigned during startup
        
        # Firecracker API endpoint
        self.api_url = "http://localhost"
        
    async def start(self) -> None:
        """Starts the Firecracker VM.
        
        This method:
        1. Launches the Firecracker process
        2. Configures the VM via the API
        3. Boots the VM
        4. Sets up networking
        
        Raises:
            RuntimeError: If the VM fails to start
        """
        # In a real implementation, this would:
        # 1. Start the firecracker process
        # 2. Configure machine, kernel, rootfs, networking
        # 3. Start the instance
        
        # Placeholder for actual implementation
        # Example of how the API would be called:
        """
        # Start firecracker process
        cmd = [
            "firecracker", 
            "--api-sock", self.socket_path,
            "--id", self.id
        ]
        self.process = await subprocess(cmd, background=True)
        
        # Configure machine
        machine_config = {
            "vcpu_count": self.vcpus,
            "mem_size_mib": self.mem_mib
        }
        await self._make_request("PUT", "/machine-config", machine_config)
        
        # Configure kernel boot
        boot_config = {
            "kernel_image_path": self.kernel_path,
            "boot_args": "console=ttyS0 reboot=k panic=1 pci=off"
        }
        await self._make_request("PUT", "/boot-source", boot_config)
        
        # Configure rootfs
        rootfs_config = {
            "drive_id": "rootfs",
            "path_on_host": self.rootfs_path,
            "is_root_device": True,
            "is_read_only": False
        }
        await self._make_request("PUT", "/drives/rootfs", rootfs_config)
        
        # Start the VM
        await self._make_request("PUT", "/actions", {"action_type": "InstanceStart"})
        
        # Set up a tap device for networking
        self.ip_address = "192.168.100.2"  # This would be dynamically assigned
        """
        
        # For now, let's just set a placeholder IP for demo purposes
        self.ip_address = "192.168.100.2"
    
    async def stop(self) -> None:
        """Stops the Firecracker VM.
        
        This method:
        1. Sends a shutdown command to the VM
        2. Terminates the Firecracker process
        3. Cleans up resources
        """
        # In a real implementation, this would:
        # 1. Send shutdown signal via API
        # 2. Kill process if needed
        # 3. Clean up socket file
        
        # Placeholder implementation:
        if self.process:
            # Try graceful shutdown first
            try:
                await self._make_request("PUT", "/actions", {"action_type": "SendCtrlAltDel"})
                # Wait a bit for graceful shutdown
                await asyncio.sleep(3)
            except Exception:
                # If that fails, force kill
                pass
            
            # Kill the process if it's still running
            try:
                self.process.kill()
            except Exception:
                pass
                
        # Clean up the socket file
        try:
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
        except Exception as e:
            logger.warning(f"Failed to remove socket file {self.socket_path}: {e}")
            
        # Reset IP address
        self.ip_address = None
    
    async def is_running(self) -> bool:
        """Checks if the VM is currently running.
        
        Returns:
            bool: True if the VM is running
        """
        # In a real implementation, this would check the VM state via the API
        # For now, just check if we have an IP assigned
        return self.ip_address is not None
    
    async def exec_command(
        self,
        cmd: List[str],
        input: Optional[Union[str, bytes]] = None,
        cwd: Optional[str] = None,
        env: Dict[str, str] = {},
        user: Optional[str] = None,
        timeout: Optional[int] = None,
        output_limit: Optional[int] = None,
    ) -> ExecResult[str]:
        """Executes a command inside the VM.
        
        This method would run a command in the VM using SSH or another 
        execution mechanism.
        
        Args:
            cmd: Command and arguments to execute
            input: Optional stdin input
            cwd: Working directory for execution
            env: Environment variables
            user: User to run as
            timeout: Command timeout in seconds
            output_limit: Maximum output size
            
        Returns:
            ExecResult: Command execution result
            
        Raises:
            RuntimeError: If command execution fails
            TimeoutError: If command times out
        """
        # In a real implementation, this would:
        # 1. Use SSH or another mechanism to execute the command
        # 2. Properly handle input, environment variables, etc.
        # 3. Return the results
        
        # Placeholder implementation:
        stdout = f"Command would run in VM: {' '.join(cmd)}"
        stderr = ""
        return ExecResult(stdout=stdout, stderr=stderr, returncode=0)
    
    async def write_file(self, path: str, contents: Union[str, bytes]) -> None:
        """Writes a file to the VM.
        
        Args:
            path: Path where to write the file
            contents: File contents (text or binary)
            
        Raises:
            RuntimeError: If file writing fails
            PermissionError: If permission is denied
        """
        # In a real implementation, this would:
        # 1. Use SSH or another file transfer mechanism
        # 2. Handle both text and binary content
        
        # Placeholder implementation - no-op
        pass
    
    async def read_file(self, path: str) -> Union[str, bytes]:
        """Reads a file from the VM.
        
        Args:
            path: Path to the file to read
            
        Returns:
            Union[str, bytes]: File contents
            
        Raises:
            FileNotFoundError: If the file doesn't exist
            PermissionError: If permission is denied
        """
        # In a real implementation, this would:
        # 1. Use SSH or another file transfer mechanism
        # 2. Return the file contents
        
        # Placeholder implementation:
        return f"Contents of {path} would be returned"
    
    async def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict:
        """Makes an HTTP request to the Firecracker API.
        
        Args:
            method: HTTP method (GET, PUT, etc.)
            endpoint: API endpoint
            data: Optional request payload
            
        Returns:
            Dict: API response
            
        Raises:
            RuntimeError: If the API request fails
        """
        # In a real implementation, this would:
        # 1. Make an HTTP request to the Firecracker socket
        # 2. Handle response parsing and error checking
        
        # Placeholder implementation:
        """
        url = f"{self.api_url}{endpoint}"
        response = requests.request(
            method=method,
            url=url,
            json=data,
            headers={"Content-Type": "application/json"},
            unix_socket_path=self.socket_path
        )
        response.raise_for_status()
        if response.content:
            return response.json()
        return {}
        """
        return {}