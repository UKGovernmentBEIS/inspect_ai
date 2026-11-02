import atexit
import logging
import os
from pathlib import Path
from typing import Any

import psutil

from inspect_ai._display import display
from inspect_ai._util.constants import (
    DEFAULT_SERVER_HOST,
    DEFAULT_VIEW_PORT,
)
from inspect_ai._util.dotenv import init_dotenv
from inspect_ai._util.error import exception_message
from inspect_ai._util.logger import init_logger

from .network import resolve_viewer_network_policy
from .notify import view_data_dir

logger = logging.getLogger(__name__)


def view(
    log_dir: str | None = None,
    recursive: bool = True,
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_VIEW_PORT,
    authorization: str | None = None,
    log_level: str | None = None,
    fs_options: dict[str, Any] = {},
    trusted_origins: tuple[str, ...] = (),
    trusted_hosts: tuple[str, ...] = (),
    unsafe_allow_unauthenticated: bool = False,
    show_shards: bool = False,
    trust_content: bool | None = None,
) -> None:
    """Run the Inspect View server.

    Args:
        log_dir: Directory to view logs from.
        recursive: Recursively list files in `log_dir`.
        host: Tcp/ip host (defaults to "127.0.0.1").
        port: Tcp/ip port (defaults to 7575).
        authorization: Validate requests by checking for this authorization header.
        log_level: Level for logging to the console: "debug", "http", "sandbox",
            "info", "warning", "error", "critical", or "notset" (defaults to "warning")
        fs_options: Additional arguments to pass through to the filesystem provider
            (e.g. `S3FileSystem`). Use `{"anon": True }` if you are accessing a
            public S3 bucket with no credentials.
        trusted_origins: Exact browser origins allowed to use the viewer.
        trusted_hosts: Additional exact HTTP authorities allowed for non-browser
            clients.
        unsafe_allow_unauthenticated: Allow a non-loopback bind without request
            authorization.
        show_shards: List shard logs (under `<name>.shards/`) that their merged
            log already covers. By default these are hidden.
        trust_content: `False` shows the content of every log as plain text,
            whatever the log's own `ViewerConfig(trust_content=...)`. `None`
            (the default) or `True` defers to each log; it never shows an
            untrusted log richly.
    """
    init_dotenv()
    init_logger(log_level)

    # initialize the log_dir
    if not log_dir:
        log_dir = os.getenv("INSPECT_LOG_DIR", "./logs")

    network_policy = resolve_viewer_network_policy(
        bind_host=host,
        port=port,
        trusted_hosts=trusted_hosts,
        trusted_origins=trusted_origins,
        authorization=authorization,
        unsafe_allow_unauthenticated=unsafe_allow_unauthenticated,
    )

    # acquire the requested port
    view_acquire_port(view_data_dir(), port)

    from .fastapi_server import view_server

    view_server(
        log_dir=log_dir,
        recursive=recursive,
        host=host,
        port=port,
        network_policy=network_policy,
        fs_options=fs_options,
        show_shards=show_shards,
        trust_content=trust_content,
    )


def view_port_pid_file(app_dir: Path, port: int) -> Path:
    ports_dir = app_dir / "ports"
    ports_dir.mkdir(parents=True, exist_ok=True)
    # not `ports/<port>`: older versions read that as a bare pid and fail on
    # anything else
    return ports_dir / f"{port}.pid"


def view_acquire_port(app_dir: Path, port: int) -> None:
    # pid file name
    pid_file = view_port_pid_file(app_dir, port)

    # is another view server holding the port? if so terminate it
    owner = view_port_owner(pid_file)
    if owner is not None:
        WAIT_SECONDS = 5
        try:
            owner.terminate()
            display().print(f"Terminating existing view command using port {port}")
            owner.wait(WAIT_SECONDS)

        except psutil.NoSuchProcess:
            # exited since we checked
            pass
        except psutil.TimeoutExpired:
            logger.warning(
                f"Timed out waiting for process to exit for {WAIT_SECONDS} seconds."
            )
        except psutil.AccessDenied:
            logger.warning(
                "Attempted to kill existing view command on "
                + f"port {port} but access was denied."
            )
        except Exception as ex:
            logger.warning(
                "Attempted to kill existing view command on "
                + f"port {port} but error occurred: {exception_message(ex)}"
            )

    # write our identity to the file
    ident = process_ident(psutil.Process())
    pid_file.write_text(ident, encoding="utf-8")

    # arrange to release on exit (unless a newer server has taken the file)
    def release_lock_file() -> None:
        try:
            if pid_file.read_text(encoding="utf-8") == ident:
                pid_file.unlink()
        except Exception:
            pass

    atexit.register(release_lock_file)


def view_port_owner(pid_file: Path) -> psutil.Process | None:
    """Return the other view server recorded in `pid_file`, if it is still running.

    The pid file outlives a server that crashes or is killed, and the OS may
    since have given its pid to an unrelated process, so the recorded start
    time must match as well. On Linux the start time psutil reports moves when
    the system clock is stepped, so it is compared with a small tolerance. A
    missing, unreadable or malformed file has no owner.
    """
    try:
        pid, create_time = pid_file.read_text(encoding="utf-8").split()
        process = psutil.Process(int(pid))
        if (
            process.pid != os.getpid()
            and abs(process.create_time() - float(create_time)) < 2
        ):
            return process
    except (OSError, ValueError, psutil.Error):
        pass
    return None


def process_ident(process: psutil.Process) -> str:
    """Identify a process by pid and start time, which pid reuse cannot repeat."""
    return f"{process.pid} {process.create_time()}"
