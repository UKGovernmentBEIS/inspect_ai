import tempfile
from pathlib import Path

import pytest
from anyio import EndOfStream

from inspect_ai._util.asyncfiles import AsyncFilesystem

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
# Tests for read_file_bytes() with S3 files (asyncio backend)
# Code path: S3BodyStream (wraps aioboto3 response body)
# =============================================================================

# Test S3 file URL (public, anonymous access)
S3_TEST_URL = "s3://slow-tests/swe_bench.eval"


@pytest.mark.anyio
@pytest.mark.slow
async def test_s3_read_file_bytes_basic_chunking(anyio_backend):
    async with AsyncFilesystem(anonymous_s3=True) as fs:
        # Read first 100 bytes
        stream = await fs.read_file_bytes(S3_TEST_URL, 0, 100)

        chunk1 = await stream.receive(4)
        assert len(chunk1) == 4
        assert chunk1 == b"PK\x03\x04"

        chunk2 = await stream.receive(30)
        assert len(chunk2) == 30

        # Read remaining chunks
        chunks = [chunk1, chunk2]
        try:
            while True:
                chunk = await stream.receive(25)
                chunks.append(chunk)
        except EndOfStream:
            pass

        result = b"".join(chunks)
        assert len(result) == 100

        await stream.aclose()


@pytest.mark.anyio
@pytest.mark.slow
async def test_s3_read_file_bytes_with_offset(anyio_backend):
    async with AsyncFilesystem(anonymous_s3=True) as fs:
        # Read bytes 10-50
        stream = await fs.read_file_bytes(S3_TEST_URL, 10, 50)

        result = b""
        try:
            while True:
                result += await stream.receive(15)
        except EndOfStream:
            pass

        assert len(result) == 40

        await stream.aclose()


@pytest.mark.anyio
@pytest.mark.slow
async def test_s3_read_file_bytes_small_chunks(anyio_backend):
    async with AsyncFilesystem(anonymous_s3=True) as fs:
        stream = await fs.read_file_bytes(S3_TEST_URL, 0, 50)

        chunks = []
        try:
            while True:
                chunk = await stream.receive(5)
                chunks.append(chunk)
        except EndOfStream:
            pass

        result = b"".join(chunks)
        assert len(result) == 50

        await stream.aclose()


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
