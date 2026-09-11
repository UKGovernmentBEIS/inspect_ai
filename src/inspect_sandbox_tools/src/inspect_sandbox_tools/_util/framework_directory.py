"""Directories whose contents the sandbox tools trust.

The server's state directory and the chunked-response directories are created
by the tools at paths another principal may have been able to reach first. An
existing entry is therefore adopted only after it is verified through a
descriptor, and that same descriptor is what the caller then acts on: a
path-based check followed by a path-based operation leaves a window in which
the entry can be swapped for a symbolic link.
"""

import os
import stat
from collections.abc import Collection
from pathlib import Path
from typing import NamedTuple


def open_framework_directory(
    path: Path,
    *,
    kind: str,
    owners: Collection[int],
    mode: int,
    create: bool,
    dir_fd: int | None = None,
    shared: bool = False,
) -> int:
    """Create or verify the directory at ``path`` and return a descriptor for it.

    The entry must be a real directory (not a symlink) owned by one of
    ``owners``. A caller that owns the directory sets its mode to ``mode``; any
    other caller requires the mode to already be ``mode``. The caller must close
    the returned descriptor. Only the final path component is verified: the
    parent must be one that other principals cannot use to replace the entry.

    Args:
        path: The directory. With ``dir_fd``, only its final component is used,
            relative to that (already verified) parent descriptor.
        kind: Describes the directory in error messages.
        owners: The uids allowed to own the directory.
        mode: The required permission bits, e.g. ``0o700`` or ``0o1733``.
        create: Create the directory (with exactly ``mode``, regardless of the
            umask) when nothing exists at the path.
        dir_fd: Descriptor of the parent directory to resolve the entry in.
        shared: The directory is shared with other uids that cannot read it
            (a sticky ``1733`` root). A caller without read permission then
            gets an ``O_PATH`` descriptor, which still supports ``fstat`` and
            anchors ``*at`` calls for the entries beneath it.

    Raises:
        FileNotFoundError: ``create`` is False and nothing exists at the path.
        RuntimeError: The entry cannot be trusted or cannot be created.
    """
    name = path.name if dir_fd is not None else path
    if create:
        _create(name, path, kind, mode, dir_fd)
    try:
        opened = _open(name, dir_fd, shared)
    except FileNotFoundError:
        raise
    except OSError as ex:
        raise _untrusted(kind, path, _describe_entry(name, dir_fd, ex)) from ex
    try:
        _verify(opened, path, kind, owners, mode)
    except BaseException:
        os.close(opened.fd)
        raise
    return opened.fd


def _create(
    name: str | Path, path: Path, kind: str, mode: int, dir_fd: int | None
) -> None:
    old_umask = os.umask(0o777 & ~mode)
    try:
        os.mkdir(name, mode, dir_fd=dir_fd)
    except FileExistsError:
        pass
    except OSError as ex:
        raise RuntimeError(
            f"{kind} {path} cannot be created: {ex.strerror or ex}"
        ) from ex
    finally:
        os.umask(old_umask)


class _OpenedDirectory(NamedTuple):
    fd: int
    readable: bool
    """False for an O_PATH descriptor, which cannot list or fchmod."""


def _open(name: str | Path, dir_fd: int | None, shared: bool) -> _OpenedDirectory:
    flags = os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        return _OpenedDirectory(os.open(name, os.O_RDONLY | flags, dir_fd=dir_fd), True)
    except PermissionError:
        o_path = getattr(os, "O_PATH", None)
        if not shared or o_path is None:
            raise
        return _OpenedDirectory(os.open(name, o_path | flags, dir_fd=dir_fd), False)


def _verify(
    opened: _OpenedDirectory,
    path: Path,
    kind: str,
    owners: Collection[int],
    mode: int,
) -> None:
    info = os.fstat(opened.fd)
    if info.st_uid not in owners:
        allowed = " or ".join(f"uid {uid}" for uid in sorted(set(owners)))
        raise _untrusted(kind, path, f"it is owned by uid {info.st_uid}, not {allowed}")
    actual = stat.S_IMODE(info.st_mode)
    if actual == mode:
        return
    if info.st_uid != os.geteuid():
        raise _untrusted(kind, path, f"it has mode {actual:04o}, not {mode:04o}")
    if not opened.readable:
        raise _untrusted(
            kind,
            path,
            f"it is owned by uid {info.st_uid} with mode {actual:04o} "
            "and cannot be opened for reading",
        )
    os.fchmod(opened.fd, mode)


def _describe_entry(name: str | Path, dir_fd: int | None, open_error: OSError) -> str:
    """Explain why opening the entry as a directory failed.

    The errno alone is not portable: a symlink surfaces as ELOOP or ENOTDIR
    depending on the platform and kernel.
    """
    detail = open_error.strerror or str(open_error)
    try:
        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except OSError:
        return detail
    if stat.S_ISLNK(info.st_mode):
        return "it is a symbolic link"
    if not stat.S_ISDIR(info.st_mode):
        return "it is not a directory"
    return (
        f"it is owned by uid {info.st_uid} with mode {stat.S_IMODE(info.st_mode):04o} "
        f"and cannot be opened ({detail})"
    )


def _untrusted(kind: str, path: Path, reason: str) -> RuntimeError:
    return RuntimeError(
        f"{kind} {path} cannot be trusted: {reason}. "
        "Remove the entry (or correct its ownership and permissions) and retry."
    )
