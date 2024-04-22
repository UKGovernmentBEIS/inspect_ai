import glob
import json
import os
import posixpath
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler
from io import BytesIO
from typing import Any
from urllib.parse import parse_qs, urlparse

from .dev import is_dev_mode


class InspectHTTPRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, directory: str, **kwargs: Any) -> None:
        # note whether we are in dev mode (i.e. developing the package)
        self.dev_mode = is_dev_mode()

        # initialize file serving directory
        directory = os.path.abspath(directory)
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self) -> None:
        if self.path.startswith("/api/events"):
            self.handle_events()
        else:
            super().do_GET()

    def handle_events(self) -> None:
        """Client polls for events (e.g. dev reload) ~ every 1 second."""
        query = parse_qs(urlparse(self.path).query)
        params = dict(zip(query.keys(), [value[0] for value in query.values()]))
        self.send_json(json.dumps(self.events_response(params)))

    def events_response(self, params: dict[str, str]) -> list[str]:
        """Send back a 'reload' event if we have modified source files."""
        loaded_time = params.get("loaded_time", None)
        return (
            ["reload"] if loaded_time and self.should_reload(int(loaded_time)) else []
        )

    def translate_path(self, path: str) -> str:
        """Ensure that paths don't escape self.directory."""
        translated = super().translate_path(path)
        if not os.path.abspath(translated).startswith(self.directory):
            return self.directory
        else:
            return translated

    def send_json(self, json: str | bytes) -> None:
        if isinstance(json, str):
            json = json.encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.copyfile(BytesIO(json), self.wfile)  # type: ignore

    def send_response(self, code: int, message: str | None = None) -> None:
        """No client side or proxy caches."""
        super().send_response(code, message)
        self.send_header("Expires", "Fri, 01 Jan 1990 00:00:00 GMT")
        self.send_header("Pragma", "no-cache")
        self.send_header(
            "Cache-Control", "no-cache, no-store, max-age=0, must-revalidate"
        )

    def guess_type(self, path: str | os.PathLike[str]) -> str:
        _, ext = posixpath.splitext(path)
        if not ext or ext == ".mjs" or ext == ".js":
            return "application/javascript"
        elif ext == ".md":
            return "text/markdown"
        else:
            return super().guess_type(path)

    def log_error(self, format: str, *args: Any) -> None:
        if self.dev_mode:
            super().log_error(format, *args)

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        """Don't log status 200 or 404 (too chatty)."""
        if code not in [200, 404]:
            super().log_request(code, size)

    def should_reload(self, loaded_time: int) -> bool:
        if self.dev_mode:
            for dir in self.reload_dirs():
                files = [
                    os.stat(file).st_mtime
                    for file in glob.glob(f"{dir}/**/*", recursive=True)
                ]
                last_modified = max(files) * 1000
                if last_modified > loaded_time:
                    return True

        return False

    def reload_dirs(self) -> list[str]:
        return [self.directory]
