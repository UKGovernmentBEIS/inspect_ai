import urllib.parse
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, Response

from inspect_ai._util.file import filesystem
from inspect_ai.log._recorders.buffer.buffer import sample_buffer

from .notify import view_last_eval_time
from .utils import (
    list_eval_logs_async,
    log_bytes_response,
    log_delete_response,
    log_file_response,
    log_headers_response,
    log_listing_response,
    log_size_response,
    normalize_uri,
)


def create_inspect_view_router(
    log_dir: str,
    recursive: bool = True,
    fs_options: dict[str, Any] = {},
    auth_callback: Optional[Callable[[Request], bool]] = None,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    fs = filesystem(log_dir)
    if not fs.exists(log_dir):
        fs.mkdir(log_dir, True)
    log_dir = fs.info(log_dir).name

    def validate_log_file_request(log_file: str) -> None:
        if not auth_callback and (not log_file.startswith(log_dir) or ".." in log_file):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    def check_auth(request: Request) -> None:
        if auth_callback and not auth_callback(request):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    @router.get("/logs/{log}")
    async def api_log(
        request: Request,
        log: str,
        header_only: Optional[str] = Query(None, alias="header-only"),
    ) -> Response:
        check_auth(request)
        file = normalize_uri(log)
        validate_log_file_request(file)
        return await log_file_response(file, header_only)

    @router.get("/log-size/{log}")
    async def api_log_size(request: Request, log: str) -> int:
        check_auth(request)
        file = normalize_uri(log)
        validate_log_file_request(file)
        return await log_size_response(file)

    @router.get("/log-delete/{log}")
    async def api_log_delete(request: Request, log: str) -> bool:
        check_auth(request)
        file = normalize_uri(log)
        validate_log_file_request(file)
        return await log_delete_response(file)

    @router.get("/log-bytes/{log}")
    async def api_log_bytes(
        request: Request, log: str, start: int = Query(...), end: int = Query(...)
    ) -> Response:
        check_auth(request)
        file = normalize_uri(log)
        validate_log_file_request(file)
        return await log_bytes_response(file, start, end)

    @router.get("/logs")
    async def api_logs(
        request: Request, log_dir_param: Optional[str] = Query(None, alias="log_dir")
    ) -> dict[str, Any]:
        check_auth(request)
        if auth_callback:
            request_log_dir = normalize_uri(log_dir_param) if log_dir_param else log_dir
        else:
            request_log_dir = log_dir

        logs = await list_eval_logs_async(
            log_dir=request_log_dir, recursive=recursive, fs_options=fs_options
        )
        return log_listing_response(logs, request_log_dir)

    @router.get("/log-headers")
    async def api_log_headers(
        request: Request, file: list[str] = Query(...)
    ) -> dict[str, Any]:
        check_auth(request)
        files = [normalize_uri(f) for f in file]
        for f in files:
            validate_log_file_request(f)
        return await log_headers_response(files)

    @router.get("/events")
    async def api_events(
        request: Request, last_eval_time: Optional[str] = None
    ) -> JSONResponse:
        check_auth(request)
        actions = (
            ["refresh-evals"]
            if last_eval_time and view_last_eval_time() > int(last_eval_time)
            else []
        )
        return JSONResponse(actions)

    @router.get("/pending-samples")
    async def api_pending_samples(request: Request, log: str) -> Response:
        check_auth(request)
        file = urllib.parse.unquote(log)
        validate_log_file_request(file)

        client_etag = request.headers.get("If-None-Match")

        buffer = sample_buffer(file)
        samples = buffer.get_samples(client_etag)
        if samples == "NotModified":
            return Response(status_code=304)
        elif samples is None:
            return Response(status_code=404)
        else:
            return Response(
                content=samples.model_dump_json(),
                media_type="application/json",
                headers={"ETag": samples.etag},
            )

    @router.get("/log-message")
    async def api_log_message(
        request: Request, log_file: str, message: str
    ) -> Response:
        check_auth(request)
        file = urllib.parse.unquote(log_file)
        validate_log_file_request(file)

        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"[CLIENT MESSAGE] ({file}): {message}")

        return Response(status_code=204)

    @router.get("/pending-sample-data")
    async def api_sample_events(
        request: Request,
        log: str,
        id: str,
        epoch: int,
        last_event_id: Optional[int] = Query(None, alias="last-event-id"),
        after_attachment_id: Optional[int] = Query(None, alias="after-attachment-id"),
    ) -> Response:
        check_auth(request)
        file = urllib.parse.unquote(log)
        validate_log_file_request(file)

        buffer = sample_buffer(file)
        sample_data = buffer.get_sample_data(
            id=id,
            epoch=epoch,
            after_event_id=last_event_id,
            after_attachment_id=after_attachment_id,
        )

        if sample_data is None:
            return Response(status_code=404)
        else:
            return Response(
                content=sample_data.model_dump_json(), media_type="application/json"
            )

    return router


inspect_view_router = create_inspect_view_router

__all__ = ["create_inspect_view_router", "inspect_view_router"]
