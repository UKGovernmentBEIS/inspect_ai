"""Async ZIP file reader with streaming decompression support.

Supports reading individual members from large ZIP archives (including ZIP64)
stored locally or remotely (e.g., S3) using async range requests.
"""

from __future__ import annotations

import struct
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import anyio
from typing_extensions import Self

from inspect_ai._util.asyncfiles import AsyncFilesystem

from .compression_transcoding import CompressedToUncompressedStream
from .zip_common import ZipCompressionMethod, ZipEntry

# Default chunk size for streaming compressed data (1MB)
DEFAULT_CHUNK_SIZE = 1024 * 1024


@dataclass
class CentralDirectoryLocation:
    """Location and raw data needed to parse the central directory."""

    offset: int
    size: int
    tail: bytes
    tail_start: int
    etag: str | None = None


@dataclass
class CentralDirectory:
    """Parsed central directory with entries and file metadata."""

    entries: list[ZipEntry]
    etag: str | None = None


# This is an exploratory cache of central directories keyed by filename
# It's not production ready for a variety of reasons.
# The file may have changed since the last read:
#   - for some filesystems, we could add the etag into the key
#   - we could fall back to modified time??
# I'm still not confident about the relationship between this class
# and the filesystem class.

central_directories_cache: dict[str, CentralDirectory] = {}
_filename_locks: dict[str, anyio.Lock] = {}
_locks_lock = anyio.Lock()


# source_cm was never entered, nothing to close


async def _get_central_directory(
    filesystem: AsyncFilesystem, filename: str
) -> CentralDirectory:
    # Fast path: check cache without locks
    if (cd := central_directories_cache.get(filename, None)) is not None:
        return cd

    # Get or create the lock for this specific filename
    async with _locks_lock:
        if filename not in _filename_locks:
            _filename_locks[filename] = anyio.Lock()
        file_lock = _filename_locks[filename]

    # Acquire the per-filename lock
    async with file_lock:
        # Double-check after acquiring lock
        if (cd := central_directories_cache.get(filename, None)) is not None:
            return cd

        cd = await _parse_central_directory(filesystem, filename)
        central_directories_cache[filename] = cd
        return cd


async def _find_central_directory(
    filesystem: AsyncFilesystem, filename: str
) -> CentralDirectoryLocation:
    """Locate and parse the central directory metadata.

    Uses a suffix range request to avoid a separate HEAD for the file size.

    Returns:
        CentralDirectoryLocation with offset, size, tail data, and etag.

    Raises:
        ValueError: If EOCD signature not found or ZIP64 structure is corrupt
    """
    suffix = await filesystem.read_file_suffix(filename, 65536)
    tail = suffix.data
    tail_start = suffix.file_size - len(tail)

    # Search backward for EOCD signature
    eocd_sig = b"PK\x05\x06"
    idx = tail.rfind(eocd_sig)
    if idx == -1:
        raise ValueError("EOCD not found")

    # Parse 32-bit EOCD fields
    (
        _disk_no,
        _cd_start_disk,
        _num_entries_disk,
        _num_entries_total,
        cd_size_32,
        cd_offset_32,
        _comment_len,
    ) = struct.unpack_from("<HHHHIIH", tail, idx + 4)

    cd_offset = cd_offset_32
    cd_size = cd_size_32

    # Check for ZIP64 EOCD locator
    loc_sig = b"PK\x06\x07"
    loc_idx = tail.rfind(loc_sig, 0, idx)
    if loc_idx != -1:
        # Parse ZIP64 EOCD locator to get EOCD64 offset
        fields = struct.unpack_from("<IQI", tail, loc_idx + 4)
        eocd64_offset = fields[1]

        # Read ZIP64 EOCD (reuse tail if possible)
        if eocd64_offset >= tail_start:
            rel = eocd64_offset - tail_start
            eocd64_data = tail[rel : rel + 56]
        else:
            eocd64_data = await filesystem.read_file_bytes_fully(
                filename, eocd64_offset, eocd64_offset + 56
            )

        # Verify ZIP64 EOCD signature
        eocd64_sig = b"PK\x06\x06"
        if not eocd64_data.startswith(eocd64_sig):
            raise ValueError("Corrupt ZIP64 structure")

        # Parse ZIP64 central directory size and offset
        cd_size, cd_offset = struct.unpack_from("<QQ", eocd64_data, 40)

    return CentralDirectoryLocation(cd_offset, cd_size, tail, tail_start, suffix.etag)


