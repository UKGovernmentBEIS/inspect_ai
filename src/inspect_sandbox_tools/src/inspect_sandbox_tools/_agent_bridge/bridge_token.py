"""The token a model proxy requires when its bridge runs in a sandbox identity scope.

The host asks for a token by naming, in the proxy's environment, the scope's user
and the token file; it never sends the token. The proxy mints the token itself and
publishes it, readable only by that user (and root), once its listener is bound.
"""

import errno
import os
import pwd
import re
import secrets
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

from inspect_sandbox_tools._util.server_dir import ensure_private_server_dir

# Also defined in inspect_ai.agent._bridge.sandbox.bridge — keep in sync.
TOKEN_FILE_ENV = "BRIDGE_MODEL_SERVICE_TOKEN_FILE"
TOKEN_USER_ENV = "BRIDGE_MODEL_SERVICE_TOKEN_USER"
TOKEN_DIR = Path("/var/tmp/.inspect-bridge")
"""Directory of token files, owned by the proxy's user (root) with mode 0711.

Other users can open a file in it whose name they know, but cannot list it or
create, rename or remove entries in it.
"""

TOKEN_DIR_MODE = 0o711
TOKEN_BYTES = 32
"""A token is this many random bytes, hex-encoded (64 characters)."""

_TOKEN_NAME = re.compile(r"[A-Za-z0-9_-]{1,128}")


class TokenRequest(NamedTuple):
    """Where to publish the token, and for whom."""

    file: Path
    user: str


def token_request(environ: Mapping[str, str]) -> TokenRequest | None:
    """The token the host asked for in the proxy's environment, if any.

    Raises:
        RuntimeError: Only one of the two variables is set, or the file is not a
            plain name in `TOKEN_DIR`.
    """
    file = environ.get(TOKEN_FILE_ENV)
    user = environ.get(TOKEN_USER_ENV)
    if not file and not user:
        return None
    if not file or not user:
        raise RuntimeError(
            f"{TOKEN_FILE_ENV} and {TOKEN_USER_ENV} must be set together."
        )
    path = Path(file)
    if path.parent != TOKEN_DIR or not _TOKEN_NAME.fullmatch(path.name):
        raise RuntimeError(
            f"Bridge token file {file} is not a plain name in {TOKEN_DIR}."
        )
    return TokenRequest(path, user)


def new_token() -> str:
    """A random token."""
    return secrets.token_hex(TOKEN_BYTES)


def publish_token(token: str, request: TokenRequest) -> None:
    """Publish `token` at `request.file`, owned by `request.user` with mode 0400.

    The directory is created or adopted under the guest verified-directory
    contract, with no repair. The token is written to a temporary file in it,
    given to the user, and linked into place, so the file is either absent or
    complete. An existing entry at either path is refused, never replaced.

    Raises:
        RuntimeError: The user does not exist, the directory cannot be trusted,
            an entry already exists, or the file cannot be given to the user.
    """
    try:
        owner = pwd.getpwnam(request.user)
    except KeyError:
        raise RuntimeError(
            f"Bridge token user '{request.user}' does not exist."
        ) from None

    directory = request.file.parent
    ensure_private_server_dir(directory, mode=TOKEN_DIR_MODE, repair_mode=False)
    dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        temp = f".{request.file.name}.tmp"
        try:
            fd = os.open(
                temp,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=dir_fd,
            )
        except FileExistsError:
            raise _entry_exists(directory / temp) from None
        try:
            with os.fdopen(fd, "w") as file:
                file.write(token)
                file.flush()
                os.fchmod(file.fileno(), 0o400)
                try:
                    os.fchown(file.fileno(), owner.pw_uid, owner.pw_gid)
                except PermissionError as ex:
                    raise RuntimeError(
                        f"Bridge token file cannot be given to user '{request.user}': "
                        f"{ex.strerror}."
                    ) from None
            try:
                os.link(
                    temp,
                    request.file.name,
                    src_dir_fd=dir_fd,
                    dst_dir_fd=dir_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                raise _entry_exists(request.file) from None
        finally:
            os.unlink(temp, dir_fd=dir_fd)
    finally:
        os.close(dir_fd)


def remove_token(file: Path) -> None:
    """Remove a published token file, if it is still there."""
    try:
        os.unlink(file)
    except OSError as ex:
        if ex.errno != errno.ENOENT:
            raise


def _entry_exists(path: Path) -> RuntimeError:
    return RuntimeError(
        f"Bridge token path {path} already exists; refusing to replace it."
    )
