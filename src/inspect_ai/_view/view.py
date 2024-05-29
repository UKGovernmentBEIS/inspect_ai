import atexit
import json
import logging
import os
import sys
from functools import partial
from http import HTTPStatus
from http.server import HTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse, urlunparse

import psutil
from pydantic_core import to_jsonable_python

from inspect_ai._display import display
from inspect_ai._display.logger import init_logger
from inspect_ai._util.appdirs import inspect_runtime_dir
from inspect_ai._util.constants import (
    DEFAULT_SERVER_HOST,
    DEFAULT_VIEW_PORT,
)
from inspect_ai._util.dotenv import init_dotenv
from inspect_ai._util.error import exception_message
from inspect_ai._util.file import FileSystem, file, filesystem
from inspect_ai._util.http import InspectHTTPRequestHandler
from inspect_ai.log._file import (
    eval_log_json,
    list_eval_logs,
    read_eval_log,
    read_eval_log_headers,
)

logger = logging.getLogger(__name__)


WWW_DIR = os.path.abspath((Path(__file__).parent / "www").as_posix())


LOGS_PATH = "/api/logs"
LOGS_DIR = f"{LOGS_PATH}/"
LOG_HEADERS_PATH = "/api/log-headers"


def view(
    log_dir: str | None = None,
    recursive: bool = True,
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_VIEW_PORT,
    log_level: str | None = None,
    fs_options: dict[str, Any] = {},
) -> None:
    init_dotenv()
    init_logger(log_level)

    # initialize the right filesystem for this log_dir
    log_dir = log_dir if log_dir else os.getenv("INSPECT_LOG_DIR", "./logs")
    fs = filesystem(log_dir, fs_options)

    # list the logs and confirm that there are logs to view (this also ensures
    # that the right e.g. S3 credentials are present before we run the server)
    files = list_eval_logs(log_dir, recursive=recursive, fs_options=fs_options)
    if len(files) == 0:
        print(f"No log files currently available in {log_dir}")
        sys.exit(0)

    # acquire the requested port
    view_acquire_port(port)

    # run server
    view_handler = partial(
        ViewHTTPRequestHandler,
        fs=fs,
        log_dir=log_dir,
        recursive=recursive,
        fs_options=fs_options,
    )
    httpd = HTTPServer((host, port), view_handler)
    display().print(f"Inspect view running at http://localhost:{port}/")
    httpd.serve_forever()


class ViewHTTPRequestHandler(InspectHTTPRequestHandler):
    def __init__(
        self,
        *args: Any,
        fs: FileSystem,
        log_dir: str,
        recursive: bool,
        fs_options: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        self.fs = fs
        self.log_dir = log_dir
        self.recursive = recursive
        self.fs_options = fs_options
        super().__init__(*args, directory=WWW_DIR, **kwargs)

    def do_GET(self) -> None:
        if self.path == LOGS_PATH:
            self.handle_logs()
        elif self.path.startswith(LOG_HEADERS_PATH):
            self.handle_log_headers()
        elif self.path.startswith(LOGS_DIR):
            self.handle_log()
        else:
            super().do_GET()

    def handle_logs(self) -> None:
        """Serve log files listing from /logs/."""
        files = list_eval_logs(
            self.log_dir, recursive=self.recursive, fs_options=self.fs_options
        )
        json_files = json.dumps(
            dict(
                log_dir=self.log_dir_aliased(),
                files=[
                    dict(
                        name=file.name,
                        size=file.size,
                        mtime=file.mtime,
                        task=file.task,
                        task_id=file.task_id,
                    )
                    for file in files
                ],
                indent=2,
            )
        )
        self.send_json(json_files)

    def handle_log_headers(self) -> None:
        # check for query params
        parsed = urlparse(self.path)
        query_params = parse_qs(parsed.query)
        files = query_params.get("file", [])
        headers = read_eval_log_headers(files)
        self.send_json(
            json.dumps(to_jsonable_python(headers, exclude_none=True), indent=2)
        )

    def handle_log(self) -> None:
        """Serve log files from /api/logs/* url."""
        path = self.path.replace(LOGS_DIR, "", 1)  # strip /api/logs/
        path = path.replace("..", "")  # no escape

        # check for query params
        parsed = urlparse(path)

        # read query parameters from the URL
        query_params = parse_qs(parsed.query)
        header_only = query_params.get("header-only", None) is not None

        # reconstruct the path
        path = urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                "",  # Clear the query component
                parsed.fragment,
            )
        )
        path = unquote(path)

        ctype = self.guess_type(path)
        try:
            contents: bytes | None = None
            if header_only:
                try:
                    log = read_eval_log(path, header_only=True)
                    contents = eval_log_json(log).encode()
                except ValueError as ex:
                    logger.info(
                        f"Unable to read headers from log file {path}: {exception_message(ex)}. "
                        + "The file may include a NaN or Inf value. Falling back to reading entire file."
                    )
                    pass

            if contents is None:  # normal read
                with file(path, "rb") as f:
                    # read file and determine its length
                    contents = f.read()

            # respond with the log
            length = len(contents)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-type", ctype)
            self.send_header("Content-Length", str(length))
            self.end_headers()
            self.copyfile(BytesIO(contents), self.wfile)  # type: ignore
        except Exception as error:
            logger.exception(error)
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")

    def events_response(self, params: dict[str, str]) -> list[str]:
        last_eval_time = params.get("last_eval_time", None)
        actions = (
            ["refresh-evals"]
            if last_eval_time and view_last_eval_time() > int(last_eval_time)
            else []
        )
        return super().events_response(params) + actions

    def log_dir_aliased(self) -> str:
        home_dir = os.path.expanduser("~")
        if self.log_dir.startswith(home_dir):
            return self.log_dir.replace(home_dir, "~", 1)
        else:
            return self.log_dir


# lightweight tracking of when the last eval task completed
# this enables the view client to poll for changes frequently
# (e.g. every 1 second) with very minimal overhead.


def view_notify_eval(location: str) -> None:
    file = view_last_eval_file()
    with open(file, "w", encoding="utf-8") as f:
        if not urlparse(location).scheme:
            location = Path(location).absolute().as_posix()

        # Construct a payload with context for the last eval
        payload = {
            "location": location,
        }
        workspace_id = os.environ.get("INSPECT_WORKSPACE_ID")
        if workspace_id:
            payload["workspace_id"] = workspace_id

        # Serialize the payload and write it to the signal file
        payload_json = json.dumps(payload, indent=2)
        f.write(payload_json)


def view_last_eval_time() -> int:
    file = view_last_eval_file()
    if file.exists():
        return int(file.stat().st_mtime * 1000)
    else:
        return 0


def view_runtime_dir() -> Path:
    return inspect_runtime_dir("view")


def view_last_eval_file() -> Path:
    return view_runtime_dir() / "last-eval-result"


def view_port_pid_file(port: int) -> Path:
    ports_dir = view_runtime_dir() / "ports"
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
