import asyncio
import contextlib
import datetime
import io
import os
import re
import string
import unicodedata
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, AsyncIterator, BinaryIO, Iterator, Literal, cast, overload
from urllib.parse import urlparse

import fsspec  # type: ignore  # type: ignore
from fsspec.asyn import AsyncFileSystem  # type: ignore
from fsspec.core import split_protocol  # type: ignore  # type: ignore
from fsspec.implementations.local import make_path_posix  # type: ignore
from pydantic import BaseModel
from s3fs import S3FileSystem  # type: ignore

# https://filesystem-spec.readthedocs.io/en/latest/_modules/fsspec/spec.html#AbstractFileSystem
# https://filesystem-spec.readthedocs.io/en/latest/api.html#fsspec.generic.GenericFileSystem


OpenTextMode = Literal["r", "a", "w"]
OpenBinaryMode = Literal["rb", "ab", "wb"]


@overload
@contextmanager
def file(
    file: str,
    mode: OpenTextMode,
    encoding: str = "utf-8",
    fs_options: dict[str, Any] = {},
) -> Iterator[io.TextIOWrapper]: ...


@overload
@contextmanager
def file(
    file: str,
    mode: OpenBinaryMode,
    encoding: str = "utf-8",
    fs_options: dict[str, Any] = {},
) -> Iterator[BinaryIO]: ...


@contextmanager
def file(
    file: str,
    mode: OpenTextMode | OpenBinaryMode,
    encoding: str = "utf-8",
    fs_options: dict[str, Any] = {},
) -> Iterator[io.TextIOWrapper] | Iterator[BinaryIO]:
    """Open local or remote file stream.

    Open a file stream for reading or writing. Refer to a local file or
    use a URI with a remove filesystem prefix (e.g. 's3://'). The
    `fsspec` package is used to resolve filesystem URLs.

    Args:
        file (str):
          Local file path or remove filesystem URL (e.g. 's3://')
        mode (str): Mode for accessing file ("r", "rb", "w", "wb", etc.).
        encoding: (str): Encoding for text files (defaults to "utf-8")
        fs_options (dict[str, Any]): Optional. Addional arguments to pass through
          to the filesystem provider (e.g. `S3FileSystem`). Use `{"anon": True }`
          if you are accessing a public S3 bucket with no credentials.

    """
    # get the default storage options for the scheme then apply passed options
    options = default_fs_options(file)
    options.update(fs_options)

    # open the file
    open_file = fsspec.open(file, mode=mode, encoding=encoding, **options)

    # yield the file and ensure it is closed when we exit the context
    with open_file as f:
        try:
            yield f
        finally:
            f.close()


def open_file(
    file: str,
    mode: OpenTextMode | OpenBinaryMode,
    encoding: str = "utf-8",
    fs_options: dict[str, Any] = {},
) -> fsspec.core.OpenFile:
    # get the default storage options for the scheme then apply passed options
    options = default_fs_options(file)
    options.update(fs_options)

    # open the file and return the stream
    return fsspec.open(file, mode=mode, encoding=encoding, **options)


# utility to copy a file
def copy_file(
    input_file: str,
    output_file: str,
    buffer_size: int = 1024 * 1024,
) -> None:
    """Copy a file across filesystems."""
    with file(input_file, "rb") as fin, file(output_file, "wb") as fout:
        while True:
            chunk = fin.read(buffer_size)
            if not chunk:
                break
            fout.write(chunk)


def basename(file: str) -> str:
    """Get the base name of the file.

    Works for all variations of fsspec providers, posix/windows/etc.

    Args:
       file (str): File name

    Returns:
       Base name for file
    """
    # windows paths aren't natively handled on posix so flip backslashes
    if os.sep == "/":
        file = file.replace("\\", "/")
    normalized_path = make_path_posix(file)
    _, path_without_protocol = split_protocol(normalized_path)
    name: str = path_without_protocol.rstrip("/").split("/")[-1]
    return name


def dirname(file: str) -> str:
    base = basename(file)
    return file[: -(len(base) + 1)]


def exists(file: str) -> bool:
    fs = filesystem(file)
    return fs.exists(file)


class FileInfo(BaseModel):
    name: str
    """Name of file."""

    type: str
    """Type of file (file or directory)"""

    size: int
    """File size in bytes."""

    mtime: float | None
    """File modification time (None if the file is a directory on S3)."""


