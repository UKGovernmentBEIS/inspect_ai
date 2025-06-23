import asyncio
import contextlib
import logging
import os
import urllib.parse
from logging import LogRecord, getLogger
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Literal, TypeVar, cast

import fsspec  # type: ignore
from aiohttp import web
from fsspec.asyn import AsyncFileSystem  # type: ignore
from fsspec.core import split_protocol  # type: ignore
from pydantic_core import to_jsonable_python
from s3fs import S3FileSystem  # type: ignore

from inspect_ai._display import display
from inspect_ai._util.constants import DEFAULT_SERVER_HOST, DEFAULT_VIEW_PORT
from inspect_ai._util.file import default_fs_options, filesystem, size_in_mb
from inspect_ai.log._file import (
    EvalLogInfo,
    eval_log_json,
    list_eval_logs,
    log_files_from_ls,
    read_eval_log_async,
    read_eval_log_headers_async,
)
from inspect_ai.log._recorders.buffer.buffer import sample_buffer

from .notify import view_last_eval_time

logger = getLogger(__name__)


def view_server(
    log_dir: str,
    recursive: bool = True,
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_VIEW_PORT,
    authorization: str | None = None,
    fs_options: dict[str, Any] = {},
) -> None:
    # route table
    routes = web.RouteTableDef()

    # get filesystem and resolve log_dir to full path
    fs = filesystem(log_dir)
    if not fs.exists(log_dir):
        fs.mkdir(log_dir, True)
    log_dir = fs.info(log_dir).name

    # validate log file requests (must be in the log_dir
    # unless authorization has been provided)
    def validate_log_file_request(log_file: str) -> None:
        if not authorization and (not log_file.startswith(log_dir) or ".." in log_file):
            raise web.HTTPUnauthorized()

    @routes.get("/api/logs/{log}")
    async def api_log(request: web.Request) -> web.Response:
        # log file requested
        file = normalize_uri(request.match_info["log"])
        validate_log_file_request(file)

        # header_only is based on a size threshold
        header_only = request.query.get("header-only", None)
        return await log_file_response(file, header_only)

    @routes.get("/api/log-size/{log}")
    async def api_log_size(request: web.Request) -> web.Response:
        # log file requested
        file = normalize_uri(request.match_info["log"])
        validate_log_file_request(file)

        return await log_size_response(file)

    @routes.get("/api/log-delete/{log}")
    async def api_log_delete(request: web.Request) -> web.Response:
        # log file requested
        file = normalize_uri(request.match_info["log"])
        validate_log_file_request(file)

        return await log_delete_response(file)

    @routes.get("/api/log-bytes/{log}")
    async def api_log_bytes(request: web.Request) -> web.Response:
        # log file requested
        file = normalize_uri(request.match_info["log"])
        validate_log_file_request(file)

        # header_only is based on a size threshold
        start = request.query.get("start", None)
        if start is None:
            return web.HTTPBadRequest(reason="No 'start' query param.")
        end = request.query.get("end", None)
        if end is None:
            return web.HTTPBadRequest(reason="No 'end' query param")

        return await log_bytes_response(file, int(start), int(end))

    @routes.get("/api/logs")
    async def api_logs(request: web.Request) -> web.Response:
        # log dir can optionally be overridden by the request
        if authorization:
            request_log_dir = request.query.getone("log_dir", None)
            if request_log_dir:
                request_log_dir = normalize_uri(request_log_dir)
            else:
                request_log_dir = log_dir
        else:
            request_log_dir = log_dir

        # list logs
        logs = await list_eval_logs_async(
            log_dir=request_log_dir, recursive=recursive, fs_options=fs_options
        )
        return log_listing_response(logs, request_log_dir)

    @routes.get("/api/log-headers")
    async def api_log_headers(request: web.Request) -> web.Response:
        files = request.query.getall("file", [])
        files = [normalize_uri(file) for file in files]
        map(validate_log_file_request, files)
        return await log_headers_response(files)

    @routes.get("/api/events")
    async def api_events(request: web.Request) -> web.Response:
        last_eval_time = request.query.get("last_eval_time", None)
        actions = (
            ["refresh-evals"]
            if last_eval_time and view_last_eval_time() > int(last_eval_time)
            else []
        )
        return web.json_response(actions)

    @routes.get("/api/pending-samples")
    async def api_pending_samples(request: web.Request) -> web.Response:
        # log file requested
        file = query_param_required("log", request, str)

        file = urllib.parse.unquote(file)
        validate_log_file_request(file)

        # see if there is an etag
        client_etag = request.headers.get("If-None-Match")

        # get samples and respond
        buffer = sample_buffer(file)
        samples = buffer.get_samples(client_etag)
        if samples == "NotModified":
            return web.Response(status=304)
        elif samples is None:
            return web.Response(status=404)
        else:
            return web.Response(
                body=samples.model_dump_json(), headers={"ETag": samples.etag}
            )

    @routes.get("/api/log-message")
    async def api_log_message(request: web.Request) -> web.Response:
        # log file requested
        file = query_param_required("log_file", request, str)

        file = urllib.parse.unquote(file)
        validate_log_file_request(file)

        # message to log
        message = query_param_required("message", request, str)

        # log the message
        logger.warning(f"[CLIENT MESSAGE] ({file}): {message}")

        # respond
        return web.Response(status=204)

    @routes.get("/api/pending-sample-data")
    async def api_sample_events(request: web.Request) -> web.Response:
        # log file requested
        file = query_param_required("log", request, str)

        file = urllib.parse.unquote(file)
        validate_log_file_request(file)

        # sample id information
        id = query_param_required("id", request, str)
        epoch = query_param_required("epoch", request, int)

        # get sync info
        after_event_id = query_param_optional("last-event-id", request, int)
        after_attachment_id = query_param_optional("after-attachment-id", request, int)

        # get samples and responsd
        buffer = sample_buffer(file)
        sample_data = buffer.get_sample_data(
            id=id,
            epoch=epoch,
            after_event_id=after_event_id,
            after_attachment_id=after_attachment_id,
        )

        # respond
        if sample_data is None:
            return web.Response(status=404)
        else:
            return web.Response(body=sample_data.model_dump_json())

    # optional auth middleware
    @web.middleware
    async def authorize(
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        if request.headers.get("Authorization", None) != authorization:
            return web.HTTPUnauthorized()
        else:
            return await handler(request)

    # setup server
    app = web.Application(middlewares=[authorize] if authorization else [])
    app.router.add_routes(routes)
    app.router.register_resource(WWWResource())

    # filter request log (remove /api/events)
    filter_aiohttp_log()

    # run app
    display().print(f"Inspect View: {log_dir}")
    web.run_app(
        app=app,
        host=host,
        port=port,
        print=display().print,
        access_log_format='%a %t "%r" %s %b (%Tf)',
        shutdown_timeout=1,
    )


def normalize_uri(uri: str) -> str:
    """Normalize incoming URIs to a consistent format."""
    # Decode any URL-encoded characters
    parsed = urllib.parse.urlparse(urllib.parse.unquote(uri))

    if parsed.scheme != "file":
        # If this isn't a file uri, just unquote it
        return urllib.parse.unquote(uri)

    else:
        # If this is a file uri, see whether we should process triple slashes
        # down to double slashes
        path = parsed.path

        # Detect and normalize Windows-style file URIs
        if path.startswith("/") and len(path) > 3 and path[2] == ":":
            # Strip leading `/` before drive letter
            path = path[1:]

        return f"file://{path}"


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


async def log_file_response(file: str, header_only_param: str | None) -> web.Response:
    # resolve header_only
    header_only_mb = int(header_only_param) if header_only_param is not None else None
    header_only = resolve_header_only(file, header_only_mb)

    try:
        contents: bytes | None = None
        if header_only:
            try:
                log = await read_eval_log_async(file, header_only=True)
                contents = eval_log_json(log)
            except ValueError as ex:
                logger.info(
                    f"Unable to read headers from log file {file}: {ex}. "
                    + "The file may include a NaN or Inf value. Falling back to reading entire file."
                )

        if contents is None:  # normal read
            log = await read_eval_log_async(file, header_only=False)
            contents = eval_log_json(log)

        return web.Response(body=contents, content_type="application/json")

    except Exception as error:
        logger.exception(error)
        return web.Response(status=500, reason="File not found")


async def log_size_response(log_file: str) -> web.Response:
    fs = filesystem(log_file)
    if fs.is_async():
        info = fs._file_info(await async_connection(log_file)._info(log_file))
    else:
        info = fs.info(log_file)
    return web.json_response(info.size)


async def log_delete_response(log_file: str) -> web.Response:
    fs = filesystem(log_file)
    fs.rm(log_file)
    return web.json_response(True)


async def log_bytes_response(log_file: str, start: int, end: int) -> web.Response:
    # build headers
    content_length = end - start + 1
    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Length": str(content_length),
    }

    # fetch bytes
    fs = filesystem(log_file)
    if fs.is_async():
        bytes = await async_connection(log_file)._cat_file(
            log_file, start=start, end=end + 1
        )
    else:
        bytes = fs.read_bytes(log_file, start, end + 1)

    # return response
    return web.Response(status=200, body=bytes, headers=headers)


