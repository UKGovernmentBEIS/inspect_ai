# Docker Sandbox Provider for inspect_ai

This document explains how the Docker sandbox provider for `inspect_ai` works. The Docker sandbox provider allows `inspect_ai` to execute code and tools in isolated Docker containers, ensuring security and reproducibility.

## Overview

The Docker sandbox provider implements the `SandboxEnvironment` interface defined in `src/inspect_ai/util/_sandbox/environment.py`. It allows `inspect_ai` to:

1. Create isolated Docker environments for executing code
2. Manage file operations between the host and the container
3. Execute commands within the container
4. Clean up resources after execution
5. Connect to the container for debugging or interactive use

## Architecture

The Docker sandbox implementation is organized in multiple files under `src/inspect_ai/util/_sandbox/docker/`:

- `docker.py`: Main implementation of the `DockerSandboxEnvironment` class
- `compose.py`: Manages Docker Compose operations
- `config.py`: Handles configuration file resolution and auto-generation
- `cleanup.py`: Tracks and cleans up Docker resources
- `internal.py`: Manages internal Docker images
- `prereqs.py`: Validates Docker and Docker Compose prerequisites
- `service.py`: Defines data structures for Docker Compose services
- `util.py`: Utilities for Docker Compose projects

### Lifecycle

The Docker sandbox follows a well-defined lifecycle:

1. **Task Initialization** (`task_init`):
   - Validates Docker and Docker Compose prerequisites
   - Creates a Docker Compose project based on configuration
   - Builds or pulls required Docker images
   - Sets up project tracking for cleanup

2. **Sample Initialization** (`sample_init`):
   - Creates a Docker Compose project specific to the sample
   - Starts containers using `docker compose up`
   - Verifies that containers are running and healthy
   - Creates sandbox environments for each service

3. **Execution**:
   - Commands are executed via `exec` method
   - Files are read/written using container file system operations
   - Port mappings are tracked for web-based tools

4. **Sample Cleanup** (`sample_cleanup`):
   - Stops and removes containers for each sample
   - Cleans up temporary resources

5. **Task Cleanup** (`task_cleanup`):
   - Performs final cleanup of Docker resources
   - Removes auto-generated files

### Configuration Files

The Docker sandbox supports several configuration approaches:

1. **Docker Compose Files**: Standard Docker Compose files (`compose.yaml`, `docker-compose.yaml`, etc.)
2. **Dockerfile**: When only a Dockerfile is present, a minimal Docker Compose file is auto-generated
3. **Auto-generated**: When no configuration is provided, a generic container is used

### Error Handling and Resilience

The implementation includes several features for error handling and resilience:

- **Retry Logic**: Commands that time out can be retried with a shorter timeout
- **Healthchecks**: Container healthchecks ensure services are properly initialized
- **Graceful Cleanup**: Resources are tracked and cleaned up properly even if tasks are interrupted

## Key Components

### DockerSandboxEnvironment

The main class implementing the `SandboxEnvironment` interface. It manages Docker containers for executing code and provides methods for file operations and command execution.

### ComposeProject

Represents a Docker Compose project. It encapsulates:
- Project name
- Configuration file
- Sample ID and epoch
- Environment variables

### File Operations

File operations use Docker's copy mechanism:
- `write_file`: Writes content to a file in the container
- `read_file`: Reads content from a file in the container

### Command Execution

Commands are executed via `docker compose exec`. The implementation supports:
- Timeout and retry logic
- Input/output handling
- Working directory specification
- Environment variable forwarding

## Advanced Features

### Auto-generated Configuration

When only a Dockerfile is provided (or no configuration at all), the system auto-generates a Docker Compose configuration file.

### Internal Images

Some tools require specific Docker images. These are built as needed from resources within the package.

### Port Mapping

For tools that expose web interfaces, port mappings are tracked and exposed via the `connection` method.

### Container Connections

The `connection` method provides information needed to connect to a running container, including:
- Shell command for direct access
- VSCode integration command
- Port mappings for web interfaces

## Prerequisites

The Docker sandbox provider requires:
- Docker Engine >= 24.0.6
- Docker Compose >= 2.21.0 (or >= 2.22.0 for pull policy operations)

## Security Considerations

The Docker sandbox enhances security through:
- Isolation: Code runs in containers isolated from the host
- Resource Limits: Containers have controlled access to system resources
- Network Constraints: By default, containers run with `network_mode: none`

## Cleanup

The Docker sandbox provider includes comprehensive cleanup mechanisms:
- Sample-level cleanup after each evaluation
- Task-level cleanup after all evaluations
- CLI-triggered cleanup for manual intervention
- Tracking of auto-generated files for removal

## Conclusion

The Docker sandbox provider is a robust, flexible system for executing code in isolated environments. It leverages Docker's isolation features while providing a simple interface for file operations and command execution.