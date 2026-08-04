import hashlib
import os
import tempfile
from pathlib import Path

PKG_NAME = Path(__file__).parent.parent.stem

# Also defined in inspect_ai.util._sandbox.local — keep in sync.
SERVER_DIR_ENV = "INSPECT_SANDBOX_TOOLS_DIR"

SERVER_DIR = Path(
    os.environ.get(
        SERVER_DIR_ENV,
        str(Path(tempfile.gettempdir()) / "sandbox-tools"),
    )
)


def server_socket_path(server_dir: Path) -> Path:
    """Return a short, stable Unix socket path for one server directory."""
    identity = hashlib.sha256(os.fsencode(server_dir.resolve())).hexdigest()[:16]
    return Path("/tmp") / f"inspect-sandbox-tools-{os.getuid()}" / f"{identity}.sock"


SOCKET_PATH = server_socket_path(SERVER_DIR)
SHUTDOWN_STATUS_PATH = SERVER_DIR / "shutdown-status.json"
SERVER_PID_PATH = SERVER_DIR / "server.pid"
