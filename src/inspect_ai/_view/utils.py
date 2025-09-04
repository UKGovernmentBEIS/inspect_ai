import asyncio
import contextlib
import os
import urllib.parse
from logging import getLogger
from typing import Any, AsyncIterator, Literal, cast

import fsspec  # type: ignore
from fastapi.responses import Response
from fsspec.asyn import AsyncFileSystem  # type: ignore
from fsspec.core import split_protocol  # type: ignore
from pydantic_core import to_jsonable_python
from s3fs import S3FileSystem  # type: ignore

from inspect_ai._util.file import default_fs_options, filesystem, size_in_mb
from inspect_ai.log._file import (
    EvalLogInfo,
    eval_log_json,
    list_eval_logs,
    log_files_from_ls,
    read_eval_log_async,
    read_eval_log_headers_async,
)

logger = getLogger(__name__)


def normalize_uri(uri: str) -> str:
    """Normalize incoming URIs to a consistent format."""
    parsed = urllib.parse.urlparse(urllib.parse.unquote(uri))

    if parsed.scheme != "file":
        return urllib.parse.unquote(uri)
    else:
        path = parsed.path
        if path.startswith("/") and len(path) > 3 and path[2] == ":":
            path = path[1:]
        return f"file://{path}"


def log_listing_response(logs: list[EvalLogInfo], log_dir: str) -> dict[str, Any]:
    response: dict[str, Any] = dict(
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
    return response


async def log_file_response(file: str, header_only_param: str | None) -> Response:
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

        if contents is None:
            log = await read_eval_log_async(file, header_only=False)
            contents = eval_log_json(log)

        return Response(content=contents, media_type="application/json")

    except Exception as error:
        logger.exception(error)
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail="File not found")


async def log_size_response(log_file: str) -> int:
    fs = filesystem(log_file)
    if fs.is_async():
        info = fs._file_info(await async_connection(log_file)._info(log_file))
    else:
        info = fs.info(log_file)
    return info.size


async def log_delete_response(log_file: str) -> bool:
    fs = filesystem(log_file)
    fs.rm(log_file)
    return True


async def log_bytes_response(log_file: str, start: int, end: int) -> Response:
    content_length = end - start + 1
    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Length": str(content_length),
    }

    fs = filesystem(log_file)
    if fs.is_async():
        bytes_content = await async_connection(log_file)._cat_file(
            log_file, start=start, end=end + 1
        )
    else:
        bytes_content = fs.read_bytes(log_file, start, end + 1)

    return Response(content=bytes_content, headers=headers)


async def log_headers_response(files: list[str]) -> dict[str, Any]:
    headers = await read_eval_log_headers_async(files)
    return to_jsonable_python(headers, exclude_none=True)  # type: ignore[no-any-return]


def aliased_path(path: str) -> str:
    home_dir = os.path.expanduser("~")
    if path.startswith(home_dir):
        return path.replace(home_dir, "~", 1)
    else:
        return path


def resolve_header_only(path: str, header_only: int | None) -> bool:
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
    fs = filesystem(log_dir, fs_options)
    if fs.is_async():
        async with async_fileystem(log_dir, fs_options=fs_options) as async_fs:
            if await async_fs._exists(log_dir):
                async_fs.invalidate_cache(log_dir)
                if recursive:
                    files: list[dict[str, Any]] = []
                    async for path, dirs, filenames in async_fs._walk(
                        log_dir, detail=True
                    ):
                        if isinstance(filenames, dict):
                            files.extend(filenames.values())
                        else:
                            files.extend(filenames)
                else:
                    files = cast(
                        list[dict[str, Any]],
                        await async_fs._ls(log_dir, detail=True),
                    )
                logs = [fs._file_info(file) for file in files]
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


_async_connections: dict[str, AsyncFileSystem] = {}


def async_connection(log_file: str) -> AsyncFileSystem:
    protocol, _ = split_protocol(log_file)
    protocol = protocol or "file"

    if protocol not in _async_connections.keys():
        _async_connections[protocol] = fsspec.filesystem(
            protocol, asynchronous=True, loop=asyncio.get_event_loop()
        )

    return _async_connections[protocol]


@contextlib.asynccontextmanager
async def async_fileystem(
    location: str, fs_options: dict[str, Any] = {}
) -> AsyncIterator[AsyncFileSystem]:
    protocol, _ = split_protocol(location)
    protocol = protocol or "file"

    options = default_fs_options(location)
    options.update(fs_options)

    if protocol == "s3":
        options["skip_instance_cache"] = True
        s3 = S3FileSystem(asynchronous=True, **options)
        session = await s3.set_session()
        try:
            yield s3
        finally:
            await session.close()
    else:
        options.update({"asynchronous": True, "loop": asyncio.get_event_loop()})
        yield fsspec.filesystem(protocol, **options)
