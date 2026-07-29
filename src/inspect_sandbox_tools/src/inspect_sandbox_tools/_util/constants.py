import os
import tempfile
from pathlib import Path

PKG_NAME = Path(__file__).parent.parent.stem

SERVER_DIR_ENV = "INSPECT_SANDBOX_TOOLS_DIR"

SERVER_DIR = Path(
    os.environ.get(
        SERVER_DIR_ENV,
        str(Path(tempfile.gettempdir()) / "sandbox-tools"),
    )
)

SOCKET_PATH = SERVER_DIR / "sandbox-tools.sock"
SHUTDOWN_STATUS_PATH = SERVER_DIR / "shutdown-status.json"
