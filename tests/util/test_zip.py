import io
import os
import zipfile
from typing import Dict

import pytest

from inspect_ai._util.zip import ZipReader, ZipWriter


@pytest.fixture
def sample_data() -> Dict[str, bytes]:
    """Fixture providing sample file data for testing."""
    return {
        "test1.txt": b"Hello, World!",
        "test2.txt": b"This is another test file.",
        "empty.txt": b"",
        "binary.dat": bytes(range(256)),
    }


@pytest.fixture
def sample_zip(sample_data: Dict[str, bytes]) -> io.BytesIO:
    """Fixture creating a sample ZIP file in memory."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for filename, content in sample_data.items():
            zf.writestr(filename, content)
    buffer.seek(0)
    return buffer


def test_init_empty_zip():
    """Test initializing with an empty ZIP file."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w"):
        pass
    buffer.seek(0)

    reader = ZipReader(buffer)

    # For an empty ZIP file:
    assert len(reader.entries) == 0  # No files
    assert reader.cd_size == 0  # Central directory is empty

    # Verify we can read the file size
    buffer.seek(0, os.SEEK_END)
    file_size = buffer.tell()

    # An empty ZIP file should contain at least the EOCD record (22 bytes)
    assert file_size >= 22

    # The EOCD record should be at the end
    buffer.seek(-22, os.SEEK_END)
    eocd_data = buffer.read()
    assert eocd_data.startswith(ZipReader.END_CENTRAL_DIR)

    # Verify EOCD record contents
    assert len(eocd_data) == 22
    num_entries = int.from_bytes(eocd_data[8:10], "little")
    assert num_entries == 0  # No entries


def test_init_invalid_zip():
    """Test initializing with invalid ZIP data."""
    buffer = io.BytesIO(b"Not a ZIP file")
    with pytest.raises(ValueError):
        ZipReader(buffer)


def test_read_existing_files(sample_zip: io.BytesIO, sample_data: Dict[str, bytes]):
    """Test reading files from a ZIP archive."""
    reader = ZipReader(sample_zip)

    # Verify all files are listed in entries
    assert set(reader.entries.keys()) == set(sample_data.keys())

    # Read and verify each file's contents
    for filename, expected_content in sample_data.items():
        content = reader.read(filename)
        assert content == expected_content

        # Verify file metadata
        entry = reader.entries[filename]
        assert entry.filename == filename
        assert entry.uncompressed_size == len(expected_content)
        assert entry.compression_method in (0, 8)  # Store or Deflate


def test_read_nonexistent_file(sample_zip: io.BytesIO):
    """Test reading a file that doesn't exist in the archive."""
    reader = ZipReader(sample_zip)
    with pytest.raises(KeyError):
        reader.read("nonexistent.txt")


def test_large_filename(tmp_path):
    """Test handling files with long names."""
    long_filename = "a" * 1000 + ".txt"
    content = b"test content"

    # Create ZIP file with a long filename
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(long_filename, content)

    with open(zip_path, "rb") as f:
        reader = ZipReader(f)
        assert long_filename in reader.entries
        assert reader.read(long_filename) == content


def test_append_single_file(sample_zip: io.BytesIO, sample_data: Dict[str, bytes]):
    """Test appending a single file to an existing archive."""
    # Create reader and writer
    reader = ZipReader(sample_zip)
    with ZipWriter(sample_zip, reader) as writer:
        # Append new file
        new_filename = "new_file.txt"
        new_content = b"New file content"
        writer.write(new_filename, new_content)

    # Verify the result
    sample_zip.seek(0)
    with zipfile.ZipFile(sample_zip) as zf:
        # Check all original files are present
        for filename, content in sample_data.items():
            assert zf.read(filename) == content

        # Check new file is present
        assert zf.read(new_filename) == new_content


def test_append_multiple_files(sample_zip: io.BytesIO):
    """Test appending multiple files to an existing archive."""
    new_files = {
        "new1.txt": b"Content 1",
        "new2.txt": b"Content 2",
        "new3.txt": b"Content 3",
    }

    reader = ZipReader(sample_zip)
    with ZipWriter(sample_zip, reader) as writer:
        for filename, content in new_files.items():
            writer.write(filename, content)

    # Verify the result
    sample_zip.seek(0)
    with zipfile.ZipFile(sample_zip) as zf:
        for filename, content in new_files.items():
            assert zf.read(filename) == content


