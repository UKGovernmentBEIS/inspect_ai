import json
import re
from typing import Any

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._subprocess import subprocess


async def validate_compose_mounts(config: dict[str, Any], project_name: str) -> None:
    """Reject host writes and unverifiable mounts in resolved Compose configuration.

    Compose preserves extension value types: interpolation produces a string,
    so only a literal boolean can authorize unsafe mounts. Check every service,
    including services whose mounts are inherited by another service.
    """
    settings = config.get("x-inspect_docker_sandbox", {})
    if not isinstance(settings, dict):
        raise PrerequisiteError("x-inspect_docker_sandbox must be a mapping.")
    allow_writes = settings.get("unsafe_allow_writable_host_mounts", False)
    if type(allow_writes) is not bool:
        raise PrerequisiteError(
            "x-inspect_docker_sandbox.unsafe_allow_writable_host_mounts must be a "
            "literal boolean (true or false), without environment or sample "
            "metadata interpolation."
        )
    if allow_writes:
        return

    bind_runtimes: dict[str | None, str] = {}
    volumes = config.get("volumes", {})
    for service_name, service in config["services"].items():
        can_remount = service.get("privileged") or any(
            cap.upper().removeprefix("CAP_") in ("SYS_ADMIN", "ALL")
            for cap in service.get("cap_add", [])
        )
        if service.get("configs") or service.get("secrets"):
            if can_remount:
                raise mount_error(
                    service_name,
                    "configs/secrets",
                    "service privileges permit remounting host binds writable",
                )
            bind_runtimes[service.get("runtime")] = (
                f"service '{service_name}' configs/secrets"
            )
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
            description = f"{source} -> {mount['target']}"
            mount_type = mount["type"]
            if mount_type == "bind":
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
                recursive = bind.get("recursive", "enabled")
                if recursive == "writable":
                    raise mount_error(service_name, description, "writable submounts")
                bind_runtimes[service.get("runtime")] = (
                    f"service '{service_name}' mount '{description}'"
                )
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
                        description,
                        "volume host access cannot be verified",
                    )
            elif mount_type not in ("tmpfs", "image", "npipe"):
                raise mount_error(
                    service_name,
                    description,
                    f"mount type '{mount_type}' cannot be verified",
                )

    if bind_runtimes:
        result = await subprocess(
            ["docker", "info", "--format", "{{json .}}"], timeout=30
        )
        if not result.success:
            raise PrerequisiteError(
                f"Unable to verify read-only host bind support: {result.stderr}"
            )
        info = json.loads(result.stdout)
        engine = re.match(r"^(\d+)", info.get("ServerVersion", ""))
        kernel = re.match(r"^(\d+)\.(\d+)", info.get("KernelVersion", ""))
        runtimes = info.get("Runtimes", {})
        if (
            engine is None
            or int(engine[1]) < 25
            or kernel is None
            or tuple(map(int, kernel.groups())) < (5, 12)
            or any(
                "rro"
                not in json.loads(
                    runtimes.get(runtime or info.get("DefaultRuntime"), {})
                    .get("status", {})
                    .get("org.opencontainers.runtime-spec.features", "{}")
                ).get("mountOptions", [])
                for runtime in bind_runtimes
            )
        ):
            raise PrerequisiteError(
                f"Read-only host binds ({', '.join(bind_runtimes.values())}) require Docker Engine 25 or newer, Linux "
                "kernel 5.12 or newer, and a runtime supporting recursive read-only "
                "mounts. Upgrade Docker or copy inputs with Sample.files."
            )


def mount_error(service: str, mount: str, reason: str) -> PrerequisiteError:
    """Describe a rejected mount and the supported migration choices."""
    return PrerequisiteError(
        f"Docker service '{service}' mount '{mount}' is not permitted: {reason}. "
        "Use a read-only host bind, copy inputs with Sample.files, or use a "
        "Docker-managed volume without a custom name, driver options or external "
        "storage. To accept unsafe host access for the whole Compose project, "
        "set top-level x-inspect_docker_sandbox.unsafe_allow_writable_host_mounts "
        "to literal true. This can compromise the host and other evaluations."
    )
