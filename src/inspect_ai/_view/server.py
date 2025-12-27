import logging
import os
import urllib.parse
from io import BytesIO
from logging import LogRecord, getLogger
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    TypeVar,
)

from aiohttp import web
from pydantic_core import to_jsonable_python

from inspect_ai._display import display
from inspect_ai._eval.evalset import EvalSet, read_eval_set_info
from inspect_ai._util.azure import is_azure_auth_error, is_azure_path
from inspect_ai._util.constants import DEFAULT_SERVER_HOST, DEFAULT_VIEW_PORT
from inspect_ai._util.file import filesystem
from inspect_ai._view.azure import (
    azure_debug_exists,
    azure_runtime_hint,
)
from inspect_ai.log._file import (
    read_eval_log_headers_async,
)
from inspect_ai.log._recorders.buffer.buffer import sample_buffer

from .common import (
    async_connection,
    delete_log,
    get_log_bytes,
    get_log_dir,
    get_log_file,
    get_log_files,
    get_log_size,
    get_logs,
    normalize_uri,
    parse_log_token,
    stream_log_bytes,
)
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
    if is_azure_path(log_dir):
        try:
            azure_debug_exists(fs, log_dir, display().print)
            # Don't call fs.info(); keep original URI (fsspec paths acceptable downstream)
        except Exception as ex:  # provide actionable guidance for Azure failures
            raise RuntimeError(azure_runtime_hint(ex)) from ex
    else:
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
        size = await get_log_size(file)
        return web.json_response(size)

    @routes.get("/api/log-delete/{log}")
    async def api_log_delete(request: web.Request) -> web.Response:
        # log file requested
        file = normalize_uri(request.match_info["log"])
        validate_log_file_request(file)

        await delete_log(file)

        return web.json_response(True)

    @routes.get("/api/log-bytes/{log}")
    async def api_log_bytes(request: web.Request) -> web.Response:
        # log file requested
        file = normalize_uri(request.match_info["log"])
        validate_log_file_request(file)

        # header_only is based on a size threshold
        start_param = request.query.get("start", None)
        if start_param is None:
            return web.HTTPBadRequest(reason="No 'start' query param.")
        end_param = request.query.get("end", None)
        if end_param is None:
            return web.HTTPBadRequest(reason="No 'end' query param")
        start = int(start_param)
        end = int(end_param)
        headers = {
            "Content-Length": str(end - start + 1),
        }
        body = await get_log_bytes(file, start, end)
        return web.Response(
            body=body, headers=headers, content_type="application/octet-stream"
        )

    @routes.get("/api/log-download/{log}")
    async def api_log_download(request: web.Request) -> web.StreamResponse:
        # log file requested
        file = normalize_uri(request.match_info["log"])
        validate_log_file_request(file)

        # get file size and stream
        file_size = await get_log_size(file)
        stream = await stream_log_bytes(file)

        # determine filename
        base_name = Path(file).stem
        filename = f"{base_name}.eval"

        # set headers for download
        headers = {
            "Content-Length": str(file_size),
            "Content-Disposition": f'attachment; filename="{filename}"',
        }

        if isinstance(stream, BytesIO):
            # BytesIO case - return regular response
            return web.Response(
                body=stream.getvalue(),
                headers=headers,
                content_type="application/octet-stream",
            )
        else:
            # AsyncIterable case - create streaming response
            response = web.StreamResponse(headers=headers)
            response.content_type = "application/octet-stream"
            await response.prepare(request)

            async for chunk in stream:
                await response.write(chunk)

            await response.write_eof()
            return response

    @routes.get("/api/log-dir")
    async def api_log_dir(request: web.Request) -> web.Response:
        # log dir can optionally be overridden by the request
        if authorization:
            request_log_dir = request.query.getone("log_dir", None)
            if request_log_dir:
                request_log_dir = normalize_uri(request_log_dir)
            else:
                request_log_dir = log_dir
        else:
            request_log_dir = log_dir

        return web.json_response(get_log_dir(request_log_dir))

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

        listing = await get_logs(
            request_log_dir, recursive=recursive, fs_options=fs_options
        )
        if listing is None:
            return web.Response(status=404, reason="File not found")
        return web.json_response(listing)

    @routes.get("/api/log-files")
    async def api_log_files(request: web.Request) -> web.Response:
        # log dir can optionally be overridden by the request
        if authorization:
            request_log_dir = request.query.getone("log_dir", None)
            if request_log_dir:
                request_log_dir = normalize_uri(request_log_dir)
            else:
                request_log_dir = log_dir
        else:
            request_log_dir = log_dir

        # see if there is an etag
        client_etag = request.headers.get("If-None-Match")
        mtime = 0.0
        file_count = 0
        if client_etag is not None:
            mtime, file_count = parse_log_token(client_etag)

        log_files_response: dict[str, Any] = await get_log_files(
            request_log_dir,
            recursive=recursive,
            fs_options=fs_options,
            mtime=mtime,
            file_count=file_count,
        )
        return web.json_response(log_files_response)

    @routes.get("/api/eval-set")
    async def eval_set(request: web.Request) -> web.Response:
        # log dir can optionally be overridden by the request
        if authorization:
            request_log_dir = request.query.getone("log_dir", None)
            if request_log_dir:
                request_log_dir = normalize_uri(request_log_dir)
            else:
                request_log_dir = log_dir
        else:
            request_log_dir = log_dir

        request_dir = request.query.getone("dir", None)
        if request_dir:
            if request_log_dir:
                request_dir = request_log_dir + "/" + request_dir.lstrip("/")
            else:
                request_dir = request_dir.lstrip("/")
            validate_log_file_request(request_dir)
        else:
            request_dir = request_log_dir

        eval_set = read_eval_set_info(request_dir, fs_options=fs_options)
        return web.json_response(to_jsonable_python(eval_set, exclude_none=True))

    @routes.get("/api/flow")
    async def flow(request: web.Request) -> web.Response:
        # log dir can optionally be overridden by the request
        if authorization:
            request_log_dir = request.query.getone("log_dir", None)
            if request_log_dir:
                request_log_dir = normalize_uri(request_log_dir)
            else:
                request_log_dir = log_dir
        else:
            request_log_dir = log_dir

        request_dir = request.query.getone("dir", None)
        if request_dir:
            if request_log_dir:
                request_dir = request_log_dir + "/" + request_dir.lstrip("/")
            else:
                request_dir = request_dir.lstrip("/")
            validate_log_file_request(request_dir)
        else:
            request_dir = request_log_dir

        fs = filesystem(request_dir)
        flow_file = f"{request_dir}{fs.sep}flow.yaml"
        try:
            bytes = fs.read_bytes(flow_file)
        except FileNotFoundError:
            return web.Response(status=404, reason="Flow file not found")
        except Exception as ex:
            if is_azure_path(request_dir) and is_azure_auth_error(ex):
                return web.Response(status=404, reason="Flow file not found")
            raise

        return web.Response(
            text=bytes.decode("utf-8"), content_type="application/yaml", status=200
        )

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
        keepalive_timeout=15,
    )


def eval_set_response(eval_set: EvalSet | None) -> web.Response:
    if eval_set is None:
        return web.Response(status=404, reason="Eval set not found")
    else:
        response = dict(
            eval_set_id=eval_set.eval_set_id,
            tasks=[
                dict(
                    name=task.name,
                    task_id=task.task_id,
                    task_file=task.task_file,
                    task_args=task.task_args,
                    model=task.model,
                    model_roles=task.model_roles,
                    sequence=task.sequence,
                )
                for task in eval_set.tasks
            ],
        )
        return web.json_response(response)


async def log_file_response(file: str, header_only_param: str | None) -> web.Response:
    try:
        contents = await get_log_file(file, header_only_param)

        return web.Response(body=contents, content_type="application/json")

    except Exception as error:
        logger.exception(error)
        return web.Response(status=500, reason="File not found")


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
