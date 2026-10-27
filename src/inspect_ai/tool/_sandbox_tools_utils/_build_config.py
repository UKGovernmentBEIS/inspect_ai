import re
from dataclasses import dataclass
from typing import Literal, TypeAlias, cast

# Duplicated from inspect_ai.util._sandbox._cli — keep in sync.
# Cannot import it here because this module runs inside Docker build containers
# where inspect_ai is not installed. Stdlib-only for the same reason, and so the
# release build runs it with no installed dependencies.
SANDBOX_TOOLS_BASE_NAME = "inspect-sandbox-tools"

SandboxToolsArch: TypeAlias = Literal["amd64", "arm64"]


@dataclass(frozen=True)
class SandboxToolsBuildConfig:
    arch: SandboxToolsArch
    version: int
    suffix: Literal["dev"] | None
    musl: bool = False
    """Whether this is the musl-linked variant (for musl sandboxes, e.g. Alpine).

    Encoded in the filename as a `-musl` token between arch and version. The glibc
    variant is the default and carries no token.
    """


def filename_to_config(filename: str) -> SandboxToolsBuildConfig:
    """
    Parse a filename into strongly typed build configuration.

    Expected pattern: inspect-sandbox-tools-{arch}[-musl]-v{version}[-{suffix}]
    Version is an ordinal integer (not semantic).
    """
    pattern = rf"^{SANDBOX_TOOLS_BASE_NAME}-(?P<arch>\w+)(?:-(?P<libc>musl))?-v(?P<version>\d+)(?:-(?P<suffix>\w+))?$"
    match = re.match(pattern, filename)
    if not match:
        raise ValueError(f"Filename '{filename}' doesn't match expected pattern")

    arch, suffix = match.group("arch"), match.group("suffix")
    if arch not in ("amd64", "arm64") or suffix not in (None, "dev"):
        raise ValueError(f"Invalid configuration in filename '{filename}'")
    return SandboxToolsBuildConfig(
        arch=cast(SandboxToolsArch, arch),
        version=int(match.group("version")),
        suffix=cast(Literal["dev"] | None, suffix),
        musl=match.group("libc") == "musl",
    )


def config_to_filename(config: SandboxToolsBuildConfig) -> str:
    """Convert strongly typed build configuration to filename."""
    base = f"{SANDBOX_TOOLS_BASE_NAME}-{config.arch}"
    if config.musl:
        base += "-musl"
    base += f"-v{config.version}"
    if config.suffix:
        base += f"-{config.suffix}"
    return base
