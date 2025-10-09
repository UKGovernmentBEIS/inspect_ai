import json
import logging
import urllib.parse
from logging import getLogger
from pathlib import Path
from typing import Any, Protocol

import anyio
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, Response
from pydantic_core import to_jsonable_python
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles
from starlette.status import (
    HTTP_204_NO_CONTENT,
    HTTP_304_NOT_MODIFIED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
)
from typing_extensions import override

from inspect_ai._display.core.active import display
from inspect_ai._eval.evalset import read_eval_set_info
from inspect_ai._util.constants import DEFAULT_SERVER_HOST, DEFAULT_VIEW_PORT
from inspect_ai._util.file import filesystem
from inspect_ai._view import notify
from inspect_ai._view.common import (
    delete_log,
    get_log_bytes,
    get_log_file,
    get_log_size,
    get_logs,
    normalize_uri,
)
from inspect_ai.log._file import read_eval_log_headers_async
from inspect_ai.log._recorders.buffer import sample_buffer

logger = getLogger(__name__)


class AccessPolicy(Protocol):
    async def can_read(self, request: Request, file: str) -> bool: ...

    async def can_delete(self, request: Request, file: str) -> bool: ...

    async def can_list(self, request: Request, dir: str) -> bool: ...


class FileMappingPolicy(Protocol):
    async def map(self, request: Request, file: str) -> str: ...

    async def unmap(self, request: Request, file: str) -> str: ...


class InspectJsonResponse(JSONResponse):
    """Like the standard starlette JSON, but allows NaN."""

    @override
    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=True,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")


def view_server_app(
    mapping_policy: FileMappingPolicy | None = None,
    access_policy: AccessPolicy | None = None,
    default_dir: str = "",
    recursive: bool = True,
    fs_options: dict[str, Any] = {},
) -> "FastAPI":
    app = FastAPI()

    async def _map_file(request: Request, file: str) -> str:
        if mapping_policy is not None:
            return await mapping_policy.map(request, file)
        return file

    async def _unmap_file(request: Request, file: str) -> str:
        if mapping_policy is not None:
            return await mapping_policy.unmap(request, file)
        return file

    async def _validate_read(request: Request, file: str) -> None:
        if access_policy is not None:
            if not await access_policy.can_read(request, file):
                raise HTTPException(status_code=HTTP_403_FORBIDDEN)

    async def _validate_delete(request: Request, file: str) -> None:
        if access_policy is not None:
            if not await access_policy.can_delete(request, file):
                raise HTTPException(status_code=HTTP_403_FORBIDDEN)

    async def _validate_list(request: Request, file: str) -> None:
        if access_policy is not None:
            if not await access_policy.can_list(request, file):
                raise HTTPException(status_code=HTTP_403_FORBIDDEN)

    @app.get("/logs/{log:path}")
    async def api_log(
        request: Request,
        log: str,
        header_only: str | None = Query(None, alias="header-only"),
    ) -> Response:
        file = normalize_uri(log)
        await _validate_read(request, file)
        body = await get_log_file(await _map_file(request, file), header_only)
        return Response(content=body, media_type="application/json")

    @app.get("/log-size/{log:path}")
    async def api_log_size(request: Request, log: str) -> Response:
        file = normalize_uri(log)
        await _validate_read(request, file)
        size = await get_log_size(await _map_file(request, file))
        return InspectJsonResponse(content=size)

    @app.get("/log-delete/{log:path}")
    async def api_log_delete(request: Request, log: str) -> Response:
        file = normalize_uri(log)
        await _validate_delete(request, file)
        await delete_log(await _map_file(request, file))

        return InspectJsonResponse(content=True)

    @app.get("/log-bytes/{log:path}")
    async def api_log_bytes(
        request: Request,
        log: str,
        start: int = Query(...),
        end: int = Query(...),
    ) -> Response:
        file = normalize_uri(log)
        await _validate_read(request, file)
        response = await get_log_bytes(await _map_file(request, file), start, end)
        return Response(
            content=response,
            headers={"Content-Length": str(end - start + 1)},
            media_type="application/octet-stream",
        )

    @app.get("/logs")
    async def api_logs(
        request: Request,
        log_dir: str | None = Query(None, alias="log_dir"),
    ) -> Response:
        if log_dir is None:
            log_dir = default_dir
        await _validate_list(request, log_dir)
        listing = await get_logs(
            await _map_file(request, log_dir),
            recursive=recursive,
            fs_options=fs_options,
        )
        if listing is None:
            return Response(status_code=HTTP_404_NOT_FOUND)
        for file in listing["files"]:
            file["name"] = await _unmap_file(request, file["name"])
        return InspectJsonResponse(content=listing)

    @app.get("/eval-set")
    async def eval_set(
        request: Request, log_dir: str = Query(None, alias="dir")
    ) -> Response:
        if log_dir is None:
            log_dir = default_dir
        await _validate_read(request, log_dir)

        eval_set = read_eval_set_info(
            await _map_file(request, log_dir), fs_options=fs_options
        )
        return InspectJsonResponse(
            content=eval_set.model_dump(exclude_none=True) if eval_set else None
        )

    @app.get("/log-headers")
    async def api_log_headers(
        request: Request, file: list[str] = Query([])
    ) -> Response:
        files = [normalize_uri(f) for f in file]
        async with anyio.create_task_group() as tg:
            for f in files:
                tg.start_soon(_validate_read, request, f)
        headers = await read_eval_log_headers_async(
            [await _map_file(request, file) for file in files]
        )
        return InspectJsonResponse(to_jsonable_python(headers, exclude_none=True))

    @app.get("/events")
    async def api_events(
        last_eval_time: str | None = None,
    ) -> Response:
        actions = (
            ["refresh-evals"]
            if last_eval_time and notify.view_last_eval_time() > int(last_eval_time)
            else []
        )
        return InspectJsonResponse(actions)

    @app.get("/pending-samples")
    async def api_pending_samples(request: Request, log: str = Query(...)) -> Response:
        file = urllib.parse.unquote(log)
        await _validate_read(request, file)

        client_etag = request.headers.get("If-None-Match")

        buffer = sample_buffer(await _map_file(request, file))
        samples = buffer.get_samples(client_etag)
        if samples == "NotModified":
            return Response(status_code=HTTP_304_NOT_MODIFIED)
        elif samples is None:
            return Response(status_code=HTTP_404_NOT_FOUND)
        else:
            return InspectJsonResponse(
                content=samples.model_dump(),
                headers={"ETag": samples.etag},
            )

    @app.get("/log-message")
    async def api_log_message(
        request: Request, log_file: str, message: str
    ) -> Response:
        file = urllib.parse.unquote(log_file)
        await _validate_read(request, file)

        logger = logging.getLogger(__name__)
        logger.warning(f"[CLIENT MESSAGE] ({file}): {message}")

        return Response(status_code=HTTP_204_NO_CONTENT)

    @app.get("/pending-sample-data")
    async def api_sample_events(
        request: Request,
        log: str,
        id: str,
        epoch: int,
        last_event_id: int | None = Query(None, alias="last-event-id"),
        after_attachment_id: int | None = Query(None, alias="after-attachment-id"),
    ) -> Response:
        file = urllib.parse.unquote(log)
        await _validate_read(request, file)

        buffer = sample_buffer(await _map_file(request, file))
        sample_data = buffer.get_sample_data(
            id=id,
            epoch=epoch,
            after_event_id=last_event_id,
            after_attachment_id=after_attachment_id,
        )

        if sample_data is None:
            return Response(status_code=HTTP_404_NOT_FOUND)
        else:
            return InspectJsonResponse(content=sample_data.model_dump())

    return app


