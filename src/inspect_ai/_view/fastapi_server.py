import json
import logging
import os
import secrets
import urllib.parse
from collections.abc import Callable
from functools import partial
from io import BytesIO
from logging import getLogger
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

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
from starlette.types import ASGIApp, Receive, Scope, Send
from typing_extensions import override

from inspect_ai._display.core.active import display
from inspect_ai._eval.evalset import EvalSet, read_eval_set_info
from inspect_ai._util._async import tg_collect
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
from .scope import (
    PERMISSIONS,
    PathScope,
    Permission,
    ScopeRoot,
    resolve_child,
)
from .scout_routes import get_scout_search_router
from .user_info import UserInfo, user_info

logger = getLogger(__name__)

VIEW_REQUEST_HEADER = "X-Inspect-View-Request"
VIEW_REQUEST_HEADER_VALUE = "true"

SHARED_FS_CLIENT_TTL_SECONDS = 15 * 60

LocationEncoding = Literal["path", "query"]
"""How a route's location arrives: percent-encoded in the path or in a query value."""


class AccessPolicy(Protocol):
    async def can_read(self, request: Request, file: str) -> bool: ...

    async def can_delete(self, request: Request, file: str) -> bool: ...

    async def can_list(self, request: Request, dir: str) -> bool: ...

    async def can_write(self, request: Request, file: str) -> bool: ...


class FileMappingPolicy(Protocol):
    async def map(self, request: Request, file: str) -> str: ...

    async def unmap(self, request: Request, file: str) -> str: ...


@runtime_checkable
class ResolvingAccessPolicy(Protocol):
    """An access policy that returns the location the server must use for I/O.

    Each method authorizes ``location`` for one operation and returns the
    string the route hands to the filesystem layer, or raises
    ``HTTPException(403)``. ``resolve_list`` receives ``None`` for an absent
    listing location and decides what that binds to. ``view_server_app`` uses
    a policy satisfying this protocol as is; a plain ``AccessPolicy`` is
    wrapped in ``CanonicalizingAdapter``. See
    ``design/viewer-scoped-authorization.md`` section 3.
    """

    async def resolve_read(self, request: Request, location: str) -> str: ...

    async def resolve_write(self, request: Request, location: str) -> str: ...

    async def resolve_delete(self, request: Request, location: str) -> str: ...

    async def resolve_list(self, request: Request, location: str | None) -> str: ...


class CanonicalizingAdapter:
    """Present a plain ``AccessPolicy`` (or ``None``) as a ``ResolvingAccessPolicy``.

    Despite the name, the adapter itself canonicalizes nothing: a plain policy
    may be keyed on a relative or bucket-relative spelling and a mapping
    policy owns the translation to storage, so the caller-supplied
    once-decoded string is what ``can_*`` receives and what is returned for
    I/O, exactly as the routes behaved before the resolver layer existed. An
    absent listing location binds to ``default_dir``. With ``policy=None``
    every location is permitted (``view_server_app(access_policy=None)``
    still means no checks).
    """

    def __init__(self, policy: AccessPolicy | None, default_dir: str) -> None:
        self._policy = policy
        self._default_dir = default_dir

    async def resolve_read(self, request: Request, location: str) -> str:
        if self._policy is not None and not await self._policy.can_read(
            request, location
        ):
            raise HTTPException(status_code=HTTP_403_FORBIDDEN)
        return location

    async def resolve_write(self, request: Request, location: str) -> str:
        if self._policy is not None and not await self._policy.can_write(
            request, location
        ):
            raise HTTPException(status_code=HTTP_403_FORBIDDEN)
        return location

    async def resolve_delete(self, request: Request, location: str) -> str:
        if self._policy is not None and not await self._policy.can_delete(
            request, location
        ):
            raise HTTPException(status_code=HTTP_403_FORBIDDEN)
        return location

    async def resolve_list(self, request: Request, location: str | None) -> str:
        if location is None:
            location = self._default_dir
        if self._policy is not None and not await self._policy.can_list(
            request, location
        ):
            raise HTTPException(status_code=HTTP_403_FORBIDDEN)
        return location


def _resolve_in_scope(
    scope: PathScope, location: str | None, permission: Permission
) -> str:
    """Resolve ``location`` (or the scope's default when absent) or raise 403."""
    resolved = (
        scope.default_location(permission)
        if location is None
        else scope.resolve(location, permission)
    )
    if resolved is None:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN)
    return resolved.io_path


class UnscopedResolvingPolicy:
    """Permit everything and return locations unchanged (the legacy credential path).

    Installed for requests that authenticate with the raw shared secret, so a
    client that predates scoped authorization sees exactly the behaviour of
    the policy-less token mode it was written against.
    """

    def __init__(self, default_dir: str) -> None:
        self._default_dir = default_dir

    async def resolve_read(self, request: Request, location: str) -> str:
        return location

    async def resolve_write(self, request: Request, location: str) -> str:
        return location

    async def resolve_delete(self, request: Request, location: str) -> str:
        return location

    async def resolve_list(self, request: Request, location: str | None) -> str:
        return self._default_dir if location is None else location


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