async def _parse_central_directory(
    filesystem: AsyncFilesystem, filename: str
) -> CentralDirectory:
    """Parse the central directory and return all entries.

    Returns:
        CentralDirectory with entries and etag.
    """
    cd_loc = await _find_central_directory(filesystem, filename)

    # Reuse the tail buffer if the central directory falls within it
    if cd_loc.offset >= cd_loc.tail_start:
        rel = cd_loc.offset - cd_loc.tail_start
        buf = cd_loc.tail[rel : rel + cd_loc.size]
    else:
        buf = await filesystem.read_file_bytes_fully(
            filename, cd_loc.offset, cd_loc.offset + cd_loc.size
        )

    entries = []
    pos = 0
    sig = b"PK\x01\x02"

    while pos < len(buf):
        if pos + 4 > len(buf) or not buf[pos : pos + 4] == sig:
            break

        # Parse central directory file header (46 bytes)
        (
            _ver_made,
            _ver_needed,
            _flags,
            method,
            _time,
            _date,
            _crc,
            compressed_size,
            uncompressed_size,
            name_len,
            extra_len,
            comment_len,
            _disk,
            _int_attr,
            _ext_attr,
            local_header_off,
        ) = struct.unpack_from("<HHHHHHIIIHHHHHII", buf, pos + 4)

        # Extract filename
        name_start = pos + 46
        name = buf[name_start : name_start + name_len].decode("utf-8")

        # Extract extra field
        extra_start = name_start + name_len
        extra = buf[extra_start : extra_start + extra_len]

        # Handle ZIP64 extra fields (0x0001)
        if (
            compressed_size == 0xFFFFFFFF
            or uncompressed_size == 0xFFFFFFFF
            or local_header_off == 0xFFFFFFFF
        ):
            i = 0
            while i + 4 <= len(extra):
                header_id, data_size = struct.unpack_from("<HH", extra, i)
                i += 4
                if header_id == 0x0001:  # ZIP64 extended information
                    # Parse available 64-bit fields in order
                    num_fields = data_size // 8
                    if num_fields > 0:
                        fields = struct.unpack_from(f"<{num_fields}Q", extra, i)
                        field_idx = 0
                        if uncompressed_size == 0xFFFFFFFF and field_idx < len(fields):
                            uncompressed_size = fields[field_idx]
                            field_idx += 1
                        if compressed_size == 0xFFFFFFFF and field_idx < len(fields):
                            compressed_size = fields[field_idx]
                            field_idx += 1
                        if local_header_off == 0xFFFFFFFF and field_idx < len(fields):
                            local_header_off = fields[field_idx]
                    break
                i += data_size

        entries.append(
            ZipEntry(
                name,
                method,
                compressed_size,
                uncompressed_size,
                local_header_off,
            )
        )
        pos += 46 + name_len + extra_len + comment_len

    return CentralDirectory(entries, cd_loc.etag)


class _ZipMemberBytes:
    """AsyncIterable + AsyncContextManager for zip member data.

    Each iteration creates a fresh decompression stream, enabling re-reads:

        async with await zip_reader.open_member("file.json") as member:
            async for chunk in member:  # first read
                process(chunk)

            async for chunk in member:  # second read (e.g., retry on error)
                process_differently(chunk)
    """

    def __init__(
        self,
        filesystem: AsyncFilesystem,
        filename: str,
        range_and_method: tuple[int, int, ZipCompressionMethod],
        *,
        raw: bool = False,
    ):
        self._filesystem = filesystem
        self._filename = filename
        self._offset, self._end, self._method = range_and_method
        self._raw = raw
        self._active_streams: set[CompressedToUncompressedStream] = set()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        byte_stream = await self._filesystem.read_file_bytes(
            self._filename, self._offset, self._end
        )

        if self._raw or self._method == ZipCompressionMethod.STORED:
            # Pass through raw bytes directly - no decompression needed
            try:
                async for chunk in byte_stream:
                    yield chunk
            finally:
                await byte_stream.aclose()
        else:
            # Decompress using the appropriate method
            stream = CompressedToUncompressedStream(byte_stream, self._method)
            self._active_streams.add(stream)
            try:
                async for chunk in stream:
                    yield chunk
            finally:
                self._active_streams.discard(stream)
                await stream.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        for stream in list(self._active_streams):
            await stream.aclose()
        self._active_streams.clear()


