"""Platform identifiers for restic binaries, matching upstream filename convention."""

from __future__ import annotations

import platform as _platform
from typing import Literal

Platform = Literal[
    "linux_amd64",
    "linux_arm64",
    "darwin_amd64",
    "darwin_arm64",
    "windows_amd64",
]
"""Supported platforms. Strings match restic's release filenames."""

SUPPORTED_PLATFORMS: tuple[Platform, ...] = (
    "linux_amd64",
    "linux_arm64",
    "darwin_amd64",
    "darwin_arm64",
    "windows_amd64",
)


def current_platform() -> Platform:
    """Return the platform string for the current host.

    Raises:
        RuntimeError: if the host OS/arch combination is not in
            ``SUPPORTED_PLATFORMS``.
    """
    system = _platform.system().lower()
    machine = _platform.machine().lower()

    os_ = _OS_MAP.get(system)
    arch = _ARCH_MAP.get(machine)

    match (os_, arch):
        case ("linux", "amd64"):
            return "linux_amd64"
        case ("linux", "arm64"):
            return "linux_arm64"
        case ("darwin", "amd64"):
            return "darwin_amd64"
        case ("darwin", "arm64"):
            return "darwin_arm64"
        case ("windows", "amd64"):
            return "windows_amd64"
        case _:
            raise RuntimeError(
                f"Unsupported host platform: system={_platform.system()!r}, "
                f"machine={_platform.machine()!r}"
            )


_OS_MAP = {
    "linux": "linux",
    "darwin": "darwin",
    "windows": "windows",
}

_ARCH_MAP = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
}