async def log_headers_response(files: list[str]) -> web.Response:
    headers = await read_eval_log_headers_async(files)
    return web.json_response(to_jsonable_python(headers, exclude_none=True))


class WWWResource(web.StaticResource):
    def __init__(self) -> None:
        super().__init__(
            "", os.path.abspath((Path(__file__).parent / "www" / "dist").as_posix())
        )

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


async def list_eval_logs_async(
    log_dir: str = os.environ.get("INSPECT_LOG_DIR", "./logs"),
    formats: list[Literal["eval", "json"]] | None = None,
    recursive: bool = True,
    descending: bool = True,
    fs_options: dict[str, Any] = {},
) -> list[EvalLogInfo]:
    """List all eval logs in a directory.

    Will be async for filesystem providers that support async (e.g. s3, gcs, etc.)
    otherwise will fallback to sync implementation.

    Args:
      log_dir (str): Log directory (defaults to INSPECT_LOG_DIR)
      formats (Literal["eval", "json"]): Formats to list (default
        to listing all formats)
      recursive (bool): List log files recursively (defaults to True).
      descending (bool): List in descending order.
      fs_options (dict[str, Any]): Optional. Additional arguments to pass through
          to the filesystem provider (e.g. `S3FileSystem`).

    Returns:
       List of EvalLog Info.
    """
    # async filesystem if we can
    fs = filesystem(log_dir, fs_options)
    if fs.is_async():
        async with async_fileystem(log_dir, fs_options=fs_options) as async_fs:
            if await async_fs._exists(log_dir):
                # prevent caching of listings
                async_fs.invalidate_cache(log_dir)
                # list logs
                if recursive:
                    files: list[dict[str, Any]] = []
                    async for _, _, filenames in async_fs._walk(log_dir, detail=True):
                        files.extend(filenames.values())
                else:
                    files = cast(
                        list[dict[str, Any]],
                        await async_fs._ls(log_dir, detail=True),
                    )
                logs = [fs._file_info(file) for file in files]
                # resolve to eval logs
                return log_files_from_ls(logs, formats, descending)
            else:
                return []
    else:
        return list_eval_logs(
            log_dir=log_dir,
            formats=formats,
            recursive=recursive,
            descending=descending,
            fs_options=fs_options,
        )


