import os
import urllib.parse
from logging import getLogger
from pathlib import Path
from typing import Any

from aiohttp import web
from pydantic_core import to_jsonable_python

from inspect_ai._util.constants import DEFAULT_SERVER_HOST, DEFAULT_VIEW_PORT
from inspect_ai._util.file import size_in_mb
from inspect_ai.log._file import (
    EvalLogInfo,
    eval_log_json,
    list_eval_logs,
    read_eval_log,
    read_eval_log_headers,
)

from .notify import view_last_eval_time

WWW_DIR = os.path.abspath((Path(__file__).parent / "www" / "dist").as_posix())


logger = getLogger(__name__)


# TODO: byte range

# TODO: writing zip file using stream
# TODO: flushing zip file


def view_server(
    log_dir: str,
    recursive: bool = True,
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_VIEW_PORT,
    fs_options: dict[str, Any] = {},
) -> None:
    routes = web.RouteTableDef()

    @routes.get("/api/logs/{log}")
    async def api_log(request: web.Request) -> web.Response:
        # log file requested
        file = request.match_info["log"]
        file = urllib.parse.unquote(file)

        # header_only is based on a size threshold
        header_only = request.query.get("header-only", None)
        return log_file_response(file, header_only)

    @routes.get("/api/logs")
    async def api_logs(_: web.Request) -> web.Response:
        logs = list_eval_logs(
            log_dir=log_dir, recursive=recursive, fs_options=fs_options
        )
        return log_listing_response(logs, log_dir)

    @routes.get("/api/log-headers")
    async def api_log_headers(request: web.Request) -> web.Response:
        files = request.query.getall("file", [])
        return log_headers_response(files)

    @routes.get("/api/events")
    async def api_events(request: web.Request) -> web.Response:
        last_eval_time = request.query.get("last_eval_time", None)
        actions = (
            ["refresh-evals"]
            if last_eval_time and view_last_eval_time() > int(last_eval_time)
            else []
        )
        return web.json_response(actions)

    # setup app and routes
    app = web.Application()
    app.router.add_routes(routes)
    app.router.register_resource(WWWResource())

    # run app
    web.run_app(app=app, host=host, port=port, print=print)


def log_listing_response(logs: list[EvalLogInfo], log_dir: str) -> web.Response:
    response = dict(
        log_dir=aliased_path(log_dir),
        files=[
            dict(
                name=log.name,
                size=log.size,
                mtime=log.mtime,
                task=log.task,
                task_id=log.task_id,
            )
            for log in logs
        ],
    )
    return web.json_response(response)


def log_file_response(file: str, header_only_param: str | None) -> web.Response:
    # resolve header_only
    header_only_mb = int(header_only_param) if header_only_param is not None else None
    header_only = resolve_header_only(file, header_only_mb)

    try:
        contents: bytes | None = None
        if header_only:
            try:
                log = read_eval_log(file, header_only=True)
                contents = eval_log_json(log).encode()
            except ValueError as ex:
                logger.info(
                    f"Unable to read headers from log file {file}: {ex}. "
                    + "The file may include a NaN or Inf value. Falling back to reading entire file."
                )

        if contents is None:  # normal read
            log = read_eval_log(file, header_only=False)
            contents = eval_log_json(log).encode()

        return web.Response(body=contents, content_type="application/json")

    except Exception as error:
        logger.exception(error)
        return web.Response(status=500, reason="File not found")


def log_headers_response(files: list[str]) -> web.Response:
    headers = read_eval_log_headers(files)
    return web.json_response(to_jsonable_python(headers, exclude_none=True))


class WWWResource(web.StaticResource):
    def __init__(self) -> None:
        super().__init__("", WWW_DIR)

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        # serve /index.html for /
        filename = request.match_info["filename"]
        if not filename:
            request.match_info["filename"] = "index.html"

        # call super
        response = await super()._handle(request)

        # disable caching as this is only ever served locally
        # and w/ caching sometimes we get stale assets
        response.headers.update(
            {
                "Expires": "Fri, 01 Jan 1990 00:00:00 GMT",
                "Pragma": "no-cache",
                "Cache-Control": "no-cache, no-store, max-age=0, must-revalidate",
            }
        )

        # return response
        return response


def aliased_path(path: str) -> str:
    home_dir = os.path.expanduser("~")
    if path.startswith(home_dir):
        return path.replace(home_dir, "~", 1)
    else:
        return path


def resolve_header_only(path: str, header_only: int | None) -> bool:
    # if there is a max_size passed, respect that and switch to
    # header_only mode if the file is too large
    if header_only == 0:
        return True
    if header_only is not None and size_in_mb(path) > int(header_only):
        return True
    else:
        return False
