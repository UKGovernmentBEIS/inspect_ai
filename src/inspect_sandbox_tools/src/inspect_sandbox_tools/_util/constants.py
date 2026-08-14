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


_MAX_UNIX_SOCKET_PATH_BYTES = 100


def server_socket_path(server_dir: Path) -> Path:
    """Return a private socket path, falling back only when it is too long."""
    natural_path = server_dir / "sandbox-tools.sock"
    if len(os.fsencode(natural_path)) <= _MAX_UNIX_SOCKET_PATH_BYTES:
        return natural_path

    identity = hashlib.sha256(os.fsencode(server_dir.resolve())).hexdigest()[:16]
    return Path("/tmp") / f"inspect-sandbox-tools-{os.getuid()}" / f"{identity}.sock"


SOCKET_PATH = server_socket_path(SERVER_DIR)
SHUTDOWN_STATUS_PATH = SERVER_DIR / "shutdown-status.json"
SERVER_PID_PATH = SERVER_DIR / "server.pid"
