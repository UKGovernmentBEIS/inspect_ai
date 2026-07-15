import asyncio
import io
import tempfile
import time
from pathlib import Path
from typing import Any, cast

import pytest
from anyio import EndOfStream
from botocore.exceptions import ClientError

from inspect_ai._util._async import run_coroutine, tg_collect
from inspect_ai._util.asyncfiles import (
    AsyncFilesystem,
    _current_async_fs,
    get_async_filesystem,
)

S3_BUCKET = "s3://test-bucket"


# =============================================================================
# Tests for read_file_bytes() with local files
# Code path: LocalFileStream (uses AnyIO async file operations)
# =============================================================================
async def test_local_read_file_bytes_basic_chunking():
    """Test read_file_bytes with local files and basic chunked reading."""
    test_data = b"Hello, World!"

    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(test_data)
        temp_path = f.name

    try:
        async with AsyncFilesystem() as fs:
            stream = await fs.read_file_bytes(temp_path, 0, len(test_data))

            chunk1 = await stream.receive(5)
            assert chunk1 == b"Hello"

            chunk2 = await stream.receive(7)
            assert chunk2 == b", World"

            chunk3 = await stream.receive(10)
            assert chunk3 == b"!"

            with pytest.raises(EndOfStream):
                await stream.receive(10)

            await stream.aclose()
    finally:
        Path(temp_path).unlink()


async def test_local_read_file_bytes_read_all_at_once():
    """Test reading entire range at once from local file."""
    test_data = b"0123456789"

    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(test_data)
        temp_path = f.name

    try:
        async with AsyncFilesystem() as fs:
            stream = await fs.read_file_bytes(temp_path, 0, len(test_data))

            chunk = await stream.receive(100)
            assert chunk == test_data

            with pytest.raises(EndOfStream):
                await stream.receive(10)

            await stream.aclose()
    finally:
        Path(temp_path).unlink()


async def test_local_read_file_bytes_empty_range():
    """Test reading empty byte range from local file."""
    test_data = b"0123456789"

    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(test_data)
        temp_path = f.name

    try:
        async with AsyncFilesystem() as fs:
            stream = await fs.read_file_bytes(temp_path, 5, 5)

            with pytest.raises(EndOfStream):
                await stream.receive(10)

            await stream.aclose()
    finally:
        Path(temp_path).unlink()


async def test_local_read_file_bytes_with_offset():
    """Test read_file_bytes with start/end offsets on local file."""
    test_data = b"0123456789ABCDEFGHIJ"

    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(test_data)
        temp_path = f.name

    try:
        async with AsyncFilesystem() as fs:
            stream = await fs.read_file_bytes(temp_path, 5, 15)

            chunk1 = await stream.receive(5)
            assert chunk1 == b"56789"

            chunk2 = await stream.receive(5)
            assert chunk2 == b"ABCDE"

            with pytest.raises(EndOfStream):
                await stream.receive(10)

            await stream.aclose()
    finally:
        Path(temp_path).unlink()


async def test_local_read_file_bytes_small_chunks():
    """Test read_file_bytes with very small chunk sizes on local file."""
    test_data = b"0123456789"

    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(test_data)
        temp_path = f.name

    try:
        async with AsyncFilesystem() as fs:
            stream = await fs.read_file_bytes(temp_path, 2, 8)

            chunks = []
            try:
                while True:
                    chunk = await stream.receive(2)
                    chunks.append(chunk)
            except EndOfStream:
                pass

            assert b"".join(chunks) == b"234567"
            await stream.aclose()
    finally:
        Path(temp_path).unlink()


async def test_local_read_file_bytes_large_file():
    """Test read_file_bytes with larger local file and multiple chunks."""
    test_data = b"0123456789" * 100  # 1000 bytes

    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(test_data)
        temp_path = f.name

    try:
        async with AsyncFilesystem() as fs:
            stream = await fs.read_file_bytes(temp_path, 10, 50)

            chunks = []
            try:
                while True:
                    chunk = await stream.receive(15)
                    chunks.append(chunk)
            except EndOfStream:
                pass

            result = b"".join(chunks)
            assert result == test_data[10:50]

            await stream.aclose()
    finally:
        Path(temp_path).unlink()


# =============================================================================
# Tests for read_file_bytes_fully() with local files
# This function reads a byte range and consumes it fully into bytes
# =============================================================================
async def test_local_read_file_bytes_fully_basic():
    """Test read_file_bytes_fully with basic byte range."""
    test_data = b"Hello, World!"

    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(test_data)
        temp_path = f.name

    try:
        async with AsyncFilesystem() as fs:
            result = await fs.read_file_bytes_fully(temp_path, 0, len(test_data))
            assert result == test_data
    finally:
        Path(temp_path).unlink()


