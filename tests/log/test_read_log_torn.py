"""Header reads of a ``.eval`` log that its writer replaces during the read.

A header read makes separate range requests (suffix, central directory,
members), so a replacement between two of them mixes two versions of the
object. Each test replaces the log at a chosen request and checks that the
read is re-read from the new version, or fails as before.
"""

import io
import json
import os
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import boto3
import pytest
from botocore.exceptions import ClientError

from inspect_ai._util.async_zip import is_torn_read
from inspect_ai._util.asyncfiles import (
    AsyncFilesystem,
    ObjectChangedError,
    SuffixResult,
)
from inspect_ai.log import read_eval_log, read_eval_log_async, write_eval_log
from inspect_ai.log._recorders.eval import READ_IN_PLACE_ATTEMPTS

BUCKET = "test-bucket"


@pytest.fixture(scope="module")
def log_members(tmp_path_factory: pytest.TempPathFactory) -> list[tuple[str, bytes]]:
    log = read_eval_log("tests/log/test_eval_log/log_formats.json")
    path = tmp_path_factory.mktemp("torn") / "log.eval"
    write_eval_log(log, path.as_posix())
    with zipfile.ZipFile(path) as zf:
        return [(name, zf.read(name)) for name in zf.namelist()]


def _zip(members: list[tuple[str, bytes]], *, version: str) -> bytes:
    """A ``.eval`` of ``members`` whose header is tagged with ``version``."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members:
            if name == "header.json":
                header = json.loads(data)
                header["eval"]["metadata"] = {"version": version}
                data = json.dumps(header).encode()
            # a stored member (incompressible padding) keeps its full size
            method = (
                zipfile.ZIP_STORED if name.startswith("pad") else zipfile.ZIP_DEFLATED
            )
            zf.writestr(name, data, compress_type=method)
    return buf.getvalue()


def _pad(count: int, size: int = 0, name: str = "pad") -> list[tuple[str, bytes]]:
    return [(f"{name}/{i:05d}-{'x' * 40}", os.urandom(size)) for i in range(count)]


class _Log:
    """One log at ``location`` that a test replaces between reads."""

    def __init__(self, location: str, tmp_path: Path) -> None:
        self.location = location
        self._tmp = tmp_path

    def put(self, data: bytes) -> str | None:
        if self.location.startswith("s3://"):
            key = self.location.removeprefix(f"s3://{BUCKET}/")
            etag = boto3.client("s3").put_object(Bucket=BUCKET, Key=key, Body=data)
            return str(etag["ETag"]).strip('"')
        # like the recorder's local writes: a new file renamed over the old
        tmp = self._tmp / "replacement"
        tmp.write_bytes(data)
        os.replace(tmp, self.location)
        return None


@pytest.fixture(params=["local", "s3"])
def torn_log(request: pytest.FixtureRequest, tmp_path: Path) -> _Log:
    if request.param == "s3":
        request.getfixturevalue("mock_s3")
        return _Log(f"s3://{BUCKET}/{tmp_path.name}.eval", tmp_path)
    return _Log((tmp_path / "log.eval").as_posix(), tmp_path)


@pytest.fixture
def s3_log(mock_s3: None, tmp_path: Path) -> _Log:
    return _Log(f"s3://{BUCKET}/{tmp_path.name}.eval", tmp_path)


def _replace_after_suffix_reads(
    monkeypatch: pytest.MonkeyPatch, replace: Callable[[int], object]
) -> list[int]:
    """Call ``replace(n)`` right after the n-th suffix read (1-based) returns."""
    calls: list[int] = []
    original = AsyncFilesystem.read_file_suffix

    async def suffix(self: AsyncFilesystem, filename: str, n: int) -> SuffixResult:
        result = await original(self, filename, n)
        calls.append(len(calls) + 1)
        replace(len(calls))
        return result

    monkeypatch.setattr(AsyncFilesystem, "read_file_suffix", suffix)
    return calls


def _range_read_errors(monkeypatch: pytest.MonkeyPatch) -> list[BaseException]:
    """The errors that range reads (central directory, members) raise."""
    errors: list[BaseException] = []
    original = AsyncFilesystem.read_file_bytes_fully

    async def spy(self: AsyncFilesystem, *args: Any, **kwargs: Any) -> bytes:
        try:
            return await original(self, *args, **kwargs)
        except Exception as ex:
            errors.append(ex)
            raise

    monkeypatch.setattr(AsyncFilesystem, "read_file_bytes_fully", spy)
    return errors


async def test_header_read_is_re_read_when_the_log_is_replaced_before_its_central_directory_read(
    s3_log: _Log,
    log_members: list[tuple[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a central directory larger than the suffix read needs its own range
    # read, which is pinned to the suffix's ETag
    big = log_members + _pad(1000)
    s3_log.put(_zip(big, version="A"))
    replaced = _zip(_pad(300, name="pad2") + big, version="B")
    etags: list[str | None] = []
    suffix_reads = _replace_after_suffix_reads(
        monkeypatch, lambda n: etags.append(s3_log.put(replaced)) if n == 1 else None
    )
    range_errors = _range_read_errors(monkeypatch)

    header = await read_eval_log_async(s3_log.location, header_only=True)

    assert header.eval.metadata == {"version": "B"}
    assert header.etag == etags[0]
    assert suffix_reads == [1, 2]
    # the pin, not a parse error, caught the replacement
    assert [type(ex) for ex in range_errors] == [ObjectChangedError]


async def test_header_read_is_re_read_when_a_member_changed_in_place(
    s3_log: _Log,
    log_members: list[tuple[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # header.json keeps its offset and length, so only its CRC shows that
    # the member read came from the replacement
    original = _zip(log_members, version="A")
    replaced = _zip(log_members, version="B")
    assert len(replaced) == len(original)
    s3_log.put(original)
    etags: list[str | None] = []
    suffix_reads = _replace_after_suffix_reads(
        monkeypatch, lambda n: etags.append(s3_log.put(replaced)) if n == 1 else None
    )

    header = await read_eval_log_async(s3_log.location, header_only=True)

    assert header.eval.metadata == {"version": "B"}
    assert header.etag == etags[0]
    assert suffix_reads == [1, 2]


async def test_header_read_is_re_read_when_member_offsets_moved(
    tmp_path: Path,
    log_members: list[tuple[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the central directory fits the suffix read, so the next request reads
    # header.json at its offset in the old version. Local only: on S3 that
    # read lands past the end, which is the shrink test's InvalidRange.
    log = _Log((tmp_path / "log.eval").as_posix(), tmp_path)
    log.put(_zip(log_members, version="A"))
    replaced = _zip(_pad(10, size=200) + log_members, version="B")
    suffix_reads = _replace_after_suffix_reads(
        monkeypatch, lambda n: log.put(replaced) if n == 1 else None
    )

    header = await read_eval_log_async(log.location, header_only=True)

    assert header.eval.metadata == {"version": "B"}
    assert suffix_reads == [1, 2]


async def test_header_read_is_re_read_when_the_log_shrank_past_a_member_offset(
    s3_log: _Log,
    log_members: list[tuple[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a compacting finish: header.json's old offset lies past the new end,
    # which S3 answers with InvalidRange (416)
    s3_log.put(_zip(_pad(1, size=200_000) + log_members, version="A"))
    replaced = _zip(log_members, version="B")
    suffix_reads = _replace_after_suffix_reads(
        monkeypatch, lambda n: s3_log.put(replaced) if n == 1 else None
    )
    member_errors = _range_read_errors(monkeypatch)

    header = await read_eval_log_async(s3_log.location, header_only=True)

    assert header.eval.metadata == {"version": "B"}
    assert suffix_reads == [1, 2]
    assert [
        ex.response["Error"]["Code"]
        for ex in member_errors
        if isinstance(ex, ClientError)
    ] == ["InvalidRange"]


async def test_header_read_raises_the_last_torn_error_when_re_reads_are_exhausted(
    torn_log: _Log,
    log_members: list[tuple[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    versions = [
        _zip(log_members, version="A"),
        _zip(_pad(10, size=200) + log_members, version="B"),
    ]
    torn_log.put(versions[0])
    # every read is torn: the log is replaced after each suffix read
    suffix_reads = _replace_after_suffix_reads(
        monkeypatch, lambda n: torn_log.put(versions[n % 2])
    )

    with pytest.raises(Exception) as raised:
        await read_eval_log_async(torn_log.location, header_only=True)

    assert is_torn_read(raised.value)
    assert len(suffix_reads) == READ_IN_PLACE_ATTEMPTS


async def test_header_read_does_not_re_read_other_storage_errors(
    s3_log: _Log,
    log_members: list[tuple[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s3_log.put(_zip(log_members, version="A"))
    suffix_reads = _replace_after_suffix_reads(monkeypatch, lambda n: None)

    async def denied(self: AsyncFilesystem, *args: Any, **kwargs: Any) -> bytes:
        raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")

    monkeypatch.setattr(AsyncFilesystem, "read_file_bytes_fully", denied)

    with pytest.raises(ClientError, match="AccessDenied"):
        await read_eval_log_async(s3_log.location, header_only=True)
    assert suffix_reads == [1]


async def test_header_read_is_not_re_read_when_cancelled(
    tmp_path: Path,
    log_members: list[tuple[str, bytes]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _Log((tmp_path / "log.eval").as_posix(), tmp_path)
    log.put(_zip(log_members, version="A"))
    suffix_reads: list[int] = []

    with anyio.CancelScope() as scope:

        async def suffix(self: AsyncFilesystem, filename: str, n: int) -> SuffixResult:
            suffix_reads.append(1)
            scope.cancel()
            await anyio.sleep(1)
            raise AssertionError("not cancelled")

        monkeypatch.setattr(AsyncFilesystem, "read_file_suffix", suffix)
        await read_eval_log_async(log.location, header_only=True)

    assert scope.cancelled_caught
    assert suffix_reads == [1]
