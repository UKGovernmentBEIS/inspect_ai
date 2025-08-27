import re
from typing import Literal

from pydantic import BaseModel


class BuildConfig(BaseModel):
    arch: Literal["amd64", "arm64"]
    version: int
    browser: bool
    suffix: Literal["dev"] | None


def filename_to_config(filename: str) -> BuildConfig:
    """
    Parse a filename into strongly typed build configuration.

    Expected pattern: inspect-tool-support-{arch}-v{version}[+browser][-{suffix}]
    Version is an ordinal integer (not semantic).
    """
    match = re.match(
        r"^inspect-tool-support-(?P<arch>\w+)-v(?P<version>\d+)(?:\+(?P<browser>browser))?(?:-(?P<suffix>\w+))?$",
        filename,
    )
    if not match:
        raise ValueError(f"Filename '{filename}' doesn't match expected pattern")

    return BuildConfig.model_validate(
        {
            "arch": match.group("arch"),
            "version": int(match.group("version")),
            "browser": match.group("browser") == "browser",
            "suffix": match.group("suffix"),
        }
    )


def config_to_filename(config: BuildConfig) -> str:
    """Convert strongly typed build configuration to filename."""
    base = f"inspect-tool-support-{config.arch}-v{config.version}"
    if config.browser:
        base += "+browser"
    if config.suffix:
        base += f"-{config.suffix}"
    return base
