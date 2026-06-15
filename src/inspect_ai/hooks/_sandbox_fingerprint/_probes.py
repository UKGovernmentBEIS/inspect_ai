import json
from dataclasses import dataclass
from logging import getLogger
from typing import Any, Awaitable, Callable

from inspect_ai.util._sandbox.environment import SandboxConnection, SandboxEnvironment
from inspect_ai.util._subprocess import subprocess

logger = getLogger(__name__)


@dataclass
class ProbeContext:
    """Inputs available to a fingerprint probe for a single sandbox environment."""

    sandbox: SandboxEnvironment
    connection: SandboxConnection | None
    """Resolved connection, or None when the provider has no host-side connection."""


ProbeFn = Callable[[ProbeContext], Awaitable[dict[str, Any]]]
"""A probe returns a partial dict of `SandboxFingerprint` field names.

Custom probes should target `{"metadata": {...}}` to avoid colliding with the
built-in fields.
"""

_PROBES: dict[str, ProbeFn] = {}


def register_fingerprint_probe(name: str, probe: ProbeFn) -> None:
    """Register a fingerprint probe (replacing any existing probe of the same name)."""
    _PROBES[name] = probe


def fingerprint_probe(name: str) -> Callable[[ProbeFn], ProbeFn]:
    """Decorator form of `register_fingerprint_probe`."""

    def decorator(probe: ProbeFn) -> ProbeFn:
        register_fingerprint_probe(name, probe)
        return probe

    return decorator


def fingerprint_probes() -> dict[str, ProbeFn]:
    return dict(_PROBES)


async def _docker_inspect(target: str, fmt: str) -> str | None:
    try:
        result = await subprocess(
            ["docker", "inspect", target, "--format", fmt], timeout=60
        )
        return result.stdout.strip() if result.success else None
    except TimeoutError:
        return None


async def _probe_image_digest(context: ProbeContext) -> dict[str, Any]:
    if context.connection is None or context.connection.container is None:
        return {}
    container = context.connection.container
    fields: dict[str, Any] = {}

    image_info = await _docker_inspect(container, "{{.Config.Image}}\t{{.Image}}")
    if image_info:
        image, _, image_id = image_info.partition("\t")
        fields["image"] = image or None
        fields["image_id"] = image_id or None
        if image_id:
            repo_digests = await _docker_inspect(image_id, "{{json .RepoDigests}}")
            if repo_digests:
                parsed = json.loads(repo_digests)
                fields["repo_digests"] = parsed or None

    return fields


async def _probe_network_profile(context: ProbeContext) -> dict[str, Any]:
    if context.connection is None or context.connection.container is None:
        return {}
    network = await _docker_inspect(
        context.connection.container, "{{.HostConfig.NetworkMode}}"
    )
    return {"network_profile": network} if network else {}


async def _exec(context: ProbeContext, cmd: list[str]) -> str | None:
    try:
        result = await context.sandbox.exec(cmd, timeout=60)
        return result.stdout.strip() if result.success else None
    except (TimeoutError, NotImplementedError, PermissionError):
        return None


async def _probe_os(context: ProbeContext) -> dict[str, Any]:
    os_release = await _exec(context, ["cat", "/etc/os-release"])
    if not os_release:
        return {}
    values: dict[str, str] = {}
    for line in os_release.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key] = value.strip().strip('"')
    pretty = values.get("PRETTY_NAME") or values.get("NAME")
    return {"os": pretty} if pretty else {}


async def _probe_kernel(context: ProbeContext) -> dict[str, Any]:
    kernel = await _exec(context, ["uname", "-r"])
    return {"kernel": kernel} if kernel else {}


async def _probe_packages(context: ProbeContext) -> dict[str, Any]:
    output = await _exec(context, ["pip", "list", "--format=json"])
    if output is None:
        return {}
    try:
        entries = json.loads(output)
    except json.JSONDecodeError:
        return {}
    packages = {
        entry["name"]: entry["version"]
        for entry in entries
        if "name" in entry and "version" in entry
    }
    return {"packages": packages}


register_fingerprint_probe("image_digest", _probe_image_digest)
register_fingerprint_probe("network_profile", _probe_network_profile)
register_fingerprint_probe("os", _probe_os)
register_fingerprint_probe("kernel", _probe_kernel)
register_fingerprint_probe("packages", _probe_packages)
