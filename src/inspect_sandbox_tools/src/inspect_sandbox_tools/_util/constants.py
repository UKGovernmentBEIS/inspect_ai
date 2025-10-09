import tempfile
from pathlib import Path

PKG_NAME = Path(__file__).parent.parent.stem


def _get_socket_path() -> Path:
    """Get the Unix domain socket path for the server."""
    socket_name = "sandbox-tools.sock"
    return Path(tempfile.gettempdir()) / socket_name


SOCKET_PATH = _get_socket_path()
