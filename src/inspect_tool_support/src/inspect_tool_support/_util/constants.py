import os
from pathlib import Path

PKG_NAME = Path(__file__).parent.parent.stem


def get_socket_path() -> Path:
    """Get the Unix domain socket path for the server."""
    if runtime_dir := os.environ.get("XDG_RUNTIME_DIR"):
        return Path(runtime_dir) / "inspect-tool-support.sock"

    # Fallback for non-systemd or older systems
    cache_dir = Path.home() / ".cache" / "inspect-tool-support"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "server.sock"


SOCKET_PATH = get_socket_path()