async def test_local_read_file_bytes_fully_with_offset():
    """Test read_file_bytes_fully with start/end offsets."""
    test_data = b"0123456789ABCDEFGHIJ"

    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(test_data)
        temp_path = f.name

    try:
        async with AsyncFilesystem() as fs:
            result = await fs.read_file_bytes_fully(temp_path, 5, 15)
            assert result == b"56789ABCDE"
    finally:
        Path(temp_path).unlink()


async def test_local_read_file_bytes_fully_empty_range():
    """Test read_file_bytes_fully with empty byte range."""
    test_data = b"0123456789"

    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(test_data)
        temp_path = f.name

    try:
        async with AsyncFilesystem() as fs:
            result = await fs.read_file_bytes_fully(temp_path, 5, 5)
            assert result == b""
    finally:
        Path(temp_path).unlink()


async def test_local_read_file_bytes_fully_large_file():
    """Test read_file_bytes_fully with larger file."""
    test_data = b"0123456789" * 1000  # 10,000 bytes

    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(test_data)
        temp_path = f.name

    try:
        async with AsyncFilesystem() as fs:
            result = await fs.read_file_bytes_fully(temp_path, 100, 500)
            assert result == test_data[100:500]
            assert len(result) == 400
    finally:
        Path(temp_path).unlink()


async def test_local_read_file_bytes_fully_entire_file():
    """Test read_file_bytes_fully reading entire file."""
    test_data = b"Test content for full file read"

    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(test_data)
        temp_path = f.name

    try:
        async with AsyncFilesystem() as fs:
            result = await fs.read_file_bytes_fully(temp_path, 0, len(test_data))
            assert result == test_data
    finally:
        Path(temp_path).unlink()


# =============================================================================
# Tests for info() with local files
# =============================================================================
async def test_local_info_file():
    """Test info() returns correct FileInfo for a local file."""
    test_data = b"Hello, World!"

    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(test_data)
        temp_path = f.name

    try:
        async with AsyncFilesystem() as fs:
            info = await fs.info(temp_path)
            assert info.type == "file"
            assert info.size == len(test_data)
            assert info.mtime is not None
            assert info.name.endswith(Path(temp_path).name)
    finally:
        Path(temp_path).unlink()


async def test_local_info_directory():
    """Test info() returns correct FileInfo for a local directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        async with AsyncFilesystem() as fs:
            info = await fs.info(temp_dir)
            assert info.type == "directory"
            assert info.name.endswith(Path(temp_dir).name)


async def test_local_info_size_matches_get_size():
    """Test that info().size matches get_size() for local files."""
    test_data = b"0123456789" * 50  # 500 bytes

    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(test_data)
        temp_path = f.name

    try:
        async with AsyncFilesystem() as fs:
            info = await fs.info(temp_path)
            size = await fs.get_size(temp_path)
            assert info.size == size
    finally:
        Path(temp_path).unlink()


async def test_local_get_size():
    """Test AsyncFilesystem.get_size with local files."""
    test_data = b"0123456789" * 50  # 500 bytes

    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(test_data)
        temp_path = f.name

    try:
        async with AsyncFilesystem() as fs:
            size = await fs.get_size(temp_path)
            assert size == 500
    finally:
        Path(temp_path).unlink()


async def test_local_read_file():
    """Test AsyncFilesystem.read_file with local files."""
    test_data = b"Hello, World!"

    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(test_data)
        temp_path = f.name

    try:
        async with AsyncFilesystem() as fs:
            content = await fs.read_file(temp_path)
            assert content == test_data
    finally:
        Path(temp_path).unlink()


async def test_write_file_local():
    """Test AsyncFilesystem.write_file with local files."""
    test_data = b"Test write data"

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / "test_file.bin"

        async with AsyncFilesystem() as fs:
            await fs.write_file(str(temp_path), test_data)

        # Verify file was written correctly
        with open(temp_path, "rb") as f:
            content = f.read()
            assert content == test_data


# =============================================================================
# Tests for write_file_streaming
# =============================================================================


async def test_write_file_streaming_local():
    """Test AsyncFilesystem.write_file_streaming with local files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Small data
        small_data = b"Hello streaming world!" * 100
        small_path = str(Path(temp_dir) / "small.bin")
        source = io.BytesIO(small_data)

        async with AsyncFilesystem() as fs:
            await fs.write_file_streaming(small_path, source)

        with open(small_path, "rb") as f:
            assert f.read() == small_data

        # Large data exceeding _STREAMING_COPY_BUFSIZE (16MB)
        large_data = b"\xab" * (20 * 1024 * 1024)  # 20MB
        large_path = str(Path(temp_dir) / "large.bin")
        source = io.BytesIO(large_data)

        async with AsyncFilesystem() as fs:
            await fs.write_file_streaming(large_path, source)

        with open(large_path, "rb") as f:
            assert f.read() == large_data


