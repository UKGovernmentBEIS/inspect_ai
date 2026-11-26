import json
import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._subprocess import subprocess

from .config import auto_compose_dir
from .prereqs import (
    DOCKER_COMPOSE_REQUIRED_VERSION_READ_ONLY,
    validate_docker_compose,
)


async def validate_compose_mounts(config: dict[str, Any], project_name: str) -> None:
    """Reject host writes and unverifiable mounts across all Compose services."""
    _reject_binds_into_auto_compose_dir(config)
    if _unsafe_mounts_allowed(config):
        return

    volumes = config.get("volumes", {})
    bind_runtimes: dict[str | None, str] = {
        service.get("runtime"): description
        for service_name, service in config["services"].items()
        if (
            description := _validate_service_mounts(
                service_name, service, volumes, project_name
            )
        )
    }

    if bind_runtimes:
        await _validate_read_only_support(bind_runtimes)


def _unsafe_mounts_allowed(config: dict[str, Any]) -> bool:
    """Require an explicit boolean opt-in to unsafe host access.

    Compose preserves extension value types: interpolation produces a string,
    so only a literal boolean can authorize unsafe mounts.
    """
    settings = config.get("x-inspect_docker_sandbox", {})
    if not isinstance(settings, dict):
        raise PrerequisiteError(
            "Invalid 'x-inspect_docker_sandbox' section in the Compose configuration. "
            "Put its options underneath the heading, for example:\n\n"
            "x-inspect_docker_sandbox:\n"
            "  unsafe_allow_writable_host_mounts: false"
        )
    allow_writes = settings.get("unsafe_allow_writable_host_mounts", False)
    if type(allow_writes) is not bool:
        raise PrerequisiteError(
            "x-inspect_docker_sandbox.unsafe_allow_writable_host_mounts must be a "
            "literal boolean (true or false), without environment or sample "
            "metadata interpolation."
        )
    return allow_writes


def _validate_service_mounts(
    service_name: str,
    service: dict[str, Any],
    volumes: dict[str, Any],
    project_name: str,
) -> str | None:
    """Validate a service's mounts, returning a host mount needing runtime checks."""
    can_remount = bool(service.get("privileged")) or any(
        cap.upper().removeprefix("CAP_") in ("SYS_ADMIN", "ALL")
        for cap in service.get("cap_add", [])
    )
    description = None
    if service.get("configs") or service.get("secrets"):
        if can_remount:
            raise mount_error(
                service_name,
                "configs/secrets",
                "service privileges permit remounting host binds writable",
            )
        description = f"service '{service_name}' configs/secrets"
    if service.get("volumes_from"):
        raise mount_error(
            service_name,
            str(service["volumes_from"]),
            "volumes_from cannot be verified",
        )
    if service.get("volume_driver", "local") != "local":
        raise mount_error(
            service_name, "volume_driver", "volume host access cannot be verified"
        )
    for mount in service.get("volumes", []):
        source = mount.get("source", "(anonymous)")
        mount_description = f"{source} -> {mount['target']}"
        mount_type = mount["type"]
        if mount_type == "bind":
            _validate_bind_mount(service_name, mount, can_remount)
            description = f"service '{service_name}' mount '{mount_description}'"
        elif mount_type == "volume":
            volume = volumes.get(source, {})
            if (
                volume.get("external")
                or volume.get("driver", "local") != "local"
                or volume.get("driver_opts")
                or volume.get("name", f"{project_name}_{source}")
                != f"{project_name}_{source}"
            ):
                raise mount_error(
                    service_name,
                    mount_description,
                    "volume host access cannot be verified",
                )
        elif mount_type not in ("tmpfs", "image", "npipe"):
            raise mount_error(
                service_name,
                mount_description,
                f"mount type '{mount_type}' cannot be verified",
            )
    return description


def _validate_bind_mount(
    service_name: str, mount: dict[str, Any], can_remount: bool
) -> None:
    """Reject binds that permit host writes, including through nested mounts."""
    description = f"{mount['source']} -> {mount['target']}"
    if mount.get("read_only") is not True:
        raise mount_error(service_name, description, "writable host bind")
    if can_remount:
        raise mount_error(
            service_name,
            description,
            "service privileges permit remounting host binds writable",
        )
    bind = mount.get("bind", {})
    if bind.get("propagation", "rprivate") not in ("private", "rprivate"):
        raise mount_error(
            service_name,
            description,
            "bind propagation may expose writable submounts",
        )
    if bind.get("recursive") == "writable":
        raise mount_error(service_name, description, "writable submounts")


