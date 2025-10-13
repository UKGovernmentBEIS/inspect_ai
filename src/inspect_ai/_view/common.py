import asyncio
import contextlib
import os
import urllib.parse
from logging import getLogger
from typing import Any, AsyncIterator, Literal, Tuple, cast

import fsspec  # type: ignore
from fsspec.asyn import AsyncFileSystem  # type: ignore
from fsspec.core import split_protocol  # type: ignore
from s3fs import S3FileSystem  # type: ignore

from inspect_ai._util.file import default_fs_options, dirname, filesystem, size_in_mb
from inspect_ai.log._file import (
    EvalLogInfo,
    eval_log_json,
    is_log_file,
    list_eval_logs,
    log_file_info,
    log_files_from_ls,
    read_eval_log_async,
)

logger = getLogger(__name__)


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


def get_log_dir(log_dir: str) -> dict[str, Any]:
    response = dict(
        log_dir=aliased_path(log_dir),
    )
    return response


async def get_log_files(
    request_log_dir: str,
    recursive: bool,
    fs_options: dict[str, Any],
    mtime: float,
    file_count: int,
) -> dict[str, Any]:
    # list logs
    logs = await list_eval_logs_async(
        log_dir=request_log_dir, recursive=recursive, fs_options=fs_options
    )

    if len(logs) != file_count:
        # have the number of files changed? could be a delete
        # so send a complete list
        return log_files_response(logs, response_type="full")
    else:
        # send only the changed files (captures edits)
        logs = [log for log in logs if (log.mtime is None or log.mtime > mtime)]
        return log_files_response(logs, response_type="incremental")


def parse_log_token(log_token: str) -> Tuple[float, int]:
    # validate basic format
    if log_token.find("-") == -1:
        raise RuntimeError(f"Invalid log token: {log_token}")

    # strip weak etag markers if present
    if log_token.startswith('W/"') and log_token.endswith('"'):
        log_token = log_token[3:-1]

    parts = log_token.split("-", 1)
    return float(parts[0]), int(parts[1])


def log_files_response(
    logs: list[EvalLogInfo], response_type: Literal["incremental", "full"]
) -> dict[str, Any]:
    response = dict(
        response_type=response_type,
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


async def get_log_file(file: str, header_only_param: str | None) -> bytes:
    # resolve header_only
    header_only_mb = int(header_only_param) if header_only_param is not None else None
    header_only = resolve_header_only(file, header_only_mb)

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

    return contents


async def get_log_size(log_file: str) -> int:
    fs = filesystem(log_file)
    if fs.is_async():
        info = fs._file_info(await async_connection(log_file)._info(log_file))
    else:
        info = fs.info(log_file)
    return info.size


async def delete_log(log_file: str) -> None:
    fs = filesystem(log_file)
    fs.rm(log_file)


async def get_log_bytes(log_file: str, start: int, end: int) -> bytes:
    # fetch bytes
    fs = filesystem(log_file)
    if fs.is_async():
        res: bytes = await async_connection(log_file)._cat_file(
            log_file, start=start, end=end + 1
        )
    else:
        res = fs.read_bytes(log_file, start, end + 1)

    return res


async def get_logs(
    request_log_dir: str, recursive: bool, fs_options: dict[str, Any]
) -> dict[str, Any] | None:
    # if the log_dir contains the path to a specific file
    # then just return that file
    if is_log_file(request_log_dir, [".json"]):
        file_info = await eval_log_info_async(request_log_dir)
        if file_info is not None:
            return get_log_listing(logs=[file_info], log_dir=dirname(request_log_dir))
        else:
            return None

    # list logs
    logs = await list_eval_logs_async(
        log_dir=request_log_dir, recursive=recursive, fs_options=fs_options
    )
    return get_log_listing(logs, request_log_dir)


def get_log_listing(logs: list[EvalLogInfo], log_dir: str) -> dict[str, Any]:
    listing = dict(
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
    return listing


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
async def async_filesystem(
    location: str, fs_options: dict[str, Any] = {}
) -> AsyncIterator[AsyncFileSystem]:
    # determine protocol
    protocol, _ = split_protocol(location)
    protocol = protocol or "file"

    # build options
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
        async with async_filesystem(log_dir, fs_options=fs_options) as async_fs:
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


def resolve_header_only(path: str, header_only: int | None) -> bool:
    # if there is a max_size passed, respect that and switch to
    # header_only mode if the file is too large
    if header_only == 0:
        return True
    if header_only is not None and size_in_mb(path) > int(header_only):
        return True
    else:
        return False


async def eval_log_info_async(
    log_file: str,
    fs_options: dict[str, Any] = {},
) -> EvalLogInfo | None:
    """Get EvalLogInfo for a specific log file asynchronously.

    Args:
        log_file (str): The complete path to the log file
        fs_options (dict[str, Any]): Optional. Additional arguments to pass through

    Returns:
        EvalLogInfo or None: The EvalLogInfo object if the file exists and is valid, otherwise None.
    """
    fs = filesystem(log_file, fs_options)
    if fs.exists(log_file):
        info = fs.info(log_file)
        return log_file_info(info)
    else:
        return None


def aliased_path(path: str) -> str:
    home_dir = os.path.expanduser("~")
    if path.startswith(home_dir):
        return path.replace(home_dir, "~", 1)
    else:
        return path