def test_write_file_streaming_s3(mock_s3: None) -> None:
    """Test AsyncFilesystem.write_file_streaming with mock S3."""
    test_data = b"\xab" * (10 * 1024 * 1024)  # 10MB, exceeds 8MB multipart threshold
    s3_path = f"{S3_BUCKET}/streaming_test/file.bin"

    async def run() -> None:
        source = io.BytesIO(test_data)
        async with AsyncFilesystem() as fs:
            await fs.write_file_streaming(s3_path, source)
            result = await fs.read_file(s3_path)
            assert result == test_data

    asyncio.run(run())


class _RetryingUploadClient:
    def __init__(self, fail_times: int = 1) -> None:
        self.fail_times = fail_times
        self.calls = 0
        self.uploaded: list[bytes] = []

    def upload_fileobj_sync(
        self, Fileobj: Any, Bucket: str, Key: str, **kwargs: Any
    ) -> None:
        self.calls += 1
        data = Fileobj.read()
        if self.calls <= self.fail_times:
            raise ClientError(
                cast(
                    Any,
                    {
                        "Error": {"Code": "RequestTimeTooSkewed", "Message": "skewed"},
                        "ResponseMetadata": {"RequestId": "request-1"},
                    },
                ),
                "PutObject",
            )
        self.uploaded.append(data)

    async def upload_fileobj(
        self, Fileobj: Any, Bucket: str, Key: str, **kwargs: Any
    ) -> None:
        self.upload_fileobj_sync(Fileobj, Bucket, Key, **kwargs)


class _FailingUploadClient:
    def __init__(self, code: str) -> None:
        self.code = code
        self.calls = 0

    def upload_fileobj_sync(
        self, Fileobj: Any, Bucket: str, Key: str, **kwargs: Any
    ) -> None:
        self.calls += 1
        Fileobj.read()
        raise ClientError(
            cast(
                Any,
                {
                    "Error": {"Code": self.code, "Message": self.code},
                    "ResponseMetadata": {"RequestId": "request-1"},
                },
            ),
            "PutObject",
        )

    async def upload_fileobj(
        self, Fileobj: Any, Bucket: str, Key: str, **kwargs: Any
    ) -> None:
        self.upload_fileobj_sync(Fileobj, Bucket, Key, **kwargs)


class _SyncUploadClient:
    def __init__(self, client: Any) -> None:
        self._client = client

    def upload_fileobj(
        self, Fileobj: Any, Bucket: str, Key: str, **kwargs: Any
    ) -> None:
        self._client.upload_fileobj_sync(Fileobj, Bucket, Key, **kwargs)


class _NonSeekableBytesIO(io.BytesIO):
    def seekable(self) -> bool:
        return False


async def test_write_file_streaming_s3_retries_stale_signature_from_start(
    monkeypatch,
):
    client = _RetryingUploadClient()

    async def s3_client_async(self):
        return client

    def s3_client(self):
        return _SyncUploadClient(client)

    async def no_sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr(AsyncFilesystem, "s3_client_async", s3_client_async)
    monkeypatch.setattr(AsyncFilesystem, "s3_client", s3_client)
    monkeypatch.setattr("inspect_ai._util.asyncfiles.anyio.sleep", no_sleep)

    content = b"full eval log contents"
    async with AsyncFilesystem() as fs:
        await fs.write_file_streaming("s3://bucket/path/log.eval", io.BytesIO(content))

    assert client.calls == 2
    assert client.uploaded == [content]


async def test_write_file_streaming_s3_retries_stale_signature_full_budget(
    monkeypatch,
):
    """All stop_after_attempt(5) attempts are available.

    Note: this guards the attempt budget only. With anyio.sleep no-op'd the
    retries run in milliseconds, so it would not catch reintroduction of a
    wall-clock stop (stop_after_delay) — that only bites when an attempt
    itself consumes real time.
    """
    client = _RetryingUploadClient(fail_times=4)

    async def s3_client_async(self):
        return client

    def s3_client(self):
        return _SyncUploadClient(client)

    async def no_sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr(AsyncFilesystem, "s3_client_async", s3_client_async)
    monkeypatch.setattr(AsyncFilesystem, "s3_client", s3_client)
    monkeypatch.setattr("inspect_ai._util.asyncfiles.anyio.sleep", no_sleep)

    content = b"full eval log contents"
    async with AsyncFilesystem() as fs:
        await fs.write_file_streaming("s3://bucket/path/log.eval", io.BytesIO(content))

    assert client.calls == 5
    assert client.uploaded == [content]


