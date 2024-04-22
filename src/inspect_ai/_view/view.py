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
from urllib.parse import urlparse

from inspect_ai._display import display
from inspect_ai._display.logger import init_logger
from inspect_ai._util.appdirs import inspect_runtime_dir
from inspect_ai._util.constants import (
    DEFAULT_SERVER_HOST,
    DEFAULT_VIEW_PORT,
)
from inspect_ai._util.dotenv import init_dotenv
from inspect_ai._util.file import FileSystem, file, filesystem
from inspect_ai._util.http import InspectHTTPRequestHandler
from inspect_ai.log._file import log_files_from_ls

logger = logging.getLogger(__name__)


WWW_DIR = os.path.abspath((Path(__file__).parent / "www").as_posix())


LOGS_PATH = "/api/logs"
LOGS_DIR = f"{LOGS_PATH}/"


def view(
    log_dir: str | None = None,
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_VIEW_PORT,
    log_level: str | None = None,
    fs_options: dict[str, Any] = {},
) -> None:
    init_dotenv()
    init_logger(log_level)

    # intialize the right filesytem for this log_dir
    log_dir = log_dir if log_dir else os.getenv("INSPECT_LOG_DIR", "./logs")
    fs = filesystem(log_dir, fs_options)

    # confirm that there are logs to view (this also ensures that the
    # right e.g. S3 credentials are present before we run the server)
    files = [] if not fs.exists(log_dir) else log_files_from_ls(fs.ls(log_dir))
    if len(files) == 0:
        print(f"No log files currently available in {log_dir}")
        sys.exit(0)

    # run server
    view_handler = partial(ViewHTTPRequestHandler, fs=fs, log_dir=log_dir)
    httpd = HTTPServer((host, port), view_handler)
    display().print(f"Inspect view running at http://localhost:{port}/")
    httpd.serve_forever()


class ViewHTTPRequestHandler(InspectHTTPRequestHandler):
    def __init__(self, *args: Any, fs: FileSystem, log_dir: str, **kwargs: Any) -> None:
        self.fs = fs
        self.log_dir = log_dir
        super().__init__(*args, directory=WWW_DIR, **kwargs)

    def do_GET(self) -> None:
        if self.path == LOGS_PATH:
            self.handle_logs()
        elif self.path.startswith(LOGS_DIR):
            self.handle_log()
        else:
            super().do_GET()

    def handle_logs(self) -> None:
        """Serve log files listing from /logs/."""
        files = log_files_from_ls(self.fs.ls(self.log_dir))
        json_files = json.dumps(
            dict(
                log_dir=self.log_dir,
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

    def handle_log(self) -> None:
        """Serve log files from /logs/* url."""
        path = self.path.replace(LOGS_DIR, "", 1)  # strip /logs
        path = path.replace("/", "").replace("\\", "")  # no escape
        log_path = os.path.join(self.log_dir, path)
        ctype = self.guess_type(log_path)
        try:
            with file(log_path, "rb") as f:
                # read file and determine its length
                contents = f.read()
                length = len(contents)
                # respond with the log
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


# lightweight tracking of when the last eval task completed
# this enables the view client to poll for changes frequently
# (e.g. every 1 second) with very minimal overhead.


def view_notify_eval(location: str) -> None:
    file = view_last_eval_file()
    with open(file, "w", encoding="utf-8") as f:
        if not urlparse(location).scheme:
            location = Path(location).absolute().as_posix()
        f.write(location)


def view_last_eval_time() -> int:
    file = view_last_eval_file()
    if file.exists():
        return int(file.stat().st_mtime * 1000)
    else:
        return 0


def view_last_eval_file() -> Path:
    return inspect_runtime_dir("view") / "last-eval"
