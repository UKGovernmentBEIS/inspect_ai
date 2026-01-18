"""Docker Compose file parsing for sandbox providers.

This module provides Pydantic models and utilities for parsing Docker Compose
files into typed structures that sandbox providers can use for configuration.

Sandbox providers can use these utilities to accept compose files as configuration,
enabling portability across different sandbox types (Docker, Modal, K8s, etc.).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

COMPOSE_FILES = [
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
]

DOCKERFILE = "Dockerfile"


def is_compose_yaml(file: str) -> bool:
    """Check if a path is a Docker Compose file.

    Args:
        file: Path to check.

    Returns:
        True if the path is a compose file (compose.yaml, compose.yml,
        docker-compose.yaml, or docker-compose.yml), False otherwise.
    """
    return Path(file).name in COMPOSE_FILES


def is_dockerfile(file: str) -> bool:
    """Check if a path is a Dockerfile.

    Args:
        file: Path to check.

    Returns:
        True if the path is a Dockerfile (Dockerfile, name.Dockerfile,
        or Dockerfile.name), False otherwise.
    """
    path = Path(file)
    return path.stem == DOCKERFILE or path.suffix == f".{DOCKERFILE}"


class ComposeModel(BaseModel):
    """Base model that allows x- extensions while rejecting other unknown fields."""

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def allow_only_extensions(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        field_names = set(cls.model_fields.keys())
        # Also allow aliased field names (e.g., "x-default" for x_default)
        for field_info in cls.model_fields.values():
            if field_info.alias:
                field_names.add(field_info.alias)
        for key in data:
            if key not in field_names and not key.startswith("x-"):
                raise ValueError(f"Unknown field: '{key}'")
        return data

    @property
    def extensions(self) -> dict[str, Any]:
        """Get x- extension fields."""
        return self.model_extra or {}


class ComposeHealthcheck(ComposeModel):
    """Healthcheck configuration for a compose service."""

    test: list[str] | str | None = Field(default=None)
    """Command to run to check health."""

    interval: str | None = Field(default=None)
    """Time between health checks (e.g., '30s', '1m')."""

    timeout: str | None = Field(default=None)
    """Maximum time to wait for a check to complete."""

    start_period: str | None = Field(default=None)
    """Time to wait before starting health checks."""

    start_interval: str | None = Field(default=None)
    """Time between checks during the start period."""

    retries: int | None = Field(default=None)
    """Number of consecutive failures needed to consider unhealthy."""


class ComposeBuild(ComposeModel):
    """Build configuration for a compose service."""

    context: str | None = Field(default=None)
    """Path to the build context directory."""

    dockerfile: str | None = Field(default=None)
    """Path to the Dockerfile, relative to context."""


class ComposeResources(ComposeModel):
    """Resource limits/reservations for a compose service."""

    cpus: str | None = Field(default=None)
    """CPU limit (e.g., '0.5', '2')."""

    memory: str | None = Field(default=None)
    """Memory limit (e.g., '512m', '2g')."""


class ComposeDeviceReservation(ComposeModel):
    """Device reservation for GPU and other devices."""

    driver: str | None = Field(default=None)
    """Device driver (e.g., 'nvidia')."""

    count: int | str | None = Field(default=None)
    """Number of devices to reserve, or 'all'."""

    device_ids: list[str] | None = Field(default=None)
    """Specific device IDs to reserve."""

    capabilities: list[str] | None = Field(default=None)
    """Required device capabilities (e.g., ['gpu'])."""

    options: dict[str, str] | None = Field(default=None)
    """Driver-specific options."""


class ComposeResourceReservations(ComposeModel):
    """Resource reservations including devices."""

    cpus: str | None = Field(default=None)
    """Reserved CPU (e.g., '0.5', '2')."""

    memory: str | None = Field(default=None)
    """Reserved memory (e.g., '512m', '2g')."""

    devices: list[ComposeDeviceReservation] | None = Field(default=None)
    """Device reservations (e.g., GPUs)."""


class ComposeResourceConfig(ComposeModel):
    """Deploy resources configuration."""

    limits: ComposeResources | None = Field(default=None)
    """Resource limits for the service."""

    reservations: ComposeResourceReservations | None = Field(default=None)
    """Resource reservations for the service."""


class ComposeDeploy(ComposeModel):
    """Deploy configuration for a compose service."""

    resources: ComposeResourceConfig | None = Field(default=None)
    """Resource limits and reservations."""


class ComposeService(ComposeModel):
    """A service definition from a compose file."""

    image: str | None = Field(default=None)
    """Docker image to use (e.g., 'python:3.11')."""

    build: ComposeBuild | str | None = Field(default=None)
    """Build configuration or path to build context."""

    command: list[str] | str | None = Field(default=None)
    """Command to run in the container."""

    entrypoint: list[str] | str | None = Field(default=None)
    """Entrypoint for the container."""

    working_dir: str | None = Field(default=None)
    """Working directory inside the container."""

    environment: list[str] | dict[str, str | None] | None = Field(default=None)
    """Environment variables."""

    env_file: list[str] | str | None = Field(default=None)
    """Path(s) to file(s) containing environment variables."""

    user: str | None = Field(default=None)
    """User to run the container as."""

    healthcheck: ComposeHealthcheck | None = Field(default=None)
    """Health check configuration."""

    ports: list[str | int] | None = Field(default=None)
    """Port mappings (host:container)."""

    expose: list[str | int] | None = Field(default=None)
    """Ports to expose without publishing to the host."""

    volumes: list[str] | None = Field(default=None)
    """Volume mounts."""

    networks: list[str] | dict[str, Any] | None = Field(default=None)
    """Networks to connect to."""

    network_mode: str | None = Field(default=None)
    """Network mode (e.g., 'host', 'none', 'bridge')."""

    hostname: str | None = Field(default=None)
    """Container hostname."""

    runtime: str | None = Field(default=None)
    """Runtime to use (e.g., 'nvidia')."""

    init: bool | None = Field(default=None)
    """Run an init process inside the container."""

    deploy: ComposeDeploy | None = Field(default=None)
    """Deployment configuration including resources."""

    mem_limit: str | None = Field(default=None)
    """Memory limit (shortcut for deploy.resources.limits.memory)."""

    mem_reservation: str | None = Field(default=None)
    """Memory reservation (shortcut for deploy.resources.reservations.memory)."""

    cpus: float | None = Field(default=None)
    """CPU limit (shortcut for deploy.resources.limits.cpus)."""

    x_default: bool | None = Field(default=None, alias="x-default")
    """Mark this service as the default for sandbox providers."""


class ComposeConfig(ComposeModel):
    """Parsed Docker Compose configuration."""

    services: dict[str, ComposeService]
    """Service definitions, keyed by service name."""

    volumes: dict[str, Any] | None = Field(default=None)
    """Volume definitions."""

    networks: dict[str, Any] | None = Field(default=None)
    """Network definitions."""

    def __hash__(self) -> int:
        """Make ComposeConfig hashable by hashing its JSON representation."""
        return hash(self.model_dump_json())

    def __eq__(self, other: object) -> bool:
        """Compare ComposeConfig objects by their content."""
        if not isinstance(other, ComposeConfig):
            return NotImplemented
        return self.model_dump() == other.model_dump()


def parse_compose_yaml(
    file: str,
    *,
    multiple_services: bool = True,
) -> ComposeConfig:
    """Parse a Docker Compose file into a ComposeConfig.

    Args:
        file: Path to the compose file.
        multiple_services: Whether the provider supports multiple services.
            If False and the compose file has multiple services, a ValueError
            will be raised.

    Returns:
        Parsed ComposeConfig.

    Raises:
        FileNotFoundError: If the compose file does not exist.
        ValueError: If the compose file is invalid or has multiple services
            when multiple_services=False.
    """
    path = Path(file)
    if not path.exists():
        raise FileNotFoundError(f"Compose file not found: {file}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Invalid compose file format: {file}")

    if "services" not in raw:
        raise ValueError(f"Compose file must have 'services' key: {file}")

    config = ComposeConfig.model_validate(raw)

    if not multiple_services and len(config.services) > 1:
        service_names = list(config.services.keys())
        raise ValueError(
            f"Provider does not support multiple services. "
            f"Found {len(config.services)} services: {service_names}"
        )

    return config
