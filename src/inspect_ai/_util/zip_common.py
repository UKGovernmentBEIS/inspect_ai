from dataclasses import dataclass
from enum import IntEnum


class ZipCompressionMethod(IntEnum):
    """ZIP compression method constants.

    See: https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT
      '4.4.5 compression method:'
    """

    STORED = 0  # No compression
    DEFLATE = 8  # DEFLATE
    ZSTD = 93  # Zstandard


@dataclass
class ZipEntry:
    """Metadata for a single ZIP archive member."""

    filename: str
    compression_method: ZipCompressionMethod
    compressed_size: int
    uncompressed_size: int
    local_header_offset: int
