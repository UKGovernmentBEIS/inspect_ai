import atexit
import logging
import os
from pathlib import Path
from typing import Any

import psutil

from inspect_ai._display import display
from inspect_ai._display.logger import init_logger
from inspect_ai._util.constants import (
    DEFAULT_SERVER_HOST,
    DEFAULT_VIEW_PORT,
)
from inspect_ai._util.dotenv import init_dotenv
from inspect_ai._util.error import exception_message
from inspect_ai._view.server import view_server

from .notify import view_data_dir

logger = logging.getLogger(__name__)


def view(
    log_dir: str | None = None,
    recursive: bool = True,
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_VIEW_PORT,
    authorization: str | None = None,
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    fs_options: dict[str, Any] = {},
) -> None:
    init_dotenv()
    init_logger(log_level, log_level_transcript)

    # initialize the log_dir
    log_dir = log_dir if log_dir else os.getenv("INSPECT_LOG_DIR", "./logs")

    # acquire the requested port
    view_acquire_port(port)

    # run server
    view_server(
        log_dir=log_dir,
        recursive=recursive,
        host=host,
        port=port,
        authorization=authorization,
        fs_options=fs_options,
    )


def view_port_pid_file(port: int) -> Path:
    ports_dir = view_data_dir() / "ports"
    ports_dir.mkdir(parents=True, exist_ok=True)
    return ports_dir / str(port)


def view_acquire_port(port: int) -> None:
    # pid file name
    pid_file = view_port_pid_file(port)

    # does it already exist? if so terminate that process
    if pid_file.exists():
        WAIT_SECONDS = 5
        with open(pid_file, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
        try:
            p = psutil.Process(pid)
            p.terminate()
            display().print(
                f"Terminating existing inspect view command using port {port}"
            )
            p.wait(WAIT_SECONDS)

        except psutil.NoSuchProcess:
            # expected error for crufty pid files
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

    # write our pid to the file
    with open(pid_file, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

    # arrange to release on exit
    def release_lock_file() -> None:
        try:
            pid_file.unlink(True)
        except Exception:
            pass

    atexit.register(release_lock_file)