async def test_write_file_streaming_s3_does_not_retry_non_seekable_source(
    monkeypatch,
):
    client = _FailingUploadClient("RequestTimeTooSkewed")

    async def s3_client_async(self):
        return client

    def s3_client(self):
        return _SyncUploadClient(client)

    monkeypatch.setattr(AsyncFilesystem, "s3_client_async", s3_client_async)
    monkeypatch.setattr(AsyncFilesystem, "s3_client", s3_client)

    async with AsyncFilesystem() as fs:
        with pytest.raises(ClientError) as exc_info:
            await fs.write_file_streaming(
                "s3://bucket/path/log.eval", _NonSeekableBytesIO(b"contents")
            )

    assert exc_info.value.response["Error"]["Code"] == "RequestTimeTooSkewed"
    assert client.calls == 1


async def test_write_file_streaming_s3_does_not_retry_non_retryable_error(
    monkeypatch,
):
    client = _FailingUploadClient("AccessDenied")

    async def s3_client_async(self):
        return client

    def s3_client(self):
        return _SyncUploadClient(client)

    monkeypatch.setattr(AsyncFilesystem, "s3_client_async", s3_client_async)
    monkeypatch.setattr(AsyncFilesystem, "s3_client", s3_client)

    async with AsyncFilesystem() as fs:
        with pytest.raises(ClientError) as exc_info:
            await fs.write_file_streaming(
                "s3://bucket/path/log.eval", io.BytesIO(b"contents")
            )

    assert exc_info.value.response["Error"]["Code"] == "AccessDenied"
    assert client.calls == 1


# =============================================================================
# Tests for get_file()
# =============================================================================


async def test_get_file_local() -> None:
    """get_file copies a local source to a local destination."""
    test_data = b"local get_file payload"

    with tempfile.TemporaryDirectory() as temp_dir:
        src = Path(temp_dir) / "src.bin"
        dst = Path(temp_dir) / "dst.bin"
        src.write_bytes(test_data)

        async with AsyncFilesystem() as fs:
            await fs.get_file(str(src), str(dst))

        assert dst.read_bytes() == test_data


def test_get_file_s3(mock_s3: None) -> None:
    """get_file downloads an S3 source to a local destination."""
    test_data = b"s3 get_file payload"
    s3_path = f"{S3_BUCKET}/get_file_test/file.bin"

    async def run() -> None:
        async with AsyncFilesystem() as fs:
            await fs.write_file(s3_path, test_data)
            with tempfile.TemporaryDirectory() as temp_dir:
                dst = Path(temp_dir) / "downloaded.bin"
                await fs.get_file(s3_path, str(dst))
                assert dst.read_bytes() == test_data

    asyncio.run(run())


# =============================================================================
# Tests for exists()
# =============================================================================


async def test_exists_local_true() -> None:
    """Existing local file returns True."""
    with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
        f.write(b"x")
        temp_path = f.name

    try:
        async with AsyncFilesystem() as fs:
            assert await fs.exists(temp_path) is True
    finally:
        Path(temp_path).unlink()


async def test_exists_local_false() -> None:
    """Missing local file returns False."""
    with tempfile.TemporaryDirectory() as temp_dir:
        missing = Path(temp_dir) / "does_not_exist.bin"
        async with AsyncFilesystem() as fs:
            assert await fs.exists(str(missing)) is False


def test_exists_s3_true(mock_s3: None) -> None:
    """Existing S3 key returns True."""
    s3_path = f"{S3_BUCKET}/exists_test/present.bin"

    async def run() -> None:
        async with AsyncFilesystem() as fs:
            await fs.write_file(s3_path, b"data")
            assert await fs.exists(s3_path) is True

    asyncio.run(run())


def test_exists_s3_false(mock_s3: None) -> None:
    """Missing S3 key returns False."""
    s3_path = f"{S3_BUCKET}/exists_test/absent.bin"

    async def run() -> None:
        async with AsyncFilesystem() as fs:
            assert await fs.exists(s3_path) is False

    asyncio.run(run())


# =============================================================================
# Tests for iter_files() and iter_dirs()
# =============================================================================


async def _collect(it):
    return [x async for x in it]


def _make_local_tree(root: Path) -> None:
    """Create a fixture tree for iter_files/iter_dirs tests.

    root/
      a.txt
      b.log
      sub1/
        c.txt
        d.log
        deep/
          e.txt
      sub2/
        f.txt
    """
    (root / "a.txt").write_bytes(b"a")
    (root / "b.log").write_bytes(b"b")
    (root / "sub1").mkdir()
    (root / "sub1" / "c.txt").write_bytes(b"c")
    (root / "sub1" / "d.log").write_bytes(b"d")
    (root / "sub1" / "deep").mkdir()
    (root / "sub1" / "deep" / "e.txt").write_bytes(b"e")
    (root / "sub2").mkdir()
    (root / "sub2" / "f.txt").write_bytes(b"f")


