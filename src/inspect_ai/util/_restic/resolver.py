"""Restic binary acquisition: platform IDs + resolver (download/cache).

The :func:`resolve_restic` coroutine returns a path to a usable restic
executable for a requested platform, downloading and caching it on demand.
The archive download retries transient network failures; the binary is
verified against the vendored ``SHA256SUMS`` file. ``Platform`` identifiers
match restic's upstream release filenames.
"""

from __future__ import annotations

import bz2
import os
import platform as _platform
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import Final, Literal

import anyio

from inspect_ai._util.appdirs import inspect_cache_dir
from inspect_ai._util.download import download

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

_VERSION_FILE: Final = Path(__file__).parent / "version.txt"
_SHA256SUMS_FILE: Final = Path(__file__).parent / "SHA256SUMS"
_RELEASE_BASE_URL: Final = "https://github.com/restic/restic/releases/download"
# Socket timeout (seconds) for the binary download, raised above download()'s
# 5s default to tolerate the larger transfer on slower links.
_DOWNLOAD_TIMEOUT: Final = 30


def _current_platform() -> Platform:
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


def _version() -> str:
    return _VERSION_FILE.read_text().strip()


def _is_windows(platform: Platform) -> bool:
    return platform.startswith("windows_")


def _archive_extension(platform: Platform) -> str:
    return "zip" if _is_windows(platform) else "bz2"


def _archive_filename(version: str, platform: Platform) -> str:
    return f"restic_{version}_{platform}.{_archive_extension(platform)}"


def _binary_filename(version: str, platform: Platform) -> str:
    suffix = ".exe" if _is_windows(platform) else ""
    return f"restic_{version}_{platform}{suffix}"


def _archive_url(version: str, platform: Platform) -> str:
    return f"{_RELEASE_BASE_URL}/v{version}/{_archive_filename(version, platform)}"


def cache_path(platform: Platform, version: str | None = None) -> Path:
    """Return the cache path where the decompressed binary lives for a platform."""
    return inspect_cache_dir("bin") / _binary_filename(version or _version(), platform)


async def resolve_restic(platform: Platform | None = None) -> Path:
    """Return a path to a usable restic binary for the given platform.

    Downloads the archive on cache miss, retrying transient network failures;
    the expected checksum is read from the vendored ``SHA256SUMS`` file (no
    network fetch). Fails fast on a SHA256 mismatch or a permanent download
    error.

    Args:
        platform: Target platform. Defaults to the current host platform.

    Returns:
        Absolute path to the cached executable.

    Raises:
        RuntimeError: on download failure (after retries), SHA256 mismatch,
            missing vendored checksum entry, decompression error, or
            unsupported platform.
    """
    target = platform or _current_platform()
    return await anyio.to_thread.run_sync(_resolve_blocking, target)


def _resolve_blocking(platform: Platform) -> Path:
    version = _version()
    target = cache_path(platform, version)
    if target.exists():
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    archive_name = _archive_filename(version, platform)
    expected_sha256 = _extract_expected_hash(_read_sha256sums(), archive_name)

    fd, tmp_path = tempfile.mkstemp(
        prefix="restic-archive-",
        suffix=f".{_archive_extension(platform)}",
        dir=target.parent,
    )
    os.close(fd)
    archive_tmp = Path(tmp_path)
    try:
        _download_archive(version, platform, expected_sha256, archive_tmp)
        binary_tmp = _extract(archive_tmp, platform, target.parent, version)
    finally:
        archive_tmp.unlink(missing_ok=True)

    try:
        binary_tmp.chmod(
            binary_tmp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        os.replace(binary_tmp, target)
    except Exception:
        binary_tmp.unlink(missing_ok=True)
        raise

    return target


def _download_archive(
    version: str, platform: Platform, sha256: str, dest: Path
) -> None:
    """Download the restic archive to ``dest`` and verify it against ``sha256``.

    Delegates retry, streaming, checksum verification, and atomic write to the
    shared :func:`inspect_ai._util.download.download` helper, translating its
    failure modes (checksum mismatch, HTTP error, exhausted retries) into the
    ``RuntimeError`` contract documented by :func:`resolve_restic`.
    """
    url = _archive_url(version, platform)
    try:
        download(url, sha256, dest, timeout=_DOWNLOAD_TIMEOUT)
    except Exception as ex:
        raise RuntimeError(f"Failed to download {url}: {ex}") from ex


def _read_sha256sums() -> str:
    """Read the vendored ``SHA256SUMS``, raising RuntimeError if it is unreadable.

    Honors :func:`resolve_restic`'s RuntimeError contract on a broken install
    (data file missing from the wheel, unreadable permissions) rather than
    leaking an ``OSError``.
    """
    try:
        return _SHA256SUMS_FILE.read_text()
    except OSError as ex:
        raise RuntimeError(
            f"Vendored SHA256SUMS unreadable at {_SHA256SUMS_FILE} "
            f"(corrupt installation?): {ex}"
        ) from ex


def _extract_expected_hash(sums_text: str, archive_name: str) -> str:
    pattern = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(\S+)$")
    for line in sums_text.splitlines():
        match = pattern.match(line.strip())
        if match and match.group(2) == archive_name:
            return match.group(1).lower()
    raise RuntimeError(
        f"No SHA256 entry for {archive_name} in the vendored SHA256SUMS; "
        f"regenerate it after a restic version bump "
        f"(see src/inspect_ai/util/_restic/README.md)."
    )


def _extract(archive: Path, platform: Platform, dest_dir: Path, version: str) -> Path:
    fd, tmp_path = tempfile.mkstemp(prefix="restic-binary-", dir=dest_dir)
    os.close(fd)
    tmp = Path(tmp_path)
    try:
        if _is_windows(platform):
            _extract_zip(archive, version, platform, tmp)
        else:
            _extract_bz2(archive, tmp)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


def _extract_bz2(archive: Path, dest: Path) -> None:
    with bz2.open(archive, "rb") as src, dest.open("wb") as dst:
        shutil.copyfileobj(src, dst)


def _extract_zip(archive: Path, version: str, platform: Platform, dest: Path) -> None:
    expected_member = f"restic_{version}_{platform}.exe"
    with zipfile.ZipFile(archive) as zf:
        try:
            with zf.open(expected_member) as src, dest.open("wb") as dst:
                shutil.copyfileobj(src, dst)
        except KeyError as ex:
            raise RuntimeError(
                f"{archive.name} does not contain expected member {expected_member}"
            ) from ex
