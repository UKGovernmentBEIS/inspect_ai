"""Validated, bounded re-reads of one ``.eval`` log.

A running log is replaced on every flush, and the central-directory read and
each member read are separate range requests, so one read can mix bytes from
two versions of the object. Every member is checked against the central
directory's CRC-32; a mismatch, a decompression error or a JSON error re-reads
the central directory and the member, up to :data:`MAX_REREADS` times. See
"Reading a member consistently" in ``design/ctl/log-dir-mode.md``.
"""

from __future__ import annotations

import importlib
import struct
import zlib
from collections.abc import Awaitable, Callable
from typing import TypeVar

import zstandard
from pydantic import ValidationError

from inspect_ai._util.async_zip import AsyncZipReader, CentralDirectory, ZipCrcError
from inspect_ai._util.asyncfiles import AsyncFilesystem

MAX_REREADS = 2
"""Re-reads after the first attempt before a read is reported as failed."""

# What a read whose bytes came from two object versions can raise. A pydantic
# ValidationError is not among them: it is raised only after the bytes passed
# their CRC check, so it means the member itself does not parse.
# ijson ships no type information; every parse error it raises derives from this
_IJSON_ERROR: type[Exception] = importlib.import_module("ijson").JSONError

_TORN_READ_ERRORS = (
    ZipCrcError,
    zlib.error,
    zstandard.ZstdError,
    struct.error,
    EOFError,
    _IJSON_ERROR,
    ValueError,
)

_T = TypeVar("_T")


class LogChangedError(Exception):
    """A log kept changing under a read after the bounded re-reads."""

    def __init__(self, location: str, detail: str) -> None:
        super().__init__(
            f"{location} changed during the read and did not settle after "
            f"{MAX_REREADS + 1} attempts ({detail})"
        )
        self.location = location


class LogUnparseableError(Exception):
    """A log exists but cannot be read as an Inspect ``.eval`` log."""

    def __init__(self, location: str, detail: str) -> None:
        super().__init__(f"{location} could not be parsed: {detail}")
        self.location = location


async def read_consistently(
    fs: AsyncFilesystem,
    location: str,
    read: Callable[[AsyncZipReader, bool], Awaitable[_T]],
    *,
    central_directory: CentralDirectory | None = None,
) -> _T:
    """Run ``read`` over a CRC-verifying reader, re-reading on a torn read.

    ``read(reader, fresh)`` gets a reader whose every member read is checked
    against its central directory's CRC-32. The first attempt reuses
    ``central_directory`` when given (``fresh`` is then False); every later
    attempt reads the central directory again (``fresh`` True), so ``read``
    must re-derive anything it took from the old one.

    Raises:
        LogChangedError: the reads kept failing their CRC check.
        LogUnparseableError: the bytes were consistent but do not parse, or
            the reads kept failing to decompress or parse.
    """
    last: BaseException | None = None
    for attempt in range(MAX_REREADS + 1):
        reuse = central_directory if attempt == 0 else None
        reader = AsyncZipReader(fs, location, verify_crc=True, central_directory=reuse)
        try:
            return await read(reader, reuse is None)
        except ValidationError as ex:
            raise LogUnparseableError(location, str(ex)) from ex
        except _TORN_READ_ERRORS as ex:
            last = ex
    assert last is not None
    if isinstance(last, ZipCrcError):
        raise LogChangedError(location, str(last)) from last
    raise LogUnparseableError(location, str(last) or type(last).__name__) from last