async def test_iter_files_local_one_level() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _make_local_tree(root)
        async with AsyncFilesystem() as fs:
            paths = await _collect(fs.iter_files(str(root)))
            names = sorted(Path(p).name for p in paths)
            assert names == ["a.txt", "b.log"]


async def test_iter_files_local_pattern() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _make_local_tree(root)
        async with AsyncFilesystem() as fs:
            paths = await _collect(fs.iter_files(str(root), "*.txt"))
            names = sorted(Path(p).name for p in paths)
            assert names == ["a.txt"]


async def test_iter_files_local_recursive() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _make_local_tree(root)
        async with AsyncFilesystem() as fs:
            paths = await _collect(fs.iter_files(str(root), "*.txt", recursive=True))
            names = sorted(Path(p).name for p in paths)
            assert names == ["a.txt", "c.txt", "e.txt", "f.txt"]


async def test_iter_files_local_empty_result() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _make_local_tree(root)
        async with AsyncFilesystem() as fs:
            paths = await _collect(fs.iter_files(str(root), "*.nope", recursive=True))
            assert paths == []


async def test_iter_files_local_question_mark_pattern() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "a1.txt").write_bytes(b"")
        (root / "a2.txt").write_bytes(b"")
        (root / "ab.txt").write_bytes(b"")
        async with AsyncFilesystem() as fs:
            paths = await _collect(fs.iter_files(str(root), "a?.txt"))
            names = sorted(Path(p).name for p in paths)
            assert names == ["a1.txt", "a2.txt", "ab.txt"]


async def test_iter_files_local_bracket_pattern() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "a1.txt").write_bytes(b"")
        (root / "a2.txt").write_bytes(b"")
        (root / "ab.txt").write_bytes(b"")
        async with AsyncFilesystem() as fs:
            paths = await _collect(fs.iter_files(str(root), "a[12].txt"))
            names = sorted(Path(p).name for p in paths)
            assert names == ["a1.txt", "a2.txt"]


async def test_iter_dirs_local_one_level() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _make_local_tree(root)
        async with AsyncFilesystem() as fs:
            paths = await _collect(fs.iter_dirs(str(root)))
            terminal = sorted(p.rstrip("/").rsplit("/", 1)[-1] for p in paths)
            assert terminal == ["sub1", "sub2"]
            for p in paths:
                assert p.endswith("/")


async def test_iter_dirs_local_pattern() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _make_local_tree(root)
        async with AsyncFilesystem() as fs:
            paths = await _collect(fs.iter_dirs(str(root), "sub1"))
            terminal = sorted(p.rstrip("/").rsplit("/", 1)[-1] for p in paths)
            assert terminal == ["sub1"]


async def test_iter_dirs_local_recursive() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _make_local_tree(root)
        async with AsyncFilesystem() as fs:
            paths = await _collect(fs.iter_dirs(str(root), "*", recursive=True))
            terminal = sorted(p.rstrip("/").rsplit("/", 1)[-1] for p in paths)
            assert terminal == ["deep", "sub1", "sub2"]


async def test_iter_dirs_local_recursive_pattern() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _make_local_tree(root)
        async with AsyncFilesystem() as fs:
            paths = await _collect(fs.iter_dirs(str(root), "deep", recursive=True))
            terminal = sorted(p.rstrip("/").rsplit("/", 1)[-1] for p in paths)
            assert terminal == ["deep"]


async def test_iter_dirs_local_empty() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "a.txt").write_bytes(b"")
        async with AsyncFilesystem() as fs:
            paths = await _collect(fs.iter_dirs(str(root)))
            assert paths == []