async def _validate_read_only_support(bind_runtimes: dict[str | None, str]) -> None:
    """Reject setups where Docker would silently leave nested mounts writable.

    Docker 25 makes read-only binds recursive on Linux 5.12+; the runtime must
    also advertise "rro" (see Moby's supportsRecursivelyReadOnly):
    https://docs.docker.com/engine/release-notes/25.0/#2500
    https://github.com/moby/moby/blob/v25.0.4/daemon/daemon_linux.go#L243-L260
    """
    result = await subprocess(["docker", "info", "--format", "{{json .}}"], timeout=30)
    if not result.success:
        raise PrerequisiteError(
            f"Unable to verify read-only host bind support: {result.stderr}"
        )
    info = json.loads(result.stdout)

    def runtime_supports_read_only(runtime: str | None) -> bool:
        status = (
            info.get("Runtimes", {})
            .get(runtime or info.get("DefaultRuntime"), {})
            .get("status", {})
        )
        features = json.loads(
            status.get("org.opencontainers.runtime-spec.features", "{}")
        )
        return "rro" in features.get("mountOptions", [])

    engine = re.match(r"^(\d+)", info.get("ServerVersion", ""))
    kernel = re.match(r"^(\d+)\.(\d+)", info.get("KernelVersion", ""))
    engine_supported = engine is not None and int(engine[1]) >= 25
    kernel_supported = kernel is not None and tuple(map(int, kernel.groups())) >= (
        5,
        12,
    )
    runtime_support = {
        runtime
        or info.get("DefaultRuntime")
        or "(unknown)": runtime_supports_read_only(runtime)
        for runtime in bind_runtimes
    }
    if not (engine_supported and kernel_supported and all(runtime_support.values())):
        runtime_details = ", ".join(
            f"{runtime} (recursive read-only {'supported' if supported else 'unsupported'})"
            for runtime, supported in runtime_support.items()
        )
        raise PrerequisiteError(
            "Inspect requires Docker Engine 25 or newer, Linux "
            "kernel 5.12 or newer, and a runtime supporting recursive read-only "
            "mounts before allowing read-only host sharing. These security "
            "requirements prevent mounts inside a shared directory from being "
            "writable.\n\n"
            f"Examples of affected host mounts: {', '.join(bind_runtimes.values())}.\n\n"
            f"Detected Docker Engine: {info.get('ServerVersion', '(unknown)')} "
            f"({'supported' if engine_supported else 'unsupported'}).\n"
            f"Detected Linux kernel: {info.get('KernelVersion', '(unknown)')} "
            f"({'supported' if kernel_supported else 'unsupported'}).\n"
            f"Detected runtimes: {runtime_details}.\n\n"
            "Upgrade Docker or copy inputs with Sample.files."
        )

    await validate_docker_compose(
        DOCKER_COMPOSE_REQUIRED_VERSION_READ_ONLY,
        required_for="Read-only host sharing",
    )
    api_override = os.environ.get("DOCKER_API_VERSION")
    if api_override is not None:
        version = re.fullmatch(r"(\d+)\.(\d+)", api_override)
        if version is None or tuple(map(int, version.groups())) < (1, 44):
            raise PrerequisiteError(
                "DOCKER_API_VERSION must be 1.44 or newer for read-only host sharing. "
                "Older API versions leave nested mounts writable. Unset this "
                "override or copy inputs with Sample.files."
            )


_ABSOLUTE_HOST_PATHS = (
    "Bind-mount sources and env_file paths in a ComposeConfig must be absolute "
    "(or start with ~/): its generated Compose file is stored outside the task "
    "directory, so Compose would resolve a relative path there. Build the path "
    'from the task file, for example Path(__file__).parent / "data".\n\n'
    "See https://inspect.aisi.org.uk/sandboxing.html#programmatic-configuration"
)


