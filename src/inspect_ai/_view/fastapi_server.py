import json
import logging
import os
import secrets
import urllib.parse
from io import BytesIO
from logging import getLogger
from pathlib import Path
from typing import Any, Protocol

import anyio
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles
from starlette.status import (
    HTTP_204_NO_CONTENT,
    HTTP_304_NOT_MODIFIED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
)
from starlette.types import ASGIApp, Scope
from typing_extensions import override

from inspect_ai._display.core.active import display
from inspect_ai._eval.evalset import EvalSet, read_eval_set_info
from inspect_ai._util.asyncfiles import AsyncFilesystem, bind_async_filesystem
from inspect_ai._util.constants import DEFAULT_SERVER_HOST, DEFAULT_VIEW_PORT
from inspect_ai._util.error import WriteConflictError
from inspect_ai._util.file import filesystem
from inspect_ai._util.local_server import get_machine_ip
from inspect_ai.log import EvalLog
from inspect_ai.log._edit import LogUpdate
from inspect_ai.log._file import read_eval_log_headers_async
from inspect_ai.log._recorders.buffer import sample_buffer
from inspect_ai.log._recorders.buffer.types import (
    PendingSampleUrls,
    SampleData,
    Samples,
)

from ._dist import resolve_dist_directory
from .common import (
    AppConfig,
    LogDirResponse,
    LogFilesResponse,
    LogInfo,
    LogInProgressError,
    LogListingResponse,
    apply_log_edits,
    build_pending_sample_urls,
    delete_log,
    get_app_config,
    get_log_dir,
    get_log_file,
    get_log_files,
    get_log_info,
    get_log_size,
    get_logs,
    normalize_uri,
    parse_log_token,
    read_eval_set_info_async,
    stream_log_bytes,
)
from .network import (
    BrowserOriginMiddleware,
    HostValidationMiddleware,
    SecurityHeadersMiddleware,
    ViewerNetworkPolicy,
    resolve_viewer_network_policy,
    unsafe_network_warning,
)
from .notify import view_last_eval_time
from .scout_routes import get_scout_search_router
from .user_info import UserInfo, user_info

logger = getLogger(__name__)

VIEW_REQUEST_HEADER = "X-Inspect-View-Request"
VIEW_REQUEST_HEADER_VALUE = "true"

SHARED_FS_CLIENT_TTL_SECONDS = 15 * 60