async def test_iter_files_local_excludes_dirs() -> None:
    """iter_files at one level returns only files, not dirs."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _make_local_tree(root)
        async with AsyncFilesystem() as fs:
            paths = await _collect(fs.iter_files(str(root)))
            for p in paths:
                assert not p.endswith("/")
                assert Path(p).is_file()


def test_iter_files_s3_one_level(mock_s3: None) -> None:
    base = f"{S3_BUCKET}/iter_test_files_1lvl"

    async def run() -> None:
        async with AsyncFilesystem() as fs:
            await fs.write_file(f"{base}/a.txt", b"a")
            await fs.write_file(f"{base}/b.log", b"b")
            await fs.write_file(f"{base}/sub/c.txt", b"c")
            paths = await _collect(fs.iter_files(base))
            assert sorted(paths) == [
                f"{base}/a.txt",
                f"{base}/b.log",
            ]

    asyncio.run(run())


def test_iter_files_s3_pattern(mock_s3: None) -> None:
    base = f"{S3_BUCKET}/iter_test_files_pat"

    async def run() -> None:
        async with AsyncFilesystem() as fs:
            await fs.write_file(f"{base}/a.txt", b"a")
            await fs.write_file(f"{base}/b.log", b"b")
            paths = await _collect(fs.iter_files(base, "*.txt"))
            assert sorted(paths) == [f"{base}/a.txt"]

    asyncio.run(run())


def test_iter_files_s3_recursive(mock_s3: None) -> None:
    base = f"{S3_BUCKET}/iter_test_files_rec"

    async def run() -> None:
        async with AsyncFilesystem() as fs:
            await fs.write_file(f"{base}/a.txt", b"a")
            await fs.write_file(f"{base}/sub/b.txt", b"b")
            await fs.write_file(f"{base}/sub/deep/c.txt", b"c")
            await fs.write_file(f"{base}/sub/d.log", b"d")
            paths = await _collect(fs.iter_files(base, "*.txt", recursive=True))
            assert sorted(paths) == [
                f"{base}/a.txt",
                f"{base}/sub/b.txt",
                f"{base}/sub/deep/c.txt",
            ]

    asyncio.run(run())


def test_iter_files_s3_missing_prefix(mock_s3: None) -> None:
    """Missing prefix returns empty iterator (not an error)."""

    async def run() -> None:
        async with AsyncFilesystem() as fs:
            paths = await _collect(
                fs.iter_files(f"{S3_BUCKET}/never_existed", recursive=True)
            )
            assert paths == []

    asyncio.run(run())


def test_iter_files_s3_pagination(mock_s3: None) -> None:
    """Pagination: >1000 keys must all be returned."""
    base = f"{S3_BUCKET}/iter_test_files_page"

    async def run() -> None:
        async with AsyncFilesystem() as fs:
            for i in range(1050):
                await fs.write_file(f"{base}/k{i:04d}.txt", b"x")
            paths = await _collect(fs.iter_files(base, recursive=True))
            assert len(paths) == 1050

    asyncio.run(run())


def test_iter_dirs_s3_one_level(mock_s3: None) -> None:
    base = f"{S3_BUCKET}/iter_test_dirs_1lvl"

    async def run() -> None:
        async with AsyncFilesystem() as fs:
            await fs.write_file(f"{base}/sub1/a.txt", b"a")
            await fs.write_file(f"{base}/sub1/b.txt", b"b")
            await fs.write_file(f"{base}/sub2/c.txt", b"c")
            await fs.write_file(f"{base}/file.txt", b"f")
            paths = await _collect(fs.iter_dirs(base))
            assert sorted(paths) == [f"{base}/sub1/", f"{base}/sub2/"]
            for p in paths:
                assert p.endswith("/")

    asyncio.run(run())


def test_iter_dirs_s3_recursive_dedup(mock_s3: None) -> None:
    """Recursive: dir with many files yields once."""
    base = f"{S3_BUCKET}/iter_test_dirs_dedup"

    async def run() -> None:
        async with AsyncFilesystem() as fs:
            for i in range(5):
                await fs.write_file(f"{base}/sub/f{i}.txt", b"x")
            paths = await _collect(fs.iter_dirs(base, "sub", recursive=True))
            assert paths == [f"{base}/sub/"]

    asyncio.run(run())


def test_iter_dirs_s3_recursive_depth(mock_s3: None) -> None:
    base = f"{S3_BUCKET}/iter_test_dirs_depth"

    async def run() -> None:
        async with AsyncFilesystem() as fs:
            await fs.write_file(f"{base}/sub1/deep/a.txt", b"a")
            await fs.write_file(f"{base}/sub2/b.txt", b"b")
            paths = await _collect(fs.iter_dirs(base, "*", recursive=True))
            assert sorted(paths) == [
                f"{base}/sub1/",
                f"{base}/sub1/deep/",
                f"{base}/sub2/",
            ]

    asyncio.run(run())


def test_iter_dirs_s3_recursive_excludes_ancestors(mock_s3: None) -> None:
    """Recursive iter_dirs must NOT yield ancestors of base."""
    base = f"{S3_BUCKET}/iter_test_dirs_anc/nested"

    async def run() -> None:
        async with AsyncFilesystem() as fs:
            await fs.write_file(f"{base}/inner/a.txt", b"a")
            paths = await _collect(fs.iter_dirs(base, "*", recursive=True))
            assert paths == [f"{base}/inner/"]

    asyncio.run(run())


def test_iter_dirs_s3_empty(mock_s3: None) -> None:
    async def run() -> None:
        async with AsyncFilesystem() as fs:
            paths = await _collect(fs.iter_dirs(f"{S3_BUCKET}/iter_test_dirs_empty"))
            assert paths == []

    asyncio.run(run())


# =============================================================================
# Tests for AsyncFilesystem sharing via ContextVar
# =============================================================================


@pytest.fixture(autouse=True)
def _reset_async_fs_contextvar() -> None:
    """Reset the ContextVar before each test to ensure isolation."""
    _current_async_fs.set(None)


async def test_context_manager_sets_contextvar() -> None:
    """Async with AsyncFilesystem() sets the ContextVar."""
    assert _current_async_fs.get() is None
    async with AsyncFilesystem() as fs:
        assert _current_async_fs.get() is fs


async def test_context_manager_cleans_up_on_exit() -> None:
    """Async with AsyncFilesystem() clears the ContextVar on exit."""
    async with AsyncFilesystem():
        assert _current_async_fs.get() is not None
    assert _current_async_fs.get() is None


async def test_nested_context_manager_reuses_outer() -> None:
    """Nested async with AsyncFilesystem() reuses the outer instance."""
    async with AsyncFilesystem() as outer_fs:
        async with AsyncFilesystem() as inner_fs:
            assert inner_fs is outer_fs


async def test_nested_context_manager_does_not_clean_up() -> None:
    """Inner async with AsyncFilesystem() does not clean up on exit."""
    async with AsyncFilesystem() as outer_fs:
        async with AsyncFilesystem():
            pass
        # Outer should still be active after inner exits
        assert _current_async_fs.get() is outer_fs
    # Only cleaned up after outer exits
    assert _current_async_fs.get() is None


async def test_get_async_filesystem_returns_current() -> None:
    """get_async_filesystem() returns the current shared instance."""
    async with AsyncFilesystem() as fs:
        assert get_async_filesystem() is fs


async def test_get_async_filesystem_raises_when_none() -> None:
    """get_async_filesystem() raises RuntimeError when no filesystem exists."""
    with pytest.raises(RuntimeError, match="No AsyncFilesystem is available"):
        get_async_filesystem()


# =============================================================================
# Tests for async S3 client TTL refresh (credential rotation pickup)
# =============================================================================


class _FakeS3Client:
    def __init__(self) -> None:
        self.closed = False

    async def __aexit__(self, *args: Any) -> None:
        self.closed = True


def _patch_client_factory(
    monkeypatch: pytest.MonkeyPatch, fs: AsyncFilesystem
) -> list[_FakeS3Client]:
    created: list[_FakeS3Client] = []

    async def fake_create(
        anonymous: bool = False, region_name: str | None = None
    ) -> _FakeS3Client:
        client = _FakeS3Client()
        created.append(client)
        return client

    monkeypatch.setattr(fs, "_create_s3_client_async", fake_create)
    return created


async def test_s3_client_async_reused_within_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fs = AsyncFilesystem(client_ttl=60)
    created = _patch_client_factory(monkeypatch, fs)

    client1 = await fs.s3_client_async()
    client2 = await fs.s3_client_async()

    assert client2 is client1
    assert len(created) == 1

    await fs.close()
    assert client1.closed


async def test_s3_client_async_recreated_after_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fs = AsyncFilesystem(client_ttl=60)
    created = _patch_client_factory(monkeypatch, fs)

    client1 = await fs.s3_client_async()
    fs._s3_client_async_created = time.monotonic() - 61
    client2 = await fs.s3_client_async()

    assert client2 is not client1
    assert len(created) == 2
    # the retired client stays open for in-flight operations
    assert not client1.closed

    await fs.close()
    assert client1.closed
    assert client2.closed


async def test_s3_client_async_no_ttl_never_recreates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fs = AsyncFilesystem()
    created = _patch_client_factory(monkeypatch, fs)

    client1 = await fs.s3_client_async()
    fs._s3_client_async_created = time.monotonic() - 24 * 60 * 60
    client2 = await fs.s3_client_async()

    assert client2 is client1
    assert len(created) == 1

    await fs.close()
    assert client1.closed


def test_run_coroutine_no_loop_uses_configured_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_coroutine() with no running loop honours INSPECT_ASYNC_BACKEND=trio."""
    import sniffio

    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", "trio")

    async def report_backend() -> str:
        return sniffio.current_async_library()

    assert run_coroutine(report_backend()) == "trio"
    assert _current_async_fs.get() is None


