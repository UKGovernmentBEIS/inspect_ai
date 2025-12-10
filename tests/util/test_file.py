import os

import pytest

from inspect_ai._util.file import (
    absolute_file_path,
    basename,
    dirname,
    filesystem,
    strip_trailing_sep,
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

    # Query params (e.g. S3 versionId) should be stripped
    assert basename("s3://my-bucket/myfile.eval?versionId=abc123") == "myfile.eval"
    assert basename("s3://my-bucket/mydir/myfile.log?versionId=abc123") == "myfile.log"


def test_dirname():
    assert dirname("s3://my-bucket/myfile.log") == "s3://my-bucket"
    assert dirname("s3://my-bucket/mydir/myfile.log") == "s3://my-bucket/mydir"
    assert dirname("/opt/files/myfile.log") == "/opt/files"

    # Query params should be stripped
    assert dirname("s3://my-bucket/myfile.eval?versionId=abc123") == "s3://my-bucket"
    assert (
        dirname("s3://my-bucket/mydir/myfile.eval?versionId=abc123")
        == "s3://my-bucket/mydir"
    )


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
