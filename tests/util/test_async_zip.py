import json
import os
import sys
import zipfile
import zlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.compression_transcoding import _DeflateCompressStream

# Import zipfile-zstd for Python < 3.14 (monkey-patches zipfile to support zstd)
if sys.version_info < (3, 14):
    import zipfile_zstd  # type: ignore[import-untyped]  # noqa: F401


@pytest.fixture
def test_zip_file(tmp_path: Path) -> Path:
    """Create a test ZIP file with sample data."""
    zip_path = tmp_path / "test_data.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add test.json
        zf.writestr("test.json", json.dumps({"message": "hello world"}))
        # Add nested file
        zf.writestr("nested/data.txt", "This is nested data")

    return zip_path


@pytest.mark.asyncio
async def test_read_local_zip_member(test_zip_file: Path) -> None:
    """Test reading a member from a local ZIP file."""
    zip_path = str(test_zip_file)

    async with AsyncFilesystem() as fs:
        reader = AsyncZipReader(fs, zip_path)

        # Read the test.json member
        chunks = []
        async with await reader.open_member("test.json") as stream:
            async for chunk in stream:
                chunks.append(chunk)

        # Verify content
        data = b"".join(chunks)
        parsed = json.loads(data.decode("utf-8"))
        assert parsed["message"] == "hello world"


@pytest.mark.asyncio
async def test_read_nested_member(test_zip_file: Path) -> None:
    """Test reading a nested member from a local ZIP file."""
    zip_path = str(test_zip_file)

    async with AsyncFilesystem() as fs:
        reader = AsyncZipReader(fs, zip_path)

        # Read the nested member
        chunks = []
        async with await reader.open_member("nested/data.txt") as stream:
            async for chunk in stream:
                chunks.append(chunk)

        data = b"".join(chunks)
        assert data == b"This is nested data"


@pytest.mark.asyncio
async def test_open_member_reiteration(test_zip_file: Path) -> None:
    """Test that a member can be iterated multiple times within same context."""
    zip_path = str(test_zip_file)

    async with AsyncFilesystem() as fs:
        reader = AsyncZipReader(fs, zip_path)

        async with await reader.open_member("test.json") as member:
            data1 = b"".join([chunk async for chunk in member])
            data2 = b"".join([chunk async for chunk in member])

        assert data1 == data2
        assert json.loads(data1.decode("utf-8"))["message"] == "hello world"


@pytest.mark.asyncio
async def test_concurrent_iteration(tmp_path: Path) -> None:
    """Test that multiple concurrent iterators work correctly."""
    # Create zip with large incompressible file to force multiple chunks
    zip_path = tmp_path / "large.zip"
    large_data = os.urandom(1024 * 1024 * 2)  # 2MB random data

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("large.bin", large_data)

    async with AsyncFilesystem() as fs:
        reader = AsyncZipReader(fs, str(zip_path))

        async with await reader.open_member("large.bin") as member:
            # Get two independent iterators
            iter1 = aiter(member)
            iter2 = aiter(member)

            # Interleave: get first chunk from iter1, then from iter2
            chunk1_first = await anext(iter1)

            # Starting iter2 should NOT break iter1
            chunk2_first = await anext(iter2)

            # Continue iter1 - this is where the bug manifests
            chunks1 = [chunk1_first] + [chunk async for chunk in iter1]
            chunks2 = [chunk2_first] + [chunk async for chunk in iter2]

            data1 = b"".join(chunks1)
            data2 = b"".join(chunks2)

            # Both should get complete data
            assert data1 == large_data
            assert data2 == large_data


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["", None])
async def test_rejects_falsy_filename(filename: str | None) -> None:
    """Test that AsyncZipReader rejects falsy filenames."""
    async with AsyncFilesystem() as fs:
        with pytest.raises(ValueError):
            AsyncZipReader(fs, filename)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_member_not_found(test_zip_file: Path) -> None:
    """Test that KeyError is raised for non-existent member."""
    zip_path = str(test_zip_file)

    async with AsyncFilesystem() as fs:
        reader = AsyncZipReader(fs, zip_path)

        with pytest.raises(KeyError):
            async with await reader.open_member("nonexistent.txt") as stream:
                async for _ in stream:
                    pass


@pytest.mark.asyncio
@pytest.mark.slow
async def test_read_s3_zip_member() -> None:
    """Test reading a specific member from a ZIP file stored in S3 (public bucket)."""
    zip_url = "s3://slow-tests/swe_bench.eval"
    member_name = "samples/astropy__astropy-14309_epoch_1.json"

    # Use anonymous S3 access for public bucket
    async with AsyncFilesystem() as fs:
        reader = AsyncZipReader(fs, zip_url)

        # Read the member and collect all chunks
        chunks: list[bytes] = []
        async with await reader.open_member(member_name) as stream:
            async for chunk in stream:
                chunks.append(chunk)

        # Verify we got data
        _the_json = json.loads(b"".join(chunks).decode("utf-8"))


@pytest.fixture
def zstd_zip_file(tmp_path: Path) -> Path:
    """Create a test ZIP file compressed with zstd (method 93)."""
    zip_path = tmp_path / "zstd_test.zip"

    # zipfile-zstd adds ZIP_ZSTANDARD (93) to zipfile
    # Use getattr to satisfy both mypy and runtime
    zstd_compression: int = getattr(zipfile, "ZIP_ZSTANDARD", 93)
    with zipfile.ZipFile(zip_path, "w", compression=zstd_compression) as zf:
        zf.writestr("test.json", json.dumps({"message": "hello zstd"}))

    return zip_path


@pytest.mark.asyncio
async def test_read_zstd_compressed_member(zstd_zip_file: Path) -> None:
    """Test reading a zstd-compressed member from a ZIP file."""
    zip_path = str(zstd_zip_file)

    async with AsyncFilesystem() as fs:
        reader = AsyncZipReader(fs, zip_path)

        # Verify the entry is zstd-compressed (method 93)
        entry = await reader.get_member_entry("test.json")
        assert entry.compression_method == 93

        # Read the test.json member
        chunks = []
        async with await reader.open_member("test.json") as stream:
            async for chunk in stream:
                chunks.append(chunk)

        # Verify content was decompressed correctly
        data = b"".join(chunks)
        parsed = json.loads(data.decode("utf-8"))
        assert parsed["message"] == "hello zstd"


@pytest.mark.asyncio
async def test_deflate_compress_stream() -> None:
    """Test that _DeflateCompressStream correctly deflate-compresses data."""
    original_data = b"The quick brown fox jumps over the lazy dog. " * 100

    async def source_iterator() -> "AsyncIterator[bytes]":
        """Yield the original data in chunks."""
        chunk_size = 1024
        for i in range(0, len(original_data), chunk_size):
            yield original_data[i : i + chunk_size]

    # Compress with _DeflateCompressStream
    compressed_chunks = []
    compress_stream = _DeflateCompressStream(source_iterator())
    try:
        async for chunk in compress_stream:
            compressed_chunks.append(chunk)
    finally:
        await compress_stream.aclose()

    compressed_data = b"".join(compressed_chunks)

    # Verify compressed data is smaller than original
    assert len(compressed_data) < len(original_data)

    # Verify we can decompress with zlib (raw DEFLATE, wbits=-15)
    decompressor = zlib.decompressobj(-15)
    decompressed = decompressor.decompress(compressed_data) + decompressor.flush()
    assert decompressed == original_data
