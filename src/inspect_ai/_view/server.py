import os
from pathlib import Path
from typing import Any

from aiohttp import web
from pydantic_core import to_jsonable_python

from inspect_ai._display import display
from inspect_ai._util.constants import DEFAULT_SERVER_HOST, DEFAULT_VIEW_PORT
from inspect_ai.log._file import EvalLogInfo, list_eval_logs, read_eval_log_headers

from .notify import view_last_eval_time

WWW_DIR = os.path.abspath((Path(__file__).parent / "www" / "dist").as_posix())


def view_server(
    log_dir: str,
    recursive: bool = True,
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_VIEW_PORT,
    fs_options: dict[str, Any] = {},
) -> None:
    # /api/logs
    async def api_logs(_: web.Request) -> web.Response:
        logs = list_eval_logs(
            log_dir=log_dir, recursive=recursive, fs_options=fs_options
        )
        return web.json_response(log_listing(logs, log_dir))

    # /api/log-headers
    async def api_log_headers(request: web.Request) -> web.Response:
        files = request.query.getall("file", [])
        headers = read_eval_log_headers(files)
        return web.json_response(to_jsonable_python(headers, exclude_none=True))

    # /api/events
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
    app.add_routes([web.get("/api/logs", api_logs)])
    app.add_routes([web.get("/api/log-headers", api_log_headers)])
    app.add_routes([web.get("/api/events", api_events)])
    app.router.add_static("/", WWW_DIR)

    # notify user
    display().print(f"Inspect view running at http://localhost:{port}/")

    # run app
    web.run_app(app=app, host=host, port=port)


def log_listing(logs: list[EvalLogInfo], log_dir: str) -> dict[str, Any]:
    return dict(
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


def aliased_path(path: str) -> str:
    home_dir = os.path.expanduser("~")
    if path.startswith(home_dir):
        return path.replace(home_dir, "~", 1)
    else:
        return path