def test_run_coroutine_reenters_asyncio_loop_from_sync_callback() -> None:
    """run_coroutine() re-enters asyncio even when sniffio has no async context."""
    result: int | None = None
    errors: list[BaseException] = []

    async def inner() -> int:
        return 42

    def callback() -> None:
        nonlocal result
        try:
            result = run_coroutine(inner())
        except BaseException as ex:
            errors.append(ex)
        finally:
            asyncio.get_running_loop().stop()

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.call_soon(callback)
        loop.run_forever()
    finally:
        asyncio.set_event_loop(None)
        loop.close()

    if errors:
        raise errors[0]

    assert result == 42
    assert _current_async_fs.get() is None


def test_run_coroutine_cleans_up_filesystem() -> None:
    """run_coroutine() cleans up the filesystem created during execution."""

    async def use_filesystem() -> None:
        assert _current_async_fs.get() is not None

    run_coroutine(use_filesystem())
    assert _current_async_fs.get() is None


def test_run_coroutine_with_nest_asyncio_preserves_outer_filesystem() -> None:
    """run_coroutine() under nest_asyncio doesn't close inherited filesystem."""

    async def outer() -> None:
        async with AsyncFilesystem() as outer_fs:

            async def inner() -> None:
                # The inner context should see the inherited filesystem
                async with AsyncFilesystem() as inner_fs:
                    assert inner_fs is outer_fs

            run_coroutine(inner())

            # The outer filesystem should still be active
            assert _current_async_fs.get() is outer_fs

    asyncio.run(outer())


async def test_concurrent_tasks_share_filesystem() -> None:
    """Concurrent tasks via tg_collect share the same filesystem."""
    async with AsyncFilesystem() as fs:
        seen_filesystems: list[AsyncFilesystem] = []

        async def task() -> None:
            async with AsyncFilesystem() as task_fs:
                seen_filesystems.append(task_fs)

        await tg_collect([task, task, task])

        assert len(seen_filesystems) == 3
        for seen_fs in seen_filesystems:
            assert seen_fs is fs


def test_concurrent_tasks_in_run_coroutine_share_filesystem() -> None:
    """Child tasks spawned by tg_collect inside run_coroutine share one filesystem.

    run_coroutine wraps the coroutine in async with AsyncFilesystem(), so the
    ContextVar is set in the parent context before tg_collect/start_soon copies
    it for child tasks.
    """
    seen_filesystems: list[AsyncFilesystem] = []

    async def task() -> None:
        async with AsyncFilesystem() as fs:
            seen_filesystems.append(fs)

    async def run_concurrent() -> None:
        await tg_collect([task, task, task])

    run_coroutine(run_concurrent())

    assert len(seen_filesystems) == 3
    assert seen_filesystems[0] is seen_filesystems[1]
    assert seen_filesystems[1] is seen_filesystems[2]


# =============================================================================
# Tests for nest_asyncio with mock S3
# =============================================================================


@pytest.mark.skip(reason="Slow (allocates 5GB+) and requires real S3 credentials")
async def test_write_file_s3_large_file() -> None:
    """write_file fails for S3 files larger than 5GB because put_object has a 5GB limit.

    S3 put_object API has a hard 5GB limit. Files larger than 5GB require
    multipart upload, which write_file does not currently support.
    """
    size = 5 * 1024 * 1024 * 1024 + 1  # 5GB + 1 byte
    large_data = b"\x00" * size

    async with AsyncFilesystem() as fs:
        await fs.write_file("s3://inspect-flow-test/large_test/big.bin", large_data)


def test_nest_asyncio_with_s3_requests(mock_s3: None) -> None:
    """Nested run_coroutine shares filesystem and both S3 requests succeed.

    Outer loop: creates AsyncFilesystem, writes/reads file1 from mock S3.
    Inner loop: run_coroutine() triggers nest_asyncio, writes/reads file2.
    Both requests complete correctly, and the outer filesystem survives.
    """
    file1 = f"{S3_BUCKET}/nest_test/file1.txt"
    file2 = f"{S3_BUCKET}/nest_test/file2.txt"
    data1 = b"outer context data"
    data2 = b"inner context data"

    async def outer() -> None:
        async with AsyncFilesystem() as outer_fs:
            # Write and read file1 in the outer context
            await outer_fs.write_file(file1, data1)
            result1 = await outer_fs.read_file(file1)
            assert result1 == data1
            future1 = outer_fs.read_file(file1)

            # Inner loop via run_coroutine (triggers nest_asyncio)
            async def inner() -> bytes:
                # The inner context should reuse the outer filesystem
                async with AsyncFilesystem() as inner_fs:
                    assert inner_fs is outer_fs
                    await inner_fs.write_file(file2, data2)
                    result1 = await future1
                    assert result1 == data1
                    return await inner_fs.read_file(file2)

            inner_result = run_coroutine(inner())
            assert inner_result == data2

            # Outer filesystem should still be active after inner exits
            assert _current_async_fs.get() is outer_fs

            # Outer can still read both files
            assert await outer_fs.read_file(file1) == data1
            assert await outer_fs.read_file(file2) == data2

    asyncio.run(outer())
