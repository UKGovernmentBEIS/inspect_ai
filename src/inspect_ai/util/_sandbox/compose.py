"""Docker Compose file parsing for sandbox providers.

This module provides Pydantic models and utilities for parsing Docker Compose
files into typed structures that sandbox providers can use for configuration.

Sandbox providers can use these utilities to accept compose files as configuration,
enabling portability across different sandbox types (Docker, Modal, K8s, etc.).
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

COMPOSE_FILES = [
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
]


def is_compose_yaml(file: str) -> bool:
    """Check if a path is a Docker Compose file.

    Args:
        file: Path to check.

    Returns:
        True if the path is a compose file (compose.yaml, compose.yml,
        docker-compose.yaml, or docker-compose.yml), False otherwise.
    """
    return Path(file).name in COMPOSE_FILES


DOCKERFILE = "Dockerfile"


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


class ComposeHealthcheck(BaseModel):
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


class ComposeBuild(BaseModel):
    """Build configuration for a compose service."""

    context: str | None = Field(default=None)
    """Path to the build context directory."""

    dockerfile: str | None = Field(default=None)
    """Path to the Dockerfile, relative to context."""


class ComposeResources(BaseModel):
    """Resource limits/reservations for a compose service."""

    cpus: str | None = Field(default=None)
    """CPU limit (e.g., '0.5', '2')."""

    memory: str | None = Field(default=None)
    """Memory limit (e.g., '512m', '2g')."""


class ComposeDeviceReservation(BaseModel):
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


class ComposeResourceReservations(BaseModel):
    """Resource reservations including devices."""

    cpus: str | None = Field(default=None)
    """Reserved CPU (e.g., '0.5', '2')."""

    memory: str | None = Field(default=None)
    """Reserved memory (e.g., '512m', '2g')."""

    devices: list[ComposeDeviceReservation] | None = Field(default=None)
    """Device reservations (e.g., GPUs)."""


class ComposeResourceConfig(BaseModel):
    """Deploy resources configuration."""

    limits: ComposeResources | None = Field(default=None)
    """Resource limits for the service."""

    reservations: ComposeResourceReservations | None = Field(default=None)
    """Resource reservations for the service."""


class ComposeDeploy(BaseModel):
    """Deploy configuration for a compose service."""

    resources: ComposeResourceConfig | None = Field(default=None)
    """Resource limits and reservations."""


class ComposeService(BaseModel):
    """A service definition from a compose file."""

    model_config = ConfigDict(extra="allow")

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

    @property
    def extensions(self) -> dict[str, Any]:
        """Access all x- extension fields.

        Returns a dict of all x- prefixed fields from the compose file.
        Providers can read arbitrary extensions like:
            service.extensions.get("x-timeout")
            service.extensions.get("x-block-network")
        """
        result = {}
        # Include x_default if set (it's an explicit field, not in model_extra)
        if self.x_default is not None:
            result["x-default"] = self.x_default
        if self.model_extra:
            for k, v in self.model_extra.items():
                if k.startswith("x-"):
                    result[k] = v
        return result


class ComposeConfig(BaseModel):
    """Parsed Docker Compose configuration."""

    model_config = ConfigDict(extra="allow")

    services: dict[str, ComposeService]
    """Service definitions, keyed by service name."""

    volumes: dict[str, Any] | None = Field(default=None)
    """Volume definitions."""

    networks: dict[str, Any] | None = Field(default=None)
    """Network definitions."""

    @property
    def extensions(self) -> dict[str, Any]:
        """Access all top-level x- extension fields.

        Returns a dict of all x- prefixed fields from the compose file.
        Providers can read arbitrary extensions like:
            config.extensions.get("x-inspect_modal_sandbox")
            config.extensions.get("x-allow-domains")
        """
        result = {}
        if self.model_extra:
            for k, v in self.model_extra.items():
                if k.startswith("x-"):
                    result[k] = v
        return result


def _get_used_fields(service: ComposeService) -> set[str]:
    """Get the set of fields that are set (not None) in a service."""
    used = set()
    for field_name, value in service.model_dump(
        by_alias=False, exclude={"x_default"}
    ).items():
        if value is not None:
            used.add(field_name)
    for key in service.extensions:
        used.add(key)
    return used


def _warn_unsupported_fields(
    config: ComposeConfig, supported_fields: list[str], path: str
) -> None:
    """Warn about fields in the compose file that are not supported."""
    supported = set(supported_fields)
    unsupported = set()
    for service in config.services.values():
        unsupported.update(_get_used_fields(service) - supported)

    if unsupported:
        warnings.warn(
            f"Compose file '{path}' uses fields not supported by this provider: "
            f"{sorted(unsupported)}",
            UserWarning,
        )


def parse_compose_yaml(
    file: str,
    *,
    supported_fields: list[str] | None = None,
    multiple_services: bool = True,
) -> ComposeConfig:
    """Parse a Docker Compose file into a ComposeConfig.

    Args:
        file: Path to the compose file.
        supported_fields: Optional list of supported field names. If provided,
            a warning will be issued for any fields in the compose file that
            are not in this list.
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

    if supported_fields is not None:
        _warn_unsupported_fields(config, supported_fields, file)

    return config
