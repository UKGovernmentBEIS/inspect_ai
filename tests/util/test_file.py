import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from inspect_ai._util.file import (
    absolute_file_path,
    basename,
    cleanup_s3_sessions,
    filesystem,
    strip_trailing_sep,
    to_uri,
)


def test_basename():
    MYFILE = "myfile.log"
    assert basename(f"s3://my-bucket/{MYFILE}") == MYFILE
    assert basename(f"/opt/files/{MYFILE}") == MYFILE
    assert basename(f"C:\\Documents\\{MYFILE}") == MYFILE

    MYDIR = "mydir"
    assert basename(f"s3://my-bucket/{MYDIR}") == MYDIR
    assert basename(f"s3://my-bucket/{MYDIR}/") == MYDIR
    assert basename(f"/opt/files/{MYDIR}") == MYDIR
    assert basename(f"/opt/files/{MYDIR}/") == MYDIR
    assert basename(f"C:\\Documents\\{MYDIR}") == MYDIR
    assert basename(f"C:\\Documents\\{MYDIR}\\") == MYDIR


def test_filesystem_file_info():
    memory_filesystem = filesystem("memory://")
    memory_filesystem.touch("test_file")
    info = memory_filesystem.info("test_file")
    assert info.name == "memory:///test_file"
    assert info.size == 0


@pytest.mark.parametrize(
    "path,expected",
    [
        # Root preserved
        ("/", "/"),
        # Exactly // preserved per POSIX
        ("//", "//"),
        # 3+ slashes collapse to root
        ("///", "/"),
        ("////", "/"),
        # Trailing slashes stripped
        ("/foo/", "/foo"),
        ("/foo//", "/foo"),
        ("foo/", "foo"),
        ("foo//", "foo"),
        # No trailing slash unchanged
        ("/foo", "/foo"),
        ("foo", "foo"),
        ("/foo/bar", "/foo/bar"),
    ],
)
def test_strip_trailing_sep(path: str, expected: str) -> None:
    assert strip_trailing_sep(path) == expected


@pytest.mark.parametrize(
    "path,expected_suffix",
    [
        # Trailing separators stripped from absolute paths
        ("/foo/bar/", "/foo/bar"),
        ("/foo/bar//", "/foo/bar"),
        # Root preserved
        ("/", "/"),
        # Scheme paths stripped but not resolved
        ("s3://bucket/key/", "s3://bucket/key"),
        ("s3://bucket/key", "s3://bucket/key"),
        # Already clean absolute path unchanged
        ("/foo/bar", "/foo/bar"),
    ],
)
def test_absolute_file_path_strips_trailing_sep(
    path: str, expected_suffix: str
) -> None:
    assert absolute_file_path(path) == expected_suffix


def test_absolute_file_path_resolves_relative() -> None:
    result = absolute_file_path("somedir/")
    assert os.path.isabs(result)
    assert result == os.path.join(os.getcwd(), "somedir")
    assert not result.endswith("/")


@pytest.mark.parametrize(
    "input_path,expected_suffix",
    [
        # Raw local path with @ should not encode it
        ("/path/to/noop.py@noop.eval", "file:///path/to/noop.py@noop.eval"),
        # Already a file:// URI with @ should pass through unchanged
        ("file:///path/to/noop.py@noop.eval", "file:///path/to/noop.py@noop.eval"),
        # S3 URIs should pass through unchanged
        ("s3://bucket/file.eval", "s3://bucket/file.eval"),
        # Plain local path without special characters
        ("/tmp/simple.eval", "file:///tmp/simple.eval"),
    ],
)
def test_to_uri(input_path: str, expected_suffix: str) -> None:
    result = to_uri(input_path)
    assert result == expected_suffix


def test_to_uri_idempotent() -> None:
    """to_uri should produce the same result when applied twice."""
    path = "/path/to/noop.py@noop.eval"
    assert to_uri(to_uri(path)) == to_uri(path)


async def test_cleanup_s3_sessions_no_instances() -> None:
    """cleanup_s3_sessions is a no-op when there are no cached instances."""
    with patch("inspect_ai._util.file.S3FileSystem") as mock_s3fs:
        mock_s3fs._cache = {}
        await cleanup_s3_sessions()
        mock_s3fs.clear_instance_cache.assert_not_called()


async def test_cleanup_s3_sessions_closes_creator() -> None:
    """cleanup_s3_sessions calls __aexit__ on each cached instance's _s3creator."""
    mock_creator = AsyncMock()
    mock_instance = MagicMock()
    mock_instance._s3creator = mock_creator

    with patch("inspect_ai._util.file.S3FileSystem") as mock_s3fs:
        mock_s3fs._cache = {"key": mock_instance}
        await cleanup_s3_sessions()

        mock_creator.__aexit__.assert_awaited_once_with(None, None, None)
        mock_s3fs.clear_instance_cache.assert_called_once()


async def test_cleanup_s3_sessions_handles_errors() -> None:
    """cleanup_s3_sessions continues if __aexit__ raises."""
    mock_creator = AsyncMock()
    mock_creator.__aexit__.side_effect = OSError("connection closed")
    mock_instance = MagicMock()
    mock_instance._s3creator = mock_creator

    mock_creator2 = AsyncMock()
    mock_instance2 = MagicMock()
    mock_instance2._s3creator = mock_creator2

    with patch("inspect_ai._util.file.S3FileSystem") as mock_s3fs:
        mock_s3fs._cache = {"k1": mock_instance, "k2": mock_instance2}
        await cleanup_s3_sessions()

        mock_creator2.__aexit__.assert_awaited_once_with(None, None, None)
        mock_s3fs.clear_instance_cache.assert_called_once()


async def test_cleanup_s3_sessions_no_s3creator() -> None:
    """cleanup_s3_sessions skips instances without _s3creator."""
    mock_instance = MagicMock(spec=[])

    with patch("inspect_ai._util.file.S3FileSystem") as mock_s3fs:
        mock_s3fs._cache = {"key": mock_instance}
        await cleanup_s3_sessions()

        mock_s3fs.clear_instance_cache.assert_called_once()