def filter_fastapi_log() -> None:
    #  filter overly chatty /api/events messages
    class RequestFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return "/api/events" not in record.getMessage()

    # don't add if we already have
    access_logger = getLogger("uvicorn.access")
    for existing_filter in access_logger.filters:
        if isinstance(existing_filter, RequestFilter):
            return

    # add the filter
    access_logger.addFilter(RequestFilter())


def authorization_middleware(authorization: str) -> type[BaseHTTPMiddleware]:
    class AuthorizationMiddleware(BaseHTTPMiddleware):
        async def dispatch(
            self, request: Request, call_next: RequestResponseEndpoint
        ) -> Response:
            auth_header = request.headers.get("authorization", None)
            if auth_header != authorization:
                return Response("Unauthorized", status_code=401)
            return await call_next(request)

    return AuthorizationMiddleware


class OnlyLogDirAccessPolicy(AccessPolicy):
    def __init__(self, log_dir: str) -> None:
        super().__init__()
        self.log_dir = log_dir

    def _validate_log_dir(self, file: str) -> bool:
        return file.startswith(self.log_dir) and ".." not in file

    async def can_read(self, request: Request, file: str) -> bool:
        return self._validate_log_dir(file)

    async def can_delete(self, request: Request, file: str) -> bool:
        return self._validate_log_dir(file)

    async def can_list(self, request: Request, dir: str) -> bool:
        return self._validate_log_dir(dir)


def view_server(
    log_dir: str,
    recursive: bool = True,
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_VIEW_PORT,
    authorization: str | None = None,
    fs_options: dict[str, Any] = {},
) -> None:
    # get filesystem and resolve log_dir to full path
    fs = filesystem(log_dir)
    if not fs.exists(log_dir):
        fs.mkdir(log_dir, True)
    log_dir = fs.info(log_dir).name

    # setup server
    api = view_server_app(
        mapping_policy=None,
        access_policy=OnlyLogDirAccessPolicy(log_dir) if not authorization else None,
        default_dir=log_dir,
        recursive=recursive,
        fs_options=fs_options,
    )

    app = FastAPI()
    app.mount("/api", api)

    dist = Path(__file__).parent / "www" / "dist"
    app.mount("/", StaticFiles(directory=dist.as_posix(), html=True), name="static")

    if authorization:
        app.add_middleware(authorization_middleware(authorization))

    # filter request log (remove /api/events)
    filter_fastapi_log()

    # run app
    display().print(f"Inspect View: {log_dir}")
    uvicorn.run(app, host=host, port=port, log_config=None)
