"""The server's private state directory and the control files inside it.

The socket, pid, lock, log, and status files that the server and CLI trust all
live in one directory. This module decides where that directory is, creates or
verifies it as private to the current user, and opens files inside it without
following anything another principal could have planted there.
"""

import errno
import fcntl
import hashlib
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

from inspect_sandbox_tools._util.framework_directory import open_framework_directory

# Also defined in inspect_ai.util._sandbox.local — keep in sync.
SERVER_DIR_ENV = "INSPECT_SANDBOX_TOOLS_DIR"

_INSTALL_TREE_SERVER_DIR_NAME = ".server"


def resolve_server_dir(
    environ: Mapping[str, str], frozen: bool, executable: str
) -> Path:
    """Choose where this process keeps the server's socket and control files.

    A host-supplied directory always wins: the ``local`` sandbox gives each sample
    its own temp dir, and every CLI and daemon process for that sample must agree
    on it. Otherwise an injected (frozen) bundle keeps its state beside its own
    launcher, inside the tools tree the host installed and already has to trust
    to execute code from. Nobody but the tools user can write there, so no other
    principal can pre-create or replace the state directory, unlike a fixed path
    under a world-writable temp dir. Source-mode processes (development and
    tests) fall back to the conventional temporary location.
    """
    if environ.get(SERVER_DIR_ENV):
        return Path(environ[SERVER_DIR_ENV])
    if frozen:
        return Path(executable).resolve().parent / _INSTALL_TREE_SERVER_DIR_NAME
    return Path(tempfile.gettempdir()) / "sandbox-tools"


_MAX_UNIX_SOCKET_PATH_BYTES = 100


def server_socket_path(server_dir: Path) -> Path:
    """Return a private socket path, falling back only when it is too long."""
    natural_path = server_dir / "sandbox-tools.sock"
    if len(os.fsencode(natural_path)) <= _MAX_UNIX_SOCKET_PATH_BYTES:
        return natural_path

    identity = hashlib.sha256(os.fsencode(server_dir.resolve())).hexdigest()[:16]
    return Path("/tmp") / f"inspect-sandbox-tools-{os.geteuid()}" / f"{identity}.sock"


def ensure_private_server_dir(server_dir: Path, *, create: bool = True) -> None:
    """Create ``server_dir`` as a private directory, or verify an existing one.

    The socket, pid, lock, and status files that the server and CLI trust live in
    this directory. Inside an injected bundle it sits in the tools tree, which only
    the tools user can write to; the ``local`` sandbox supplies a directory inside
    its private per-sample temp dir; source mode (development and tests) falls back
    to the system temp dir, where other users may be able to plant an entry before
    the server first starts. Either way an existing entry is adopted only if it is
    a real directory owned by the current effective uid, and it is then tightened
    to mode 0700. This holds for root and non-root servers alike: a rootless server
    shares its uid with the sandbox's default user, but no other uid in the
    container may reach its socket or rewrite its control files (older releases
    left rootless directories at 0777).

    Args:
        server_dir: The directory to create or verify.
        create: Create the directory (mode 0700) when nothing exists at the path.
            With ``False`` a missing directory raises ``FileNotFoundError``.

    Raises:
        RuntimeError: An entry exists at the path but cannot be trusted, or the
            directory cannot be created.
        FileNotFoundError: ``create`` is False and nothing exists at the path.
    """
    os.close(
        open_framework_directory(
            server_dir,
            kind="Sandbox-tools server directory",
            owners=(os.geteuid(),),
            mode=0o700,
            create=create,
        )
    )


def read_private_text(path: Path) -> str:
    """Read a file in the server directory without following a symlink at its path."""
    with os.fdopen(_open_private(path, os.O_RDONLY)) as file:
        return file.read()


def write_private_text(path: Path, text: str) -> None:
    """Create or truncate a file in the server directory, never through a symlink."""
    with os.fdopen(
        _open_private(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC), "w"
    ) as file:
        file.write(text)


def open_private_append(path: Path) -> TextIO:
    """Open a file in the server directory for appending, never through a symlink."""
    return os.fdopen(_open_private(path, os.O_RDWR | os.O_CREAT | os.O_APPEND), "a+")


def _open_private(path: Path, flags: int) -> int:
    """Open a control file that must be a regular file owned by this uid.

    O_NOFOLLOW rejects a symlink at the path, but not a FIFO, device, or
    directory planted there. A FIFO with no peer would block ``open()`` itself,
    so the open is non-blocking: a read-open of a FIFO then returns at once and
    a write-open fails with ENXIO, and the fstat that follows rejects anything
    that is not a regular file. O_NONBLOCK is cleared before the descriptor is
    returned (it has no effect on regular files anyway).
    """
    try:
        fd = os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o600)
    except OSError as ex:
        if ex.errno == errno.ELOOP:
            raise RuntimeError(
                f"Sandbox-tools server file {path} is a symbolic link; refusing to follow it"
            ) from ex
        if ex.errno in (errno.ENXIO, errno.EISDIR):
            raise _not_regular_file(path) from ex
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise _not_regular_file(path)
        if info.st_uid != os.geteuid():
            raise RuntimeError(
                f"Sandbox-tools server file {path} is owned by uid {info.st_uid}, "
                f"not uid {os.geteuid()}; refusing to open it"
            )
        status_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, status_flags & ~os.O_NONBLOCK)
        if flags & os.O_CREAT:
            # The umask may have masked owner bits from the creation mode; the
            # file must stay readable and writable by its owner for the next open.
            os.fchmod(fd, 0o600)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _not_regular_file(path: Path) -> RuntimeError:
    return RuntimeError(
        f"Sandbox-tools server file {path} is not a regular file; refusing to open it"
    )
