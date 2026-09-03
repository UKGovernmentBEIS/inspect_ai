import errno
import hashlib
import os
import stat
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

PKG_NAME = Path(__file__).parent.parent.stem

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


SERVER_DIR = resolve_server_dir(
    os.environ, bool(getattr(sys, "frozen", False)), sys.executable
)


_MAX_UNIX_SOCKET_PATH_BYTES = 100


def server_socket_path(server_dir: Path) -> Path:
    """Return a private socket path, falling back only when it is too long."""
    natural_path = server_dir / "sandbox-tools.sock"
    if len(os.fsencode(natural_path)) <= _MAX_UNIX_SOCKET_PATH_BYTES:
        return natural_path

    identity = hashlib.sha256(os.fsencode(server_dir.resolve())).hexdigest()[:16]
    return Path("/tmp") / f"inspect-sandbox-tools-{os.geteuid()}" / f"{identity}.sock"


SOCKET_PATH = server_socket_path(SERVER_DIR)
SHUTDOWN_STATUS_PATH = SERVER_DIR / "shutdown-status.json"
SERVER_PID_PATH = SERVER_DIR / "server.pid"


def ensure_private_server_dir(server_dir: Path, *, create: bool = True) -> None:
    """Create ``server_dir`` as a private directory, or verify an existing one.

    The socket, pid, lock, and status files that the server and CLI trust live in
    this directory. Inside an injected bundle it sits in the tools tree, which only
    the tools user can write to; the ``local`` sandbox supplies a directory inside
    its private per-sample temp dir; source mode (development and tests) falls back
    to the system temp dir, where other users may be able to plant an entry before
    the server first starts. Either way an existing entry is adopted only if it is
    a real directory (not a symlink) owned by the current effective uid, and it is
    then tightened to mode 0700; an owned directory the uid cannot even enter is
    refused rather than repaired. This holds for root and non-root servers alike: a
    rootless server shares its uid with the sandbox's default user, but no other uid
    in the container may reach its socket or rewrite its control files (older
    releases left rootless directories at 0777).

    Verification and tightening go through a descriptor so they bind to the entry
    that was inspected; a path-based chmod would follow a symlink swapped in later.
    Only the final path component is checked: the caller must supply a parent that
    other principals cannot write to (or that is sticky), and it must already exist.

    Args:
        server_dir: The directory to create or verify.
        create: Create the directory (mode 0700) when nothing exists at the path.
            With ``False`` a missing directory raises ``FileNotFoundError``.

    Raises:
        RuntimeError: An entry exists at the path but cannot be trusted, or the
            directory cannot be created.
        FileNotFoundError: ``create`` is False and nothing exists at the path.
    """
    if create:
        # The inherited umask filters the requested mode and could leave the new
        # directory without owner permissions, which would then be refused.
        old_umask = os.umask(0o077)
        try:
            server_dir.mkdir(mode=0o700)
        except FileExistsError:
            pass
        except OSError as ex:
            raise RuntimeError(
                f"Sandbox-tools server directory {server_dir} cannot be created: "
                f"{ex.strerror or ex}"
            ) from ex
        finally:
            os.umask(old_umask)

    try:
        dir_fd = _open_directory(server_dir)
    except FileNotFoundError:
        raise
    except OSError as ex:
        raise _untrusted_server_dir(server_dir, _describe_entry(server_dir, ex)) from ex

    try:
        info = os.fstat(dir_fd)
        expected_uid = os.geteuid()
        if info.st_uid != expected_uid:
            raise _untrusted_server_dir(
                server_dir, f"it is owned by uid {info.st_uid}, not uid {expected_uid}"
            )
        if stat.S_IMODE(info.st_mode) != 0o700:
            os.fchmod(dir_fd, 0o700)
    finally:
        os.close(dir_fd)


def _open_directory(path: Path) -> int:
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def _describe_entry(path: Path, open_error: OSError) -> str:
    """Explain why opening ``path`` as a directory failed, for an error message.

    The errno alone is not portable: for a symlink, Linux reports ELOOP but macOS
    reports ENOTDIR once O_DIRECTORY is combined with O_NOFOLLOW.
    """
    detail = open_error.strerror or str(open_error)
    try:
        info = path.lstat()
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


def _untrusted_server_dir(server_dir: Path, reason: str) -> RuntimeError:
    return RuntimeError(
        f"Sandbox-tools server directory {server_dir} cannot be trusted: {reason}. "
        "Remove the entry (or correct its ownership and permissions) and retry."
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
    try:
        fd = os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    except OSError as ex:
        if ex.errno == errno.ELOOP:
            raise RuntimeError(
                f"Sandbox-tools server file {path} is a symbolic link; refusing to follow it"
            ) from ex
        raise
    if flags & os.O_CREAT:
        # The umask may have masked owner bits from the creation mode; the file
        # must stay readable and writable by its owner for the next open.
        os.fchmod(fd, 0o600)
    return fd
