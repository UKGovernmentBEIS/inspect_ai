import logging
import os
from logging import LogRecord, getLogger
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from inspect_ai._display import display
from inspect_ai._util.constants import DEFAULT_SERVER_HOST, DEFAULT_VIEW_PORT

from .routes import create_inspect_view_router

logger = getLogger(__name__)


def view_server(
    log_dir: str,
    recursive: bool = True,
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_VIEW_PORT,
    authorization: str | None = None,
    fs_options: dict[str, Any] = {},
) -> None:
    def auth_callback(request: Request) -> bool:
        if not authorization:
            return True
        return request.headers.get("Authorization") == authorization

    app = FastAPI()

    router = create_inspect_view_router(
        log_dir=log_dir,
        recursive=recursive,
        fs_options=fs_options,
        auth_callback=auth_callback if authorization else None,
    )

    app.include_router(router)

    www_path = os.path.abspath((Path(__file__).parent / "www" / "dist").as_posix())
    app.mount("/", StaticFiles(directory=www_path, html=True), name="static")

    filter_uvicorn_log()

    display().print(f"Inspect View: {log_dir}")
    uvicorn.run(
        app,
        host=host,
        port=port,
    )


def filter_uvicorn_log() -> None:
    """Filter out noisy /api/events requests from access logs."""

    class RequestFilter(logging.Filter):
        def filter(self, record: LogRecord) -> bool:
            return "/api/events" not in record.getMessage()

    access_logger = getLogger("uvicorn.access")
    for existing_filter in access_logger.filters:
        if isinstance(existing_filter, RequestFilter):
            return

    access_logger.addFilter(RequestFilter())