def validate_generated_host_paths(config: dict[str, Any]) -> None:
    """Reject relative host paths in a programmatic (``ComposeConfig``) config.

    Compose resolves a relative bind-mount source or ``env_file`` against the
    directory holding the compose file. A ``ComposeConfig`` is written to the
    generated-config directory, not the task directory, so a relative path
    would select a location there; a missing short-syntax bind source is even
    created, so the container silently sees an empty directory. Build contexts
    are not covered: ``auto_compose_file`` rebases them against the working
    directory. A source Compose interpolates (``${VAR}``) is checked once
    resolved, by ``validate_compose_mounts``.

    Args:
        config: The config as dumped from ``ComposeConfig``, before writing.
    """
    for service_name, service in config["services"].items():
        for mount in service.get("volumes", []):
            if _is_relative_bind(mount):
                raise relative_host_path_error(
                    service_name, "mount", _mount_text(mount)
                )
        env_files = service.get("env_file", [])
        for env_file in [env_files] if isinstance(env_files, str) else env_files:
            if _is_relative_host_path(env_file):
                raise relative_host_path_error(service_name, "env_file", env_file)


def _is_relative_bind(mount: Any) -> bool:
    if isinstance(mount, str):
        # short syntax: the source is a host path only when it starts with '.',
        # '/', '~' or a Windows drive, and of those only '.' is relative
        source, sep, _ = mount.partition(":")
        return bool(sep) and source.startswith(".")
    if isinstance(mount, dict) and mount.get("type") == "bind":
        bind_source = mount.get("source")
        return isinstance(bind_source, str) and _is_relative_host_path(bind_source)
    return False


def _is_relative_host_path(path: str) -> bool:
    """A literal relative path: not absolute, home-relative or interpolated.

    Any ``$`` counts as interpolation (``C:${HOMEPATH}`` is absolute once
    expanded); the backstop checks such paths after Compose resolves them.
    """
    if path.startswith("~") or "$" in path:
        return False
    return not (
        PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()
    )


def _mount_text(mount: Any) -> str:
    if isinstance(mount, str):
        return mount
    return f"{mount.get('source')} -> {mount.get('target')}"


def _reject_binds_into_auto_compose_dir(config: dict[str, Any]) -> None:
    """Reject bind sources Compose resolved into the generated-config directory.

    The backstop for a relative source ``validate_generated_host_paths`` could
    not see because interpolation supplied it (``${VAR}:/data``). Applies
    before the unsafe-mounts opt-in: that directory holds every sandbox's
    generated config and is never the directory a config meant. A value that
    climbs out of it (``../x``) is not detected. ``realpath`` rather than
    ``Path.resolve``, which raises on a symlink loop before Python 3.13.
    """
    compose_dir = Path(os.path.realpath(auto_compose_dir()))
    for service_name, service in config["services"].items():
        for mount in service.get("volumes", []):
            source = mount.get("source")
            if (
                mount["type"] == "bind"
                and isinstance(source, str)
                and Path(os.path.realpath(source)).is_relative_to(compose_dir)
            ):
                raise PrerequisiteError(
                    f"Docker service '{service_name}' mount "
                    f"'{source} -> {mount['target']}' resolves into Inspect's "
                    f"generated Compose config directory ({compose_dir}). "
                    + _ABSOLUTE_HOST_PATHS
                )


def relative_host_path_error(service: str, field: str, path: str) -> PrerequisiteError:
    """Describe a relative host path in a ``ComposeConfig`` and how to fix it."""
    return PrerequisiteError(
        f"Docker service '{service}' {field} '{path}' uses a relative host path. "
        + _ABSOLUTE_HOST_PATHS
    )


def mount_error(service: str, mount: str, reason: str) -> PrerequisiteError:
    """Describe a rejected mount and the supported migration choices."""
    return PrerequisiteError(
        f"Docker service '{service}' mount '{mount}' is not permitted: {reason}. "
        "For writable bind mounts, add :ro (e.g. ./data:/data:ro). "
        "Alternatively, copy inputs with Sample.files or use a "
        "Docker-managed volume without a custom name, driver options or external "
        "storage. To accept unsafe host access for the whole Compose project, "
        "set top-level x-inspect_docker_sandbox.unsafe_allow_writable_host_mounts "
        "to literal true. This can compromise the host.\n\n"
        "See https://inspect.aisi.org.uk/sandboxing.html#mounting-host-directories"
    )
