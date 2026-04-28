import tempfile
from pathlib import Path

PKG_NAME = Path(__file__).parent.parent.stem


SERVER_DIR = Path(tempfile.gettempdir()) / "sandbox-tools"

SOCKET_PATH = SERVER_DIR / "sandbox-tools.sock"
