from pathlib import Path

PKG_NAME = Path(__file__).parent.parent.stem


def _get_socket_path() -> Path:
    """Get the Unix domain socket path for the server."""
    socket_name = "sandbox-tools.sock"
    cache_dir = Path.home() / ".tmp"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / socket_name


SOCKET_PATH = _get_socket_path()