def test_append_empty_file(sample_zip: io.BytesIO):
    """Test appending an empty file."""
    reader = ZipReader(sample_zip)
    with ZipWriter(sample_zip, reader) as writer:
        writer.write("empty_new.txt", b"")

    sample_zip.seek(0)
    with zipfile.ZipFile(sample_zip) as zf:
        assert zf.read("empty_new.txt") == b""


def test_append_large_file(sample_zip: io.BytesIO):
    """Test appending a large file."""
    large_content = b"x" * 1_000_000  # 1MB file

    reader = ZipReader(sample_zip)
    with ZipWriter(sample_zip, reader) as writer:
        writer.write("large.txt", large_content)

    sample_zip.seek(0)
    with zipfile.ZipFile(sample_zip) as zf:
        assert zf.read("large.txt") == large_content


def test_append_binary_data(sample_zip: io.BytesIO):
    """Test appending binary data."""
    binary_data = bytes(range(256))  # All possible byte values

    reader = ZipReader(sample_zip)
    with ZipWriter(sample_zip, reader) as writer:
        writer.write("binary.dat", binary_data)

    sample_zip.seek(0)
    with zipfile.ZipFile(sample_zip) as zf:
        assert zf.read("binary.dat") == binary_data


def test_duplicate_filename(sample_zip: io.BytesIO):
    """Test appending a file with a name that already exists."""
    reader = ZipReader(sample_zip)
    with ZipWriter(sample_zip, reader) as writer:
        writer.write("test1.txt", b"New content")

    # The new content should override the old content
    sample_zip.seek(0)
    with zipfile.ZipFile(sample_zip) as zf:
        assert zf.read("test1.txt") == b"New content"


@pytest.mark.parametrize(
    "filename",
    [
        "unicode_€£¥.txt",
        "path/with/slashes.txt",
        " leading_space.txt",
        "trailing_space.txt ",
        "!@#$%^&*().txt",
    ],
)
def test_special_filenames(sample_zip: io.BytesIO, filename: str):
    """Test appending files with special characters in names."""
    content = b"Special filename test"

    reader = ZipReader(sample_zip)
    with ZipWriter(sample_zip, reader) as writer:
        writer.write(filename, content)

    sample_zip.seek(0)
    with zipfile.ZipFile(sample_zip) as zf:
        assert zf.read(filename) == content


def test_compression_efficiency(sample_zip: io.BytesIO):
    """Test that compression is working effectively."""
    # Create highly compressible data
    data = b"a" * 10000

    reader = ZipReader(sample_zip)
    with ZipWriter(sample_zip, reader) as writer:
        writer.write("compressed.txt", data)

    # Verify compression ratio
    sample_zip.seek(0)
    with zipfile.ZipFile(sample_zip) as zf:
        info = zf.getinfo("compressed.txt")
        assert info.compress_size < info.file_size
        # Compression should achieve at least 90% reduction for this data
        assert info.compress_size < info.file_size * 0.1


def test_end_to_end_workflow(tmp_path):
    """Test complete workflow of creating, reading, and appending to a ZIP file."""
    zip_path = tmp_path / "test.zip"

    # Create initial ZIP file
    initial_files = {
        "file1.txt": b"Initial content 1",
        "file2.txt": b"Initial content 2",
    }
    with zipfile.ZipFile(zip_path, "w") as zf:
        for filename, content in initial_files.items():
            zf.writestr(filename, content)

    # Append new files
    new_files = {"new1.txt": b"New content 1", "new2.txt": b"New content 2"}

    with open(zip_path, "rb+") as f:
        reader = ZipReader(f)
        with ZipWriter(f, reader) as writer:
            for filename, content in new_files.items():
                writer.write(filename, content)

    # Verify final ZIP contents
    with zipfile.ZipFile(zip_path) as zf:
        # Check all original files
        for filename, content in initial_files.items():
            assert zf.read(filename) == content

        # Check all new files
        for filename, content in new_files.items():
            assert zf.read(filename) == content
