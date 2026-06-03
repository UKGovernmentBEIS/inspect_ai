import os
import tempfile
from pathlib import Path

PKG_NAME = Path(__file__).parent.parent.stem

SERVER_DIR_ENV = "INSPECT_SANDBOX_TOOLS_DIR"


def _get_server_dir() -> Path:
    """Get the directory holding the server's socket and logs.

    Reads from INSPECT_SANDBOX_TOOLS_DIR if set, else falls back to a
    fixed path under the system temp dir. Setting this per-sandbox lets
    each sandbox run its own server, preventing a stale server (whose
    working directory was deleted) from breaking subsequent runs.
    """
    if env_dir := os.environ.get(SERVER_DIR_ENV):
        return Path(env_dir)
    return Path(tempfile.gettempdir()) / "sandbox-tools"


SERVER_DIR = _get_server_dir()

SOCKET_PATH = SERVER_DIR / "sandbox-tools.sock"
