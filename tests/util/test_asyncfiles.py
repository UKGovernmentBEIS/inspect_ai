import asyncio
import tempfile
from pathlib import Path

import pytest
from anyio import EndOfStream

from inspect_ai._util._async import run_coroutine, tg_collect
from inspect_ai._util.asyncfiles import (
    AsyncFilesystem,
    _current_async_fs,
    cleanup_async_filesystem,
    get_or_create_async_filesystem,
    has_async_filesystem,
)

# =============================================================================
# Tests for read_file_bytes() with local files
# Code path: LocalFileStream (uses AnyIO async file operations)
# =============================================================================


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_local_info_directory():
    """Test info() returns correct FileInfo for a local directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        async with AsyncFilesystem() as fs:
            info = await fs.info(temp_dir)
            assert info.type == "directory"
            assert info.name.endswith(Path(temp_dir).name)


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_get_or_create_creates_on_first_call() -> None:
    """get_or_create_async_filesystem() creates a new instance when none exists."""
    assert not has_async_filesystem()
    fs = get_or_create_async_filesystem()
    assert fs is not None
    assert isinstance(fs, AsyncFilesystem)
    assert has_async_filesystem()


@pytest.mark.asyncio
async def test_get_or_create_returns_same_instance() -> None:
    """get_or_create_async_filesystem() returns the same instance on subsequent calls."""
    fs1 = get_or_create_async_filesystem()
    fs2 = get_or_create_async_filesystem()
    assert fs1 is fs2


@pytest.mark.asyncio
async def test_cleanup_closes_and_clears() -> None:
    """cleanup_async_filesystem() closes the filesystem and clears the ContextVar."""
    get_or_create_async_filesystem()
    assert has_async_filesystem()
    await cleanup_async_filesystem()
    assert not has_async_filesystem()


@pytest.mark.asyncio
async def test_cleanup_noop_when_none() -> None:
    """cleanup_async_filesystem() is a no-op when no filesystem exists."""
    assert not has_async_filesystem()
    await cleanup_async_filesystem()
    assert not has_async_filesystem()


@pytest.mark.asyncio
async def test_context_manager_sets_contextvar() -> None:
    """Async with AsyncFilesystem() sets the ContextVar."""
    assert not has_async_filesystem()
    async with AsyncFilesystem() as fs:
        assert has_async_filesystem()
        assert get_or_create_async_filesystem() is fs


@pytest.mark.asyncio
async def test_context_manager_cleans_up_on_exit() -> None:
    """Async with AsyncFilesystem() clears the ContextVar on exit."""
    async with AsyncFilesystem():
        assert has_async_filesystem()
    assert not has_async_filesystem()


@pytest.mark.asyncio
async def test_nested_context_manager_reuses_outer() -> None:
    """Nested async with AsyncFilesystem() reuses the outer instance."""
    async with AsyncFilesystem() as outer_fs:
        async with AsyncFilesystem() as inner_fs:
            assert inner_fs is outer_fs
            assert get_or_create_async_filesystem() is outer_fs


@pytest.mark.asyncio
async def test_nested_context_manager_does_not_clean_up() -> None:
    """Inner async with AsyncFilesystem() does not clean up on exit."""
    async with AsyncFilesystem() as outer_fs:
        async with AsyncFilesystem():
            pass
        # Outer should still be active after inner exits
        assert has_async_filesystem()
        assert get_or_create_async_filesystem() is outer_fs
    # Only cleaned up after outer exits
    assert not has_async_filesystem()


def test_run_coroutine_cleans_up_filesystem() -> None:
    """run_coroutine() cleans up the filesystem created during execution."""

    async def use_filesystem() -> AsyncFilesystem:
        fs = get_or_create_async_filesystem()
        assert has_async_filesystem()
        return fs

    run_coroutine(use_filesystem())
    # After run_coroutine returns, the ContextVar should be cleared.
    # Note: asyncio.run() creates a new context copy, so the outer
    # context was never modified. Verify by checking our thread-level state.
    assert not has_async_filesystem()


def test_run_coroutine_with_nest_asyncio_preserves_outer_filesystem() -> None:
    """run_coroutine() under nest_asyncio doesn't close inherited filesystem."""

    async def outer() -> None:
        outer_fs = get_or_create_async_filesystem()

        # Simulate what happens when sync code calls run_coroutine()
        # while an async context with a filesystem is already running.
        # run_coroutine will detect the running loop, apply nest_asyncio,
        # and call asyncio.run() which inherits the context.
        async def inner() -> None:
            # The inner context should see the inherited filesystem
            inner_fs = get_or_create_async_filesystem()
            assert inner_fs is outer_fs

        run_coroutine(inner())

        # The outer filesystem should still be active
        assert has_async_filesystem()
        assert get_or_create_async_filesystem() is outer_fs

    asyncio.run(outer())


@pytest.mark.asyncio
async def test_concurrent_tasks_share_filesystem() -> None:
    """Concurrent tasks via tg_collect share the same filesystem."""
    fs = get_or_create_async_filesystem()
    seen_filesystems: list[AsyncFilesystem] = []

    async def task() -> None:
        task_fs = get_or_create_async_filesystem()
        seen_filesystems.append(task_fs)

    await tg_collect([task, task, task])

    assert len(seen_filesystems) == 3
    for seen_fs in seen_filesystems:
        assert seen_fs is fs


def test_concurrent_tasks_in_run_coroutine_share_filesystem() -> None:
    """Child tasks spawned by tg_collect inside run_coroutine share one filesystem.

    When run_coroutine calls asyncio.run(), and the coroutine spawns concurrent
    tasks via tg_collect/start_soon, each child task gets a copy of the parent
    context. If the filesystem is only created lazily inside a child task, the
    ContextVar write is invisible to sibling tasks and each creates its own
    instance. The filesystem must be set in the parent context before spawning.
    """
    seen_filesystems: list[AsyncFilesystem] = []

    async def task() -> None:
        fs = get_or_create_async_filesystem()
        seen_filesystems.append(fs)

    async def run_concurrent() -> None:
        await tg_collect([task, task, task])

    run_coroutine(run_concurrent())

    assert len(seen_filesystems) == 3
    # All three tasks must have seen the same instance
    assert seen_filesystems[0] is seen_filesystems[1]
    assert seen_filesystems[1] is seen_filesystems[2]


def test_get_or_create_does_not_cache_in_sync_context() -> None:
    """get_or_create_async_filesystem() does not set ContextVar from sync code."""
    fs = get_or_create_async_filesystem()
    assert fs is not None
    # Should not be cached since we're not in an async context
    assert not has_async_filesystem()
    # Subsequent call returns a different instance
    fs2 = get_or_create_async_filesystem()
    assert fs2 is not fs