class AccessPolicy(Protocol):
    async def can_read(self, request: Request, file: str) -> bool: ...

    async def can_delete(self, request: Request, file: str) -> bool: ...

    async def can_list(self, request: Request, dir: str) -> bool: ...

    async def can_write(self, request: Request, file: str) -> bool: ...


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
    generate_direct_urls: bool = False,
) -> "FastAPI":
    app = FastAPI()

    @app.exception_handler(FileNotFoundError)
    async def _file_not_found(_request: Request, _exc: FileNotFoundError) -> Response:
        return Response(status_code=HTTP_404_NOT_FOUND)

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

    async def _validate_write(request: Request, file: str) -> None:
        if access_policy is not None:
            if not await access_policy.can_write(request, file):
                raise HTTPException(status_code=HTTP_403_FORBIDDEN)

    async def _validate_list(request: Request, file: str) -> None:
        if access_policy is not None:
            if not await access_policy.can_list(request, file):
                raise HTTPException(status_code=HTTP_403_FORBIDDEN)

    def _validate_mutating_request(request: Request) -> None:
        if request.headers.get(VIEW_REQUEST_HEADER) != VIEW_REQUEST_HEADER_VALUE:
            raise HTTPException(status_code=HTTP_403_FORBIDDEN)

        fetch_dest = request.headers.get("Sec-Fetch-Dest")
        if fetch_dest is not None and fetch_dest != "empty":
            raise HTTPException(status_code=HTTP_403_FORBIDDEN)

    @app.get("/logs/{log:path}", response_model=EvalLog)
    async def api_log(
        request: Request,
        log: str,
        header_only: str | None = Query(None, alias="header-only"),
    ) -> Response:
        file = normalize_uri(log)
        await _validate_read(request, file)
        body, etag = await get_log_file(await _map_file(request, file), header_only)
        headers = {"ETag": etag} if etag is not None else {}
        return Response(content=body, media_type="application/json", headers=headers)

    @app.get("/log-size/{log:path}")
    async def api_log_size(request: Request, log: str) -> int:
        file = normalize_uri(log)
        await _validate_read(request, file)
        return await get_log_size(await _map_file(request, file))

    @app.get("/log-info/{log:path}", response_model_exclude_none=True)
    async def api_log_info(request: Request, log: str) -> LogInfo:
        file = normalize_uri(log)
        await _validate_read(request, file)
        return await get_log_info(
            await _map_file(request, file),
            generate_direct_url=generate_direct_urls,
        )

    @app.delete("/log-delete/{log:path}")
    async def api_log_delete(request: Request, log: str) -> bool:
        _validate_mutating_request(request)
        file = normalize_uri(log)
        await _validate_delete(request, file)
        await delete_log(await _map_file(request, file))
        return True

    @app.post("/log-edit/{log:path}", response_model=EvalLog)
    async def api_log_edit(request: Request, log: str, update: LogUpdate) -> Response:
        _validate_mutating_request(request)
        file = normalize_uri(log)
        await _validate_write(request, file)
        if_match = request.headers.get("If-Match")
        try:
            contents, new_etag = await apply_log_edits(
                await _map_file(request, file), update, if_match_etag=if_match
            )
        except LogInProgressError as ex:
            # 409 Conflict — the recorder still owns the file. Distinct
            # from 412 (stale ETag) and 400 (bad input).
            raise HTTPException(status_code=409, detail=str(ex))
        except ValueError as ex:
            raise HTTPException(status_code=400, detail=str(ex))
        except WriteConflictError as ex:
            raise HTTPException(status_code=412, detail=str(ex))
        headers = {"ETag": new_etag} if new_etag is not None else {}
        return Response(
            content=contents, media_type="application/json", headers=headers
        )

    @app.get("/log-bytes/{log:path}")
    async def api_log_bytes(
        request: Request,
        log: str,
        start: int = Query(...),
        end: int = Query(...),
    ) -> Response:
        file = normalize_uri(log)
        await _validate_read(request, file)
        mapped_file = await _map_file(request, file)

        # Get actual file size to clamp the requested range
        file_size = await get_log_size(mapped_file)

        if start >= file_size:
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        actual_end = min(end, file_size - 1)

        response = await stream_log_bytes(
            mapped_file, start, actual_end, log_file_size=file_size
        )

        if isinstance(response, BytesIO):
            # Return in-memory bytes directly: StreamingResponse would iterate
            # the BytesIO line-by-line (newline-split binary chunks), sending
            # each through a threadpool hop — ~1MB/s for local range reads.
            return Response(
                content=response.getvalue(),
                media_type="application/octet-stream",
            )
        else:
            # For S3 streaming responses, omit Content-Length to use chunked
            # transfer encoding. The file may change between get_log_size()
            # and the actual S3 read (e.g. in-progress evals being rewritten),
            # which would cause a Content-Length mismatch.
            return StreamingResponse(
                content=response,
                media_type="application/octet-stream",
            )

    @app.get("/log-download/{log:path}")
    async def api_log_download(
        request: Request,
        log: str,
    ) -> Response:
        file = normalize_uri(log)
        await _validate_read(request, file)

        mapped_file = await _map_file(request, file)

        file_size = await get_log_size(mapped_file)
        stream = await stream_log_bytes(mapped_file, log_file_size=file_size)

        base_name = Path(file).stem
        filename = f"{base_name}.eval"

        # No explicit Content-Length: the file may change between
        # get_log_size() and the read (in-progress evals are rewritten
        # in place), and a stale size makes clients fail the download.
        # The buffered branch lets the framework set it from the actual
        # body; the streaming branch uses chunked transfer encoding
        # (same rationale as /log-bytes above).
        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
        }

        if isinstance(stream, BytesIO):
            return Response(
                content=stream.getvalue(),
                headers=headers,
                media_type="application/octet-stream",
            )
        else:
            return StreamingResponse(
                content=stream,
                headers=headers,
                media_type="application/octet-stream",
            )

    @app.get("/log-dir")
    async def api_log_dir(
        request: Request,
        log_dir: str | None = Query(None, alias="log_dir"),
    ) -> LogDirResponse:
        if log_dir is None:
            log_dir = default_dir
        await _validate_list(request, log_dir)
        return get_log_dir(log_dir)

    @app.get("/log-files", response_class=InspectJsonResponse)
    async def api_log_files(
        request: Request,
        log_dir: str | None = Query(None, alias="log_dir"),
    ) -> LogFilesResponse:
        if log_dir is None:
            log_dir = default_dir
        await _validate_list(request, log_dir)

        client_etag = request.headers.get("If-None-Match")
        mtime = 0.0
        file_count = 0
        if client_etag is not None:
            mtime, file_count = parse_log_token(client_etag)
        result = await get_log_files(
            await _map_file(request, log_dir),
            recursive=recursive,
            fs_options=fs_options,
            mtime=mtime,
            file_count=file_count,
        )
        for entry in result.files:
            entry.name = await _unmap_file(request, entry.name)
        return result

    @app.get(
        "/logs", response_model=LogListingResponse, response_class=InspectJsonResponse
    )
    async def api_logs(
        request: Request,
        log_dir: str | None = Query(None, alias="log_dir"),
    ) -> LogListingResponse | Response:
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
        for entry in listing.files:
            entry.name = await _unmap_file(request, entry.name)
        listing.log_dir = await _unmap_file(request, listing.log_dir)
        if listing.log_dir_uri is not None:
            listing.log_dir_uri = await _unmap_file(request, listing.log_dir_uri)
        return listing

    @app.get(
        "/eval-set",
        response_class=InspectJsonResponse,
        response_model_exclude_none=True,
    )
    async def eval_set(
        request: Request,
        log_dir: str = Query(None, alias="log_dir"),
        sub_dir: str = Query(None, alias="dir"),
    ) -> EvalSet | None:
        # resolve the eval-set directory (using the log_dir and dir params)
        base_dir = log_dir if log_dir else default_dir
        if sub_dir and base_dir:
            eval_set_dir = base_dir + "/" + sub_dir.lstrip("/")
        elif sub_dir:
            eval_set_dir = sub_dir.lstrip("/")
        else:
            eval_set_dir = base_dir

        # validate that the directory can be listed
        await _validate_list(request, eval_set_dir)

        # return the eval set info for this directory (async fs, not to_thread —
        # see the fsspec/to_thread warning in AGENTS.md)
        mapped = await _map_file(request, eval_set_dir)
        if fs_options:
            return read_eval_set_info(mapped, fs_options=fs_options)
        async with AsyncFilesystem() as afs:
            return await read_eval_set_info_async(mapped, afs)

    @app.get("/flow")
    async def flow(
        request: Request,
        log_dir: str = Query(None, alias="log_dir"),
        sub_dir: str = Query(None, alias="dir"),
    ) -> Response:
        # resolve the eval-set directory (using the log_dir and dir params)
        base_dir = log_dir if log_dir else default_dir
        if sub_dir and base_dir:
            flow_dir = base_dir + "/" + sub_dir.lstrip("/")
        elif sub_dir:
            flow_dir = sub_dir.lstrip("/")
        else:
            flow_dir = base_dir

        # validate that the directory can be listed
        await _validate_list(request, flow_dir)

        mapped_dir = await _map_file(request, flow_dir)
        sep = filesystem(mapped_dir).sep
        flow_file = f"{mapped_dir.rstrip('/').rstrip(sep)}{sep}flow.yaml"

        # async fs, not to_thread — see the fsspec/to_thread warning in AGENTS.md
        async with AsyncFilesystem() as afs:
            content = (
                await afs.read_file(flow_file) if await afs.exists(flow_file) else None
            )
        if content is not None:
            return Response(
                content=content.decode("utf-8"),
                status_code=200,
                media_type="text/yaml",
            )
        else:
            return Response(status_code=HTTP_404_NOT_FOUND)

    @app.get(
        "/log-headers",
        response_class=InspectJsonResponse,
        response_model_exclude_none=True,
    )
    async def api_log_headers(
        request: Request, file: list[str] = Query([])
    ) -> list[EvalLog]:
        files = [normalize_uri(f) for f in file]
        mapped_files: list[str] = [""] * len(files)

        async def _validate_and_map(idx: int, f: str) -> None:
            await _validate_read(request, f)
            mapped_files[idx] = await _map_file(request, f)

        async with anyio.create_task_group() as tg:
            for i, f in enumerate(files):
                tg.start_soon(_validate_and_map, i, f)

        return await read_eval_log_headers_async(mapped_files)

    @app.get("/user-info", response_model_exclude_none=True)
    async def api_user_info() -> UserInfo:
        return user_info()

    @app.get("/events")
    async def api_events(
        last_eval_time: str | None = None,
    ) -> list[str]:
        return (
            ["refresh-evals"]
            if last_eval_time and view_last_eval_time() > int(last_eval_time)
            else []
        )

    @app.get(
        "/pending-samples", response_model=Samples, response_class=InspectJsonResponse
    )
    async def api_pending_samples(
        request: Request, response: Response, log: str = Query(...)
    ) -> Samples | Response:
        file = urllib.parse.unquote(log)
        await _validate_read(request, file)

        client_etag = request.headers.get("If-None-Match")

        # NOTE: sync on the event loop. The sample buffer can be filestore-backed
        # (fsspec) and must not be wrapped in to_thread — see the fsspec/to_thread
        # warning in AGENTS.md.
        buffer = sample_buffer(await _map_file(request, file))
        samples = buffer.get_samples(client_etag)
        if samples == "NotModified":
            return Response(status_code=HTTP_304_NOT_MODIFIED)
        elif samples is None:
            return Response(status_code=HTTP_404_NOT_FOUND)
        else:
            response.headers["ETag"] = samples.etag
            return samples

    @app.post("/log-message")
    async def api_log_message(
        request: Request, log_file: str, message: str
    ) -> Response:
        _validate_mutating_request(request)
        file = urllib.parse.unquote(log_file)
        await _validate_read(request, file)

        logger = logging.getLogger(__name__)
        logger.warning(f"[CLIENT MESSAGE] ({file}): {message}")

        return Response(status_code=HTTP_204_NO_CONTENT)

    @app.get(
        "/pending-sample-data",
        response_model=SampleData,
        response_class=InspectJsonResponse,
    )
    async def api_sample_events(
        request: Request,
        log: str,
        id: str,
        epoch: int,
        last_event_id: int | None = Query(None, alias="last-event-id"),
        after_attachment_id: int | None = Query(None, alias="after-attachment-id"),
        after_message_pool_id: int | None = Query(None, alias="after-message-pool-id"),
        after_call_pool_id: int | None = Query(None, alias="after-call-pool-id"),
    ) -> SampleData | Response:
        file = urllib.parse.unquote(log)
        await _validate_read(request, file)

        # NOTE: sync on the event loop. The sample buffer can be filestore-backed
        # (fsspec) and must not be wrapped in to_thread — see the fsspec/to_thread
        # warning in AGENTS.md.
        buffer = sample_buffer(await _map_file(request, file))
        sample_data = buffer.get_sample_data(
            id=id,
            epoch=epoch,
            after_event_id=last_event_id,
            after_attachment_id=after_attachment_id,
            after_message_pool_id=after_message_pool_id,
            after_call_pool_id=after_call_pool_id,
        )

        if sample_data is None:
            return Response(status_code=HTTP_404_NOT_FOUND)
        else:
            return sample_data

    @app.get(
        "/pending-sample-data-urls",
        response_model=PendingSampleUrls,
        response_model_exclude_none=False,
        response_class=InspectJsonResponse,
    )
    async def api_pending_sample_data_urls(
        request: Request,
        log: str,
        id: str,
        epoch: int,
        last_event_id: int | None = Query(None, alias="last-event-id"),
        after_attachment_id: int | None = Query(None, alias="after-attachment-id"),
        after_message_pool_id: int | None = Query(None, alias="after-message-pool-id"),
        after_call_pool_id: int | None = Query(None, alias="after-call-pool-id"),
        max_segments: int | None = Query(None, alias="max-segments"),
        tail: bool = Query(False),
    ) -> PendingSampleUrls | Response:
        file = urllib.parse.unquote(log)
        await _validate_read(request, file)

        mapped = await _map_file(request, file)
        body = await build_pending_sample_urls(
            file=mapped,
            id=id,
            epoch=epoch,
            after_event_id=last_event_id,
            after_attachment_id=after_attachment_id,
            after_message_pool_id=after_message_pool_id,
            after_call_pool_id=after_call_pool_id,
            max_segments=max_segments,
            tail=tail,
        )
        if body is None:
            return Response(status_code=HTTP_404_NOT_FOUND)
        return body

    @app.get("/app-config", response_model=AppConfig)
    async def api_app_config() -> AppConfig:
        return get_app_config()

    scout_router = get_scout_search_router()
    if scout_router is not None:
        app.include_router(scout_router, prefix="/scout")

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
            if auth_header is None or not secrets.compare_digest(
                auth_header.encode(), authorization.encode()
            ):
                return Response("Unauthorized", status_code=401)
            return await call_next(request)

    return AuthorizationMiddleware