class FileSystem:
    def __init__(self, fs: Any) -> None:
        self.fs = fs

    @property
    def sep(self) -> str:
        return cast(str, self.fs.sep)

    def exists(self, path: str) -> bool:
        return self.fs.exists(path) is True

    def rm(
        self, path: str, recursive: bool = False, maxdepth: int | None = None
    ) -> None:
        self.fs.rm(path, recursive=recursive, maxdepth=maxdepth)

    def mkdir(self, path: str, exist_ok: bool = False) -> None:
        if self.is_s3():
            # try to avoid calling create_bucket on s3 filesystems (as that requires distinct
            # privileges from being able to write to an existing bucket). we do this by
            # first calling mkdir w/ create_parents=False and then only if that fails
            # with FileNotFound do we attempt to create the bucket by calling mkdirs
            try:
                self.fs.makedir(path, create_parents=False)
            except FileExistsError:
                if exist_ok:
                    pass
                else:
                    raise
            except FileNotFoundError:
                self.fs.makedirs(path, exist_ok=exist_ok)
        else:
            self.fs.makedirs(path, exist_ok=exist_ok)

    def info(self, path: str, **kwargs: dict[str, Any]) -> FileInfo:
        return self._file_info(self.fs.info(path, **kwargs))

    def ls(
        self, path: str, recursive: bool = False, **kwargs: dict[str, Any]
    ) -> list[FileInfo]:
        # prevent caching of listings
        self.fs.invalidate_cache(path)

        # enumerate the files
        if recursive:
            files: list[dict[str, Any]] = []
            for _, _, filenames in self.fs.walk(path=path, detail=True, **kwargs):
                files.extend(filenames.values())
        else:
            files = cast(
                list[dict[str, Any]],
                self.fs.ls(path, detail=True, **kwargs),
            )

        # return FileInfo
        return [self._file_info(file) for file in files]

    def is_local(self) -> bool:
        return isinstance(self.fs, fsspec.implementations.local.LocalFileSystem)

    def is_async(self) -> bool:
        return isinstance(self.fs, fsspec.asyn.AsyncFileSystem)

    def is_s3(self) -> bool:
        return isinstance(self.fs, S3FileSystem)

    def put_file(self, lpath: str, rpath: str) -> None:
        self.fs.put_file(lpath, rpath)

    def get_file(self, rpath: str, lpath: str) -> None:
        self.fs.get_file(rpath, lpath)

    def read_bytes(self, path: str, start: int, end: int) -> bytes:
        return cast(bytes, self.fs.read_bytes(path, start, end))

    def _file_info(self, info: dict[str, Any]) -> FileInfo:
        # name needs the protocol prepended
        file = info.copy()
        file["name"] = self.fs.unstrip_protocol(file["name"])

        # S3 filesystems use "LastModified"
        if "LastModified" in file.keys():
            file["mtime"] = cast(
                datetime.datetime, cast(Any, file)["LastModified"]
            ).timestamp()
        # if we don't yet have an mtime key then fetch created explicitly
        # note: S3 doesn't give you a directory modification time
        if "mtime" not in file.keys() and file["type"] == "file":
            file["mtime"] = self.fs.created(file).timestamp()

        if "mtime" in file.keys():
            file["mtime"] = file["mtime"] * 1000
        else:
            file["mtime"] = None

        return FileInfo(
            name=file["name"],
            type=file["type"],
            size=file["size"],
            mtime=file["mtime"],
        )


def filesystem(path: str, fs_options: dict[str, Any] = {}) -> FileSystem:
    """Return the filesystem used to host the specified path.

    Args:
      path (str): Local path or remote URL e.g. s3://).  The
        `fsspec` package is used to resolve filesystem URLs.
      fs_options (dict[str, Any]): Optional. Additional arguments to pass through
        to the filesystem provider (e.g. `S3FileSystem`). Use `{"anon": True }`
        if you are accessing a public S3 bucket with no credentials.

    Returns:
       An tuple with an `fsspec` compatible filesystem and the
       file-systems-specific URL for file.
    """
    # determine options
    options = default_fs_options(path)
    options.update(fs_options)

    # create filesystem
    fs, path = fsspec.core.url_to_fs(path, **options)
    return FileSystem(fs)


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


def absolute_file_path(file: str) -> str:
    # check for a relative dir, if we find one then resolve to absolute
    fs_scheme = urlparse(file).scheme
    if not fs_scheme and not os.path.isabs(file):
        file = Path(file).resolve().as_posix()
    return file


def default_fs_options(file: str) -> dict[str, Any]:
    options = deepcopy(DEFAULT_FS_OPTIONS.get(urlparse(file).scheme, {}))
    # disable caching for all filesystems
    options.update(
        dict(
            skip_instance_cache=False,
            use_listings_cache=False,
        )
    )
    return options


def size_in_mb(file: str) -> float:
    # Open the file using fsspec and retrieve the file's information
    fs, path = fsspec.core.url_to_fs(file)

    # Use the filesystem's info method to get the size
    file_info = fs.info(path)

    # Extract the size from the file information
    file_size_in_bytes = cast(float, file_info["size"])

    # Get the size in megabytes
    file_size_in_mb = file_size_in_bytes / (1024 * 1024)
    return file_size_in_mb


def safe_filename(s: str, max_length: int = 255) -> str:
    """
    Convert a string into a safe filename by removing or replacing unsafe characters.

    Args:
        s (str): The input string to convert
        max_length (int): Maximum length of the resulting filename (default 255)

    Returns:
        str: A safe filename string

    Example:
        >>> safe_filename("Hello/World?.txt")
        'Hello_World.txt'
    """
    # normalize unicode characters
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ASCII", "ignore").decode("ASCII")

    # remove or replace unsafe characters
    # Keep only alphanumeric characters, dots, dashes, and underscores
    safe_chars = string.ascii_letters + string.digits + ".-_"
    s = "".join(c if c in safe_chars else "_" for c in s)

    # remove consecutive underscores
    s = re.sub(r"_+", "_", s)

    # remove leading/trailing periods and underscores
    s = s.strip("._")

    # handle empty string case
    if not s:
        s = "untitled"

    # handle starting with a period (hidden files)
    if s.startswith("."):
        s = "_" + s

    # enforce length limit
    if len(s) > max_length:
        # If we need to truncate, preserve the file extension if present
        name, ext = os.path.splitext(s)
        ext_len = len(ext)
        if ext_len > 0:
            max_name_length = max_length - ext_len
            s = name[:max_name_length] + ext
        else:
            s = s[:max_length]

    return s


DEFAULT_FS_OPTIONS: dict[str, dict[str, Any]] = dict(
    # disable all S3 native caching
    s3=dict(default_fill_cache=False, default_cache_type="none", cache_regions=False)
)
