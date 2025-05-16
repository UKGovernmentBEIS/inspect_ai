"""Configuration constants for Firecracker sandbox environments.

This module defines common configuration files used by Firecracker sandbox providers.
These are the configuration files that will be automatically discovered when
a sandbox environment is not explicitly specified.
"""

# Standard docker compose file names (in order they should be tried)
CONFIG_FILES = [
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
]

# Dockerfile for single-file configurations
DOCKERFILE = "Dockerfile"