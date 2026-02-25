import asyncio
import tempfile
from pathlib import Path

import pytest
from anyio import EndOfStream

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
