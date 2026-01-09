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


class ComposeHealthcheck(BaseModel):
    """Healthcheck configuration for a compose service."""

    test: list[str] | str | None = None
    interval: str | None = None
    timeout: str | None = None
    start_period: str | None = None
    start_interval: str | None = None
    retries: int | None = None


class ComposeBuild(BaseModel):
    """Build configuration for a compose service."""

    context: str | None = None
    dockerfile: str | None = None


class ComposeResources(BaseModel):
    """Resource limits/reservations for a compose service."""

    cpus: str | None = None
    memory: str | None = None


class ComposeDeviceReservation(BaseModel):
    """Device reservation for GPU and other devices."""

    driver: str | None = None
    count: int | str | None = None  # Can be int or "all"
    device_ids: list[str] | None = None
    capabilities: list[str] | None = None
    options: dict[str, str] | None = None


class ComposeResourceReservations(BaseModel):
    """Resource reservations including devices."""

    cpus: str | None = None
    memory: str | None = None
    devices: list[ComposeDeviceReservation] | None = None


class ComposeResourceConfig(BaseModel):
    """Deploy resources configuration."""

    limits: ComposeResources | None = None
    reservations: ComposeResourceReservations | None = None


class ComposeDeploy(BaseModel):
    """Deploy configuration for a compose service."""

    resources: ComposeResourceConfig | None = None


class ComposeService(BaseModel):
    """A service definition from a compose file."""

    model_config = ConfigDict(extra="allow")

    # Standard compose fields
    image: str | None = None
    build: ComposeBuild | str | None = None
    command: list[str] | str | None = None
    entrypoint: list[str] | str | None = None
    working_dir: str | None = None
    environment: list[str] | dict[str, str | None] | None = None
    env_file: list[str] | str | None = None
    user: str | None = None
    healthcheck: ComposeHealthcheck | None = None
    ports: list[str | int] | None = None
    expose: list[str | int] | None = None
    volumes: list[str] | None = None
    networks: list[str] | dict[str, Any] | None = None
    network_mode: str | None = None
    hostname: str | None = None
    runtime: str | None = None
    init: bool | None = None
    deploy: ComposeDeploy | None = None

    # Memory/CPU shortcuts (alternative to deploy.resources)
    mem_limit: str | None = None
    mem_reservation: str | None = None
    cpus: float | None = None

    # x-default is explicit since all providers use it to identify the default service
    x_default: bool | None = Field(default=None, alias="x-default")

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
    volumes: dict[str, Any] | None = None
    networks: dict[str, Any] | None = None

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

    @staticmethod
    def is_compose_file(path: str) -> bool:
        """Check if a path is a Docker Compose file.

        Args:
            path: Path to check.

        Returns:
            True if the path is a compose file, False otherwise.
        """
        return Path(path).name in COMPOSE_FILES


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


def parse_compose_file(
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
