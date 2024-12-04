import os
import struct
import zlib
from dataclasses import dataclass
from typing import Any, BinaryIO, Dict, Iterable, List, Tuple
from zipfile import ZIP_DEFLATED

ZIP_COMPRESSION_METHOD = ZIP_DEFLATED
ZIP_COMPRESSION_LEVEL = 5


@dataclass
class ZipEntry:
    """Contains metadata about a file in the ZIP archive"""

    filename: str
    compressed_size: int
    uncompressed_size: int
    local_header_offset: int
    crc32: int
    compression_method: int
    general_purpose_flag: int
    central_directory_data: bytes


class ZipDirectory:
    def __init__(self) -> None:
        self.entries: Dict[str, ZipEntry] = {}
        self.cd_offset: int = 0
        self.cd_size: int = 0


class ZipReader(ZipDirectory):
    ZIP_HEADER: bytes = b"PK\x03\x04"
    CENTRAL_DIR_HEADER: bytes = b"PK\x01\x02"
    END_CENTRAL_DIR: bytes = b"PK\x05\x06"

    def __init__(self, file_obj: BinaryIO):
        super().__init__()
        self.file = file_obj
        self._load_central_directory()

    def _read_exactly(self, size: int) -> bytes:
        """Read exactly size bytes from file."""
        data: bytes = self.file.read(size)
        if len(data) < size:
            raise ValueError(f"Failed to read {size} bytes")
        return data

    def _find_end_central_dir(self) -> Tuple[int, bytes]:
        """Find the end of central directory record."""
        file_size: int = self.file.seek(0, os.SEEK_END)
        if file_size < 22:
            raise ValueError("File too small to be a ZIP file")

        # Search for the end of central directory signature
        MAX_COMMENT_SIZE = 65535
        search_size = min(MAX_COMMENT_SIZE + 22, file_size)

        self.file.seek(file_size - search_size)
        search_data = self.file.read(search_size)

        pos = search_data.rfind(self.END_CENTRAL_DIR)
        if pos == -1:
            raise ValueError("Could not find end of central directory")

        eocd_pos = file_size - search_size + pos
        self.file.seek(eocd_pos)
        eocd_data = self._read_exactly(22)

        return eocd_pos, eocd_data

    def _load_central_directory(self) -> None:
        """Load central directory entries into memory."""
        eocd_pos, eocd_data = self._find_end_central_dir()

        num_entries: int = struct.unpack("<H", eocd_data[8:10])[0]
        self.cd_size = struct.unpack("<L", eocd_data[12:16])[0]
        self.cd_offset = struct.unpack("<L", eocd_data[16:20])[0]

        self.file.seek(self.cd_offset)

        for _ in range(num_entries):
            # Read fixed-length portion
            entry_data = self._read_exactly(46)
            if not entry_data.startswith(self.CENTRAL_DIR_HEADER):
                raise ValueError("Invalid central directory entry")

            # Read variable-length fields
            name_length = struct.unpack("<H", entry_data[28:30])[0]
            extra_length = struct.unpack("<H", entry_data[30:32])[0]
            comment_length = struct.unpack("<H", entry_data[32:34])[0]

            filename = self._read_exactly(name_length).decode("utf-8")
            extra = self._read_exactly(extra_length)
            comment = self._read_exactly(comment_length)

            # Store entry metadata
            self.entries[filename] = ZipEntry(
                filename=filename,
                compressed_size=struct.unpack("<L", entry_data[20:24])[0],
                uncompressed_size=struct.unpack("<L", entry_data[24:28])[0],
                local_header_offset=struct.unpack("<L", entry_data[42:46])[0],
                crc32=struct.unpack("<L", entry_data[16:20])[0],
                compression_method=struct.unpack("<H", entry_data[10:12])[0],
                general_purpose_flag=struct.unpack("<H", entry_data[8:10])[0],
                central_directory_data=entry_data
                + filename.encode("utf-8")
                + extra
                + comment,
            )

    def filenames(self) -> Iterable[str]:
        return self.entries.keys()

    def read(self, filename: str) -> bytes:
        """Read a file from the ZIP archive."""
        if filename not in self.entries:
            raise KeyError(f"File {filename} not found in ZIP")

        entry = self.entries[filename]
        self.file.seek(entry.local_header_offset)

        # Read and validate local file header
        header = self._read_exactly(30)
        if not header.startswith(self.ZIP_HEADER):
            raise ValueError("Invalid local file header")

        name_length = struct.unpack("<H", header[26:28])[0]
        extra_length = struct.unpack("<H", header[28:30])[0]

        # Skip filename and extra field
        self.file.seek(entry.local_header_offset + 30 + name_length + extra_length)

        # Read compressed data
        compressed_data = self._read_exactly(entry.compressed_size)

        if entry.compression_method == 0:  # No compression
            return compressed_data
        elif entry.compression_method == 8:  # Deflate
            return zlib.decompress(compressed_data, -15)
        else:
            raise ValueError(
                f"Unsupported compression method: {entry.compression_method}"
            )