class AsyncZipReader:
    """Async ZIP reader that supports streaming decompression of individual members.

    This reader minimizes data transfer by using range requests to read only
    the necessary portions of the ZIP file (central directory + requested member).
    Supports ZIP64 archives and streams decompressed data incrementally.

    For example:

        async with AsyncFilesystem() as fs:
            reader = AsyncZipReader(fs, "s3://bucket/large-archive.zip")
            async with await reader.open_member("trajectory_001.json") as iterable:
                async for chunk in iterable:
                    process(chunk)
    """

    def __init__(
        self,
        filesystem: AsyncFilesystem,
        filename: str,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ):
        """Initialize the async ZIP reader.

        Args:
            filesystem: AsyncFilesystem instance for reading files
            filename: Path or URL to ZIP file (local path or s3:// URL)
            chunk_size: Size of chunks for streaming compressed data

        Raises:
            ValueError: If filename is empty or None
        """
        if not filename:
            raise ValueError("filename must not be empty")
        self._filesystem = filesystem
        self._filename = filename
        self._chunk_size = chunk_size
        self._central_directory: CentralDirectory | None = None

    @property
    def etag(self) -> str | None:
        """ETag from the S3 response used to read the central directory."""
        return self._central_directory.etag if self._central_directory else None

    async def entries(self) -> CentralDirectory:
        """Load and cache the central directory."""
        if self._central_directory is None:
            self._central_directory = await _get_central_directory(
                self._filesystem, self._filename
            )
        return self._central_directory

    async def get_member_entry(self, member_name: str) -> ZipEntry:
        cd = await self.entries()
        entry = next((e for e in cd.entries if e.filename == member_name), None)
        if entry is None:
            raise KeyError(member_name)
        return entry

    async def open_member_raw(self, member: str | ZipEntry) -> _ZipMemberBytes:
        """Open a ZIP member for streaming its raw (likely compressed) bytes.

        Unlike open_member(), this does NOT decompress the data. Use this when
        you want to pass through the raw bytes (e.g., for HTTP streaming with
        Content-Encoding: deflate).

        Returns a "cold" iterable - the stream is not opened until iteration.

        Args:
            member: Name or ZipEntry of the member file within the archive

        Returns:
            _ZipMemberBytes that yields raw bytes (may be compressed)
        """
        return _ZipMemberBytes(
            self._filesystem,
            self._filename,
            await self._get_member_range_and_method(member),
            raw=True,
        )

    async def open_member(self, member: str | ZipEntry) -> _ZipMemberBytes:
        """Open a ZIP member and stream its decompressed contents.

        Must be used as an async context manager to ensure proper cleanup.
        Can be re-iterated within the same context manager scope.

        Args:
            member: Name or ZipEntry of the member file within the archive

        Returns:
            AsyncIterable of decompressed data chunks

        Raises:
            KeyError: If member_name not found in archive
            NotImplementedError: If compression method is not supported

        Example:
            async with await zip_reader.open_member("file.json") as stream:
                async for chunk in stream:
                    process(chunk)
        """
        return _ZipMemberBytes(
            self._filesystem,
            self._filename,
            await self._get_member_range_and_method(member),
        )

    async def read_member_fully(self, member: str | ZipEntry) -> bytes:
        """Read a member's decompressed content fully into memory.

        Reads the local file header and compressed data in a single request,
        then decompresses. More efficient than ``open_member`` for small members
        because it avoids a separate request for the local file header.

        Args:
            member: Name or ZipEntry of the member file within the archive

        Returns:
            Decompressed member content as bytes
        """
        entry = (
            member
            if isinstance(member, ZipEntry)
            else await self.get_member_entry(member)
        )

        # Estimate variable header size from central directory filename
        # plus generous padding for the extra field
        name_len_estimate = len(entry.filename.encode("utf-8"))
        variable_header_padding = name_len_estimate + 256

        # Read local header + compressed data in one request
        read_start = entry.local_header_offset
        read_end = read_start + 30 + variable_header_padding + entry.compressed_size
        buf = await self._filesystem.read_file_bytes_fully(
            self._filename, read_start, read_end
        )

        # Parse local header to find exact data offset
        _, _, _, _, _, _, _, _, _, name_len, extra_len = struct.unpack_from(
            "<4sHHHHHIIIHH", buf
        )
        data_start = 30 + name_len + extra_len

        if data_start + entry.compressed_size <= len(buf):
            compressed_data = buf[data_start : data_start + entry.compressed_size]
        else:
            # Variable header was larger than estimated; fall back to separate read
            abs_data_start = read_start + data_start
            compressed_data = await self._filesystem.read_file_bytes_fully(
                self._filename,
                abs_data_start,
                abs_data_start + entry.compressed_size,
            )

        if entry.compression_method == ZipCompressionMethod.STORED:
            return compressed_data
        elif entry.compression_method == ZipCompressionMethod.DEFLATE:
            import zlib

            return zlib.decompress(compressed_data, -15)
        elif entry.compression_method == ZipCompressionMethod.ZSTD:
            import zstandard

            dctx = zstandard.ZstdDecompressor()
            return dctx.decompress(compressed_data)
        else:
            raise NotImplementedError(
                f"Unsupported compression method: {entry.compression_method}"
            )

    async def _get_member_range_and_method(
        self, member: str | ZipEntry
    ) -> tuple[int, int, ZipCompressionMethod]:
        entry = (
            member
            if isinstance(member, ZipEntry)
            else await self.get_member_entry(member)
        )

        # Read local file header to determine actual data offset
        local_header = await self._filesystem.read_file_bytes_fully(
            self._filename,
            entry.local_header_offset,
            entry.local_header_offset + 30,
        )
        _, _, _, _, _, _, _, _, _, name_len, extra_len = struct.unpack_from(
            "<4sHHHHHIIIHH", local_header
        )

        data_offset = entry.local_header_offset + 30 + name_len + extra_len
        data_end = data_offset + entry.compressed_size
        return (data_offset, data_end, entry.compression_method)