class ReleasingStreamingResponse(StreamingResponse):
    """StreamingResponse that releases a connection-owning body.

    Use instead of `StreamingResponse` when the content exposes `release()`,
    e.g. the aiobotocore `StreamingBody` from `stream_log_bytes`.
    """

    @override
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Nothing else releases the body: starlette never closes a body
        # iterator, and a `send` failure on `http.response.start` leaves it
        # unstarted, so an iterator's own `finally` won't run either. An
        # abandoned S3 body holds its pool slot until every S3 read wedges.
        # release() is idempotent, so releasing a finished body is free.
        release: Callable[[], object] | None = getattr(
            self.body_iterator, "release", None
        )
        try:
            await super().__call__(scope, receive, send)
        finally:
            if release is not None:
                try:
                    release()
                except Exception:
                    # Don't mask whatever ended the request.
                    logger.warning("Failed to release response body", exc_info=True)


def view_server_app(
    mapping_policy: FileMappingPolicy | None = None,
    access_policy: AccessPolicy | ResolvingAccessPolicy | None = None,
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

    resolver: ResolvingAccessPolicy
    unchecked_child_base: str | None
    if isinstance(access_policy, ResolvingAccessPolicy):
        resolver = access_policy
        unchecked_child_base = None
    else:
        resolver = CanonicalizingAdapter(access_policy, default_dir)
        unchecked_child_base = default_dir

    def _decode_location(location: str, encoding: LocationEncoding | None) -> str:
        """Percent-decode a request location exactly once.

        This is the only place a route's location is decoded (the decode-once
        rule of design section 3, enforced by a static test): path-segment
        routes and ``/log-headers`` decode through ``normalize_uri``, the
        query-string sample routes through ``unquote``; ``None`` means the
        value is already the once-decoded spelling.
        """
        if encoding == "path":
            return normalize_uri(location)
        if encoding == "query":
            return urllib.parse.unquote(location)
        return location

    def _io_location(caller: str, resolved: str) -> str:
        # A mapping policy owns the translation to storage and is given the
        # caller's (now authorized) spelling, as before the resolver layer;
        # otherwise the resolver's canonical location is used for I/O.
        return caller if mapping_policy is not None else resolved

    async def _resolve_read(
        request: Request, location: str, encoding: LocationEncoding | None = "path"
    ) -> str:
        decoded = _decode_location(location, encoding)
        return _io_location(decoded, await resolver.resolve_read(request, decoded))

    async def _resolve_write(
        request: Request, location: str, encoding: LocationEncoding | None = "path"
    ) -> str:
        decoded = _decode_location(location, encoding)
        return _io_location(decoded, await resolver.resolve_write(request, decoded))

    async def _resolve_delete(
        request: Request, location: str, encoding: LocationEncoding | None = "path"
    ) -> str:
        decoded = _decode_location(location, encoding)
        return _io_location(decoded, await resolver.resolve_delete(request, decoded))

    async def _resolve_list(request: Request, location: str | None) -> str:
        resolved = await resolver.resolve_list(request, location)
        return resolved if location is None else _io_location(location, resolved)

    async def _resolve_list_child(
        request: Request, log_dir: str | None, sub_dir: str | None
    ) -> str:
        """Resolve the directory named by ``/eval-set`` and ``/flow``.

        With a child, the base is the caller's ``log_dir``; when absent it is
        the server default for a plain policy (unchecked, as before: the
        joined string is what gets checked) or the scope's default binding for
        a resolving policy. The child is joined by ``resolve_child`` (400 if it
        escapes) and the result resolved for listing.
        """
        if not sub_dir:
            return await _resolve_list(request, log_dir or None)
        if log_dir:
            base = log_dir
        elif unchecked_child_base is not None:
            base = unchecked_child_base
        else:
            base = await resolver.resolve_list(request, None)
        try:
            joined = resolve_child(base, sub_dir)
        except ValueError as ex:
            raise HTTPException(status_code=400, detail=str(ex))
        return await _resolve_list(request, joined)

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
        file = await _resolve_read(request, log)
        body, etag = await get_log_file(await _map_file(request, file), header_only)
        headers = {"ETag": etag} if etag is not None else {}
        return Response(content=body, media_type="application/json", headers=headers)

    @app.get("/log-size/{log:path}")
    async def api_log_size(request: Request, log: str) -> int:
        file = await _resolve_read(request, log)
        return await get_log_size(await _map_file(request, file))

    @app.get("/log-info/{log:path}", response_model_exclude_none=True)
    async def api_log_info(request: Request, log: str) -> LogInfo:
        file = await _resolve_read(request, log)
        return await get_log_info(
            await _map_file(request, file),
            generate_direct_url=generate_direct_urls,
        )

    @app.delete("/log-delete/{log:path}")
    async def api_log_delete(request: Request, log: str) -> bool:
        _validate_mutating_request(request)
        file = await _resolve_delete(request, log)
        await delete_log(await _map_file(request, file))
        return True

    @app.post("/log-edit/{log:path}", response_model=EvalLog)
    async def api_log_edit(request: Request, log: str, update: LogUpdate) -> Response:
        _validate_mutating_request(request)
        file = await _resolve_write(request, log)
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
        file = await _resolve_read(request, log)
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
            return ReleasingStreamingResponse(
                content=response,
                media_type="application/octet-stream",
            )

    @app.get("/log-download/{log:path}")
    async def api_log_download(
        request: Request,
        log: str,
    ) -> Response:
        file = await _resolve_read(request, log)

        mapped_file = await _map_file(request, file)

        base_name = Path(file).stem
        filename = f"{base_name}.eval"

        # Percent-encode names starlette can't encode as latin-1 (it encodes
        # every header that way, so a CJK or emoji log name would raise in the
        # response constructor). RFC 6266 form, as starlette's FileResponse.
        quoted = urllib.parse.quote(filename)
        disposition = (
            f'attachment; filename="{filename}"'
            if quoted == filename
            else f"attachment; filename*=utf-8''{quoted}"
        )
        headers = {"Content-Disposition": disposition}

        # Acquire the body last: anything raising before the return strands
        # it, since only __call__ can release it.
        file_size = await get_log_size(mapped_file)
        stream = await stream_log_bytes(mapped_file, log_file_size=file_size)

        # No explicit Content-Length: the file may change between
        # get_log_size() and the read (in-progress evals are rewritten
        # in place), and a stale size makes clients fail the download.
        # The buffered branch lets the framework set it from the actual
        # body; the streaming branch uses chunked transfer encoding
        # (same rationale as /log-bytes above).
        if isinstance(stream, BytesIO):
            return Response(
                content=stream.getvalue(),
                headers=headers,
                media_type="application/octet-stream",
            )
        else:
            return ReleasingStreamingResponse(
                content=stream,
                headers=headers,
                media_type="application/octet-stream",
            )

    @app.get("/log-dir")
    async def api_log_dir(
        request: Request,
        log_dir: str | None = Query(None, alias="log_dir"),
    ) -> LogDirResponse:
        log_dir = await _resolve_list(request, log_dir)
        return get_log_dir(log_dir)

    @app.get("/log-files", response_class=InspectJsonResponse)
    async def api_log_files(
        request: Request,
        log_dir: str | None = Query(None, alias="log_dir"),
    ) -> LogFilesResponse:
        log_dir = await _resolve_list(request, log_dir)

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
        log_dir = await _resolve_list(request, log_dir)
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
        eval_set_dir = await _resolve_list_child(request, log_dir, sub_dir)

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
        flow_dir = await _resolve_list_child(request, log_dir, sub_dir)

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
        async def _resolve_and_map(f: str) -> str:
            return await _map_file(request, await _resolve_read(request, f))

        mapped_files = await tg_collect([partial(_resolve_and_map, f) for f in file])

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
        request: Request, log: str = Query(...)
    ) -> Samples | Response:
        file = await _resolve_read(request, log, encoding="query")

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
            return InspectJsonResponse(
                content=samples.model_dump(mode="json", by_alias=True),
                headers={"ETag": samples.etag},
            )

    @app.post("/log-message")
    async def api_log_message(
        request: Request, log_file: str, message: str
    ) -> Response:
        _validate_mutating_request(request)
        file = await _resolve_read(request, log_file, encoding="query")

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
        file = await _resolve_read(request, log, encoding="query")

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
        file = await _resolve_read(request, log, encoding="query")

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
    keeps one warm aiobotocore client + connection pool across all requests, so S3
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
    """Confine every request to one directory (standalone ``inspect view`` without a token).

    Containment is judged by ``scope.py``'s canonicalizer, so symlink and
    prefix-sibling escapes are refused and the location returned by the
    ``resolve_*`` methods is canonical. The ``can_*`` methods remain for
    callers that consult the policy directly and answer on the same rule.
    """

    def __init__(self, dir: str) -> None:
        super().__init__()
        self.dir = dir
        self._scope = PathScope((ScopeRoot.parse(dir, "dir", sorted(PERMISSIONS)),))

    async def can_read(self, request: Request, file: str) -> bool:
        return self._scope.resolve(file, "read") is not None

    async def can_delete(self, request: Request, file: str) -> bool:
        return self._scope.resolve(file, "delete") is not None

    async def can_list(self, request: Request, dir: str) -> bool:
        return self._scope.resolve(dir, "list") is not None

    async def can_write(self, request: Request, file: str) -> bool:
        return self._scope.resolve(file, "write") is not None

    async def resolve_read(self, request: Request, location: str) -> str:
        return _resolve_in_scope(self._scope, location, "read")

    async def resolve_write(self, request: Request, location: str) -> str:
        return _resolve_in_scope(self._scope, location, "write")

    async def resolve_delete(self, request: Request, location: str) -> str:
        return _resolve_in_scope(self._scope, location, "delete")

    async def resolve_list(self, request: Request, location: str | None) -> str:
        return _resolve_in_scope(self._scope, location, "list")


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
            else UnscopedResolvingPolicy(log_dir)
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
            # aiobotocore client.
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