class ZipWriter:
    def __init__(self, file_obj: BinaryIO, directory: ZipDirectory):
        self.file = file_obj
        self.directory = directory
        self.added_entries: List[ZipEntry] = []

    def write(self, filename: str, data: bytes) -> None:
        """Append a new file to the ZIP archive."""
        # If this is the first append, seek to end of last file and truncate
        if not self.added_entries:
            self.file.seek(self.directory.cd_offset)
            self.file.truncate()

        local_header_offset = self.file.tell()

        # Compress the data
        compressor = zlib.compressobj(
            level=ZIP_COMPRESSION_LEVEL, method=ZIP_COMPRESSION_METHOD, wbits=-15
        )
        compressed_data = compressor.compress(data) + compressor.flush()
        crc = zlib.crc32(data)

        general_purpose_flag = 0x0800  # UTF-8 encoding
        encoded_filename = filename.encode("utf-8")

        # Write local file header
        header = (
            ZipReader.ZIP_HEADER
            + struct.pack("<H", 20)  # Version needed
            + struct.pack("<H", general_purpose_flag)
            + struct.pack("<H", 8)  # Compression method
            + struct.pack("<H", 0)  # Time
            + struct.pack("<H", 0)  # Date
            + struct.pack("<L", crc)
            + struct.pack("<L", len(compressed_data))
            + struct.pack("<L", len(data))
            + struct.pack("<H", len(encoded_filename))
            + struct.pack("<H", 0)  # Extra field length
            + encoded_filename
        )

        self.file.write(header)
        self.file.write(compressed_data)

        # Create central directory entry
        cd_entry = (
            ZipReader.CENTRAL_DIR_HEADER
            + struct.pack("<H", 20)  # Version made by
            + struct.pack("<H", 20)  # Version needed
            + struct.pack("<H", general_purpose_flag)
            + struct.pack("<H", 8)  # Compression method
            + struct.pack("<H", 0)  # Time
            + struct.pack("<H", 0)  # Date
            + struct.pack("<L", crc)
            + struct.pack("<L", len(compressed_data))
            + struct.pack("<L", len(data))
            + struct.pack("<H", len(encoded_filename))
            + struct.pack("<H", 0)  # Extra field length
            + struct.pack("<H", 0)  # Comment length
            + struct.pack("<H", 0)  # Disk number start
            + struct.pack("<H", 0)  # Internal attributes
            + struct.pack("<L", 0)  # External attributes
            + struct.pack("<L", local_header_offset)
            + encoded_filename
        )

        # Store entry for later writing to central directory
        entry = ZipEntry(
            filename=filename,
            compressed_size=len(compressed_data),
            uncompressed_size=len(data),
            local_header_offset=local_header_offset,
            crc32=crc,
            compression_method=8,
            general_purpose_flag=general_purpose_flag,
            central_directory_data=cd_entry,
        )
        self.added_entries.append(entry)

    def __enter__(self) -> "ZipWriter":
        return self

    def __exit__(self, *execinfo: Any) -> None:
        """Write the final central directory after all files have been appended."""
        cd_offset = self.file.tell()

        # Write existing entries from reader
        for entry in self.directory.entries.values():
            self.file.write(entry.central_directory_data)

        # Write new entries
        for entry in self.added_entries:
            self.file.write(entry.central_directory_data)

        # Calculate total entries and central directory size
        total_entries = len(self.directory.entries) + len(self.added_entries)
        cd_size = self.file.tell() - cd_offset

        # Write end of central directory record
        eocd = (
            ZipReader.END_CENTRAL_DIR
            + struct.pack("<H", 0)  # Disk number
            + struct.pack("<H", 0)  # Disk with central directory
            + struct.pack("<H", total_entries)
            + struct.pack("<H", total_entries)
            + struct.pack("<L", cd_size)
            + struct.pack("<L", cd_offset)
            + struct.pack("<H", 0)  # Comment length
        )
        self.file.write(eocd)
        self.file.flush()
