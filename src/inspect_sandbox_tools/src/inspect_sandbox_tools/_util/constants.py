import os
import tempfile
from pathlib import Path

PKG_NAME = Path(__file__).parent.parent.stem

SOCKET_PATH_ENV = "INSPECT_SANDBOX_TOOLS_SOCKET"


def _get_socket_path() -> Path:
    """Get the Unix domain socket path for the server.

    Reads from the INSPECT_SANDBOX_TOOLS_SOCKET environment variable if set,
    otherwise falls back to the default path in the system temp directory.

    Setting this per-sandbox allows each sandbox instance to run its own
    server, preventing a stale server (whose working directory was deleted)
    from breaking subsequent runs.
    """
    if env_path := os.environ.get(SOCKET_PATH_ENV):
        return Path(env_path)
    return Path(tempfile.gettempdir()) / "sandbox-tools.sock"


SOCKET_PATH = _get_socket_path()
