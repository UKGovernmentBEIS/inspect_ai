import re
from typing import Literal

from pydantic import BaseModel


class SandboxToolsBuildConfig(BaseModel):
    arch: Literal["amd64", "arm64"]
    version: int
    suffix: Literal["dev"] | None


def filename_to_config(filename: str) -> SandboxToolsBuildConfig:
    """
    Parse a filename into strongly typed build configuration.

    Expected pattern: inspect-sandbox-tools-{arch}-v{version}[-{suffix}]
    Version is an ordinal integer (not semantic).
    """
    match = re.match(
        r"^inspect-sandbox-tools-(?P<arch>\w+)-v(?P<version>\d+)(?:-(?P<suffix>\w+))?$",
        filename,
    )
    if not match:
        raise ValueError(f"Filename '{filename}' doesn't match expected pattern")

    return SandboxToolsBuildConfig.model_validate(
        {
            "arch": match.group("arch"),
            "version": int(match.group("version")),
            "suffix": match.group("suffix"),
        }
    )


def config_to_filename(config: SandboxToolsBuildConfig) -> str:
    """Convert strongly typed build configuration to filename."""
    base = f"inspect-sandbox-tools-{config.arch}-v{config.version}"
    if config.suffix:
        base += f"-{config.suffix}"
    return base