def filter_aiohttp_log() -> None:
    #  filter overly chatty /api/events messages
    class RequestFilter(logging.Filter):
        def filter(self, record: LogRecord) -> bool:
            return "/api/events" not in record.getMessage()

    # don't add if we already have
    access_logger = getLogger("aiohttp.access")
    for existing_filter in access_logger.filters:
        if isinstance(existing_filter, RequestFilter):
            return

    # add the filter
    access_logger.addFilter(RequestFilter())


_async_connections: dict[str, AsyncFileSystem] = {}


def async_connection(log_file: str) -> AsyncFileSystem:
    # determine protocol
    protocol, _ = split_protocol(log_file)
    protocol = protocol or "file"

    # create connection if required
    if protocol not in _async_connections.keys():
        _async_connections[protocol] = fsspec.filesystem(
            protocol, asynchronous=True, loop=asyncio.get_event_loop()
        )

    # return async file-system
    return _async_connections.get(protocol)


@contextlib.asynccontextmanager
async def async_fileystem(
    location: str, fs_options: dict[str, Any] = {}
) -> AsyncIterator[AsyncFileSystem]:
    # determine protocol
    protocol, _ = split_protocol(location)
    protocol = protocol or "file"

    # build options
    options = default_fs_options(location)
    options.update(fs_options)

    if protocol == "s3":
        s3 = S3FileSystem(asynchronous=True, **options)
        session = await s3.set_session()
        try:
            yield s3
        finally:
            await session.close()
    else:
        options.update({"asynchronous": True, "loop": asyncio.get_event_loop()})
        yield fsspec.filesystem(protocol, **options)


T = TypeVar("T")  # Define type variable


def query_param_required(
    key: str, request: web.Request, converter: Callable[[str], T]
) -> T:
    """
    Generic parameter validation function.

    Args:
        key: Parameter key to look up
        request: aiohttp Request object
        converter: Function to convert the string parameter to type T

    Returns:
        Converted parameter value of type T

    Raises:
        HTTPBadRequest: If parameter is missing or invalid
    """
    value = request.query.get(key)
    if value is None:
        raise web.HTTPBadRequest(text=f"Missing parameter {key}")

    try:
        return converter(value)
    except ValueError:
        raise web.HTTPBadRequest(text=f"Invalid value {value} for {key}")


def query_param_optional(
    key: str, request: web.Request, converter: Callable[[str], T]
) -> T | None:
    """
    Generic parameter validation function.

    Args:
        key: Parameter key to look up
        request: aiohttp Request object
        converter: Function to convert the string parameter to type T

    Returns:
        Converted parameter value of type T

    Raises:
        HTTPBadRequest: If parameter is missing or invalid
    """
    value = request.query.get(key)
    if value is None:
        return None

    try:
        return converter(value)
    except ValueError:
        raise web.HTTPBadRequest(text=f"Invalid value {value} for {key}")
