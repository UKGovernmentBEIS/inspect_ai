import re
from typing import Literal, TypeAlias

from pydantic import BaseModel

# Duplicated from inspect_ai.util._sandbox._cli — keep in sync.
# Cannot import it here because this module runs inside Docker build containers
# where inspect_ai is not installed.
SANDBOX_TOOLS_BASE_NAME = "inspect-sandbox-tools"

SandboxToolsArch: TypeAlias = Literal["amd64", "arm64"]


class SandboxToolsBuildConfig(BaseModel):
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

    return SandboxToolsBuildConfig.model_validate(
        {
            "arch": match.group("arch"),
            "version": int(match.group("version")),
            "suffix": match.group("suffix"),
            "musl": match.group("libc") == "musl",
        }
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