class AsyncFilesystemMiddleware:
    """Bind one shared AsyncFilesystem for the lifetime of each request.

    Pure-ASGI (not BaseHTTPMiddleware) so the ContextVar set here propagates to
    the route handler and into its `tg_collect` fan-out tasks — BaseHTTPMiddleware
    runs the endpoint in a separate task and would drop it. The single instance
    keeps one warm aioboto3 client + connection pool across all requests, so S3
    reads don't re-pay the credential/connection cold-start on every request.
    """

    def __init__(self, app: Any, fs: AsyncFilesystem) -> None:
        self.app = app
        self.fs = fs

    async def __call__(self, scope: Scope, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with bind_async_filesystem(self.fs):
            await self.app(scope, receive, send)


class _InspectStaticFiles(StaticFiles):
    """StaticFiles with no-cache headers to avoid stale assets."""

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["expires"] = "Fri, 01 Jan 1990 00:00:00 GMT"
        response.headers["pragma"] = "no-cache"
        response.headers["cache-control"] = (
            "no-cache, no-store, max-age=0, must-revalidate"
        )
        return response


class OnlyDirAccessPolicy(AccessPolicy):
    def __init__(self, dir: str) -> None:
        super().__init__()
        self.dir = dir

    def _validate_log_dir(self, file: str) -> bool:
        return file.startswith(self.dir) and ".." not in file

    async def can_read(self, request: Request, file: str) -> bool:
        return self._validate_log_dir(file)

    async def can_delete(self, request: Request, file: str) -> bool:
        return self._validate_log_dir(file)

    async def can_list(self, request: Request, dir: str) -> bool:
        return self._validate_log_dir(dir)

    async def can_write(self, request: Request, file: str) -> bool:
        return self._validate_log_dir(file)


def standalone_view_app(
    *,
    log_dir: str,
    network_policy: ViewerNetworkPolicy,
    recursive: bool = True,
    fs_options: dict[str, Any] = {},
    generate_direct_urls: bool = False,
    dist_dir: Path | None = None,
) -> ASGIApp:
    api = view_server_app(
        mapping_policy=None,
        access_policy=(
            OnlyDirAccessPolicy(log_dir)
            if network_policy.authorization is None
            else None
        ),
        default_dir=log_dir,
        recursive=recursive,
        fs_options=fs_options,
        generate_direct_urls=generate_direct_urls,
    )

    resolved_dist_dir = dist_dir or resolve_dist_directory()

    @api.get("/dist")
    async def api_dist() -> dict[str, str]:
        return {"path": resolved_dist_dir.as_posix()}

    app = FastAPI()
    app.mount("/api", BrowserOriginMiddleware(api, network_policy))
    app.mount(
        "/",
        _InspectStaticFiles(directory=resolved_dist_dir.as_posix(), html=True),
        name="static",
    )

    if network_policy.authorization:
        app.add_middleware(authorization_middleware(network_policy.authorization))

    protected_app: ASGIApp = HostValidationMiddleware(app, network_policy)
    return SecurityHeadersMiddleware(protected_app)


def view_server(
    log_dir: str,
    recursive: bool = True,
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_VIEW_PORT,
    authorization: str | None = None,
    fs_options: dict[str, Any] = {},
    generate_direct_urls: bool = False,
    trusted_origins: tuple[str, ...] = (),
    trusted_hosts: tuple[str, ...] = (),
    unsafe_allow_unauthenticated: bool = False,
    network_policy: ViewerNetworkPolicy | None = None,
) -> None:
    network_policy = network_policy or resolve_viewer_network_policy(
        bind_host=host,
        port=port,
        trusted_hosts=trusted_hosts,
        trusted_origins=trusted_origins,
        authorization=authorization,
        unsafe_allow_unauthenticated=unsafe_allow_unauthenticated,
    )

    # get filesystem and resolve log_dir to full path
    fs = filesystem(log_dir)
    if not fs.exists(log_dir):
        fs.mkdir(log_dir, True)
    log_dir = fs.info(log_dir).name

    app = standalone_view_app(
        log_dir=log_dir,
        network_policy=network_policy,
        recursive=recursive,
        fs_options=fs_options,
        generate_direct_urls=generate_direct_urls,
    )

    # one server-lifetime async filesystem (shared client + connection pool)
    # bound into every request by AsyncFilesystemMiddleware; client_ttl so the
    # long-running server picks up externally rotated static AWS credentials
    shared_fs = AsyncFilesystem(client_ttl=SHARED_FS_CLIENT_TTL_SECONDS)
    app = AsyncFilesystemMiddleware(app, fs=shared_fs)

    # filter request log (remove /api/events)
    filter_fastapi_log()

    # run app
    display().print(f"Inspect View: {log_dir}")
    warning = unsafe_network_warning(network_policy)
    if warning:
        logger.warning(warning)

    async def run_server() -> None:
        async def warm_shared_fs() -> None:
            # Warm the shared async S3 client (connection pool + credentials)
            # concurrently with server startup, so the first request doesn't
            # pay the cold-start but slow credential resolution doesn't delay
            # listening. Only relevant for S3; other backends don't use the
            # aioboto3 client.
            try:
                await shared_fs.exists(log_dir)
            except Exception:
                logger.warning("Failed to pre-warm shared S3 filesystem", exc_info=True)

        config = uvicorn.Config(
            app,
            host=network_policy.bind_host,
            port=network_policy.port,
            log_config=None,
            timeout_keep_alive=15,
        )
        server = uvicorn.Server(config)

        async def announce_when_ready() -> None:
            while not server.started:
                await anyio.sleep(0.05)

            # Only show machine IP when binding to 0.0.0.0 (accessible from all interfaces)
            machine_ip = network_policy.bind_host
            if network_policy.bind_host == "0.0.0.0":
                machine_ip = get_machine_ip() or "0.0.0.0"
            display().print(
                "======== Running on "
                f"http://{machine_ip}:{network_policy.port} ========\n"
                "(Press CTRL+C to quit)"
            )

        try:
            async with anyio.create_task_group() as tg:
                if fs.is_s3():
                    tg.start_soon(warm_shared_fs)
                tg.start_soon(announce_when_ready)
                await server.serve()
        finally:
            await shared_fs.close()

    anyio.run(run_server)
