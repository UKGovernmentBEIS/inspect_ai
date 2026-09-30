import importlib
import os
import sys
import weakref
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import fsspec  # type: ignore
import fsspec.core  # type: ignore
import pytest
from test_helpers.utils import skip_if_trio

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import (
    HF_FILESYSTEM_REQUIRED_VERSION,
    absolute_file_path,
    basename,
    cleanup_s3_sessions,
    filesystem,
    local_path,
    size_in_mb,
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


def test_is_writeable_strips_trailing_sep():
    # is_writeable builds a "<path><sep><marker>" write-test file. A trailing
    # slash on the path must be stripped first, otherwise the marker path gets a
    # double separator (e.g. "s3://bucket/logs//.inspect_write_test"), which is a
    # malformed key on S3/Azure.
    fs = filesystem("memory://")
    with patch.object(fs, "touch") as mock_touch, patch.object(fs, "rm"):
        fs.is_writeable("mydir/")
    touch_path = mock_touch.call_args[0][0]
    assert f"{fs.fs.sep}{fs.fs.sep}" not in touch_path


@pytest.mark.parametrize(
    "installed_version",
    [HF_FILESYSTEM_REQUIRED_VERSION, "1.6", "1.6.0.post1", "1.6.1", "2.0.0"],
)
def test_hf_filesystem_imports_and_registers_huggingface_hub(
    installed_version: str,
):
    mock_fs = MagicMock()
    hf_filesystem = MagicMock()
    huggingface_hub = SimpleNamespace(
        HfFileSystem=hf_filesystem, __version__=installed_version
    )
    with (
        patch.object(
            importlib,
            "import_module",
            return_value=huggingface_hub,
        ) as import_module,
        patch.object(fsspec, "register_implementation") as register,
        patch.object(
            fsspec.core,
            "url_to_fs",
            return_value=(mock_fs, "buckets/org/bucket/path"),
        ) as url_to_fs,
    ):
        fs = filesystem("hf://buckets/org/bucket/path")

    assert fs.fs is mock_fs
    import_module.assert_called_once_with("huggingface_hub")
    register.assert_called_once_with("hf", hf_filesystem, clobber=True)
    url_to_fs.assert_called_once_with(
        "hf://buckets/org/bucket/path",
        skip_instance_cache=False,
        use_listings_cache=False,
    )


def test_hf_size_in_mb_imports_and_registers_huggingface_hub():
    mock_fs = MagicMock()
    mock_fs.info.return_value = {"size": 2 * 1024 * 1024}
    hf_filesystem = MagicMock()
    huggingface_hub = SimpleNamespace(
        HfFileSystem=hf_filesystem, __version__=HF_FILESYSTEM_REQUIRED_VERSION
    )
    with (
        patch.object(
            importlib,
            "import_module",
            return_value=huggingface_hub,
        ),
        patch.object(fsspec, "register_implementation") as register,
        patch.object(
            fsspec.core,
            "url_to_fs",
            return_value=(mock_fs, "buckets/org/bucket/path"),
        ),
    ):
        size = size_in_mb("hf://buckets/org/bucket/path")

    assert size == 2
    register.assert_called_once_with("hf", hf_filesystem, clobber=True)


def test_hf_size_in_mb_missing_dependency():
    with (
        patch.object(importlib, "import_module", side_effect=ImportError),
        patch.object(fsspec.core, "url_to_fs") as url_to_fs,
    ):
        with pytest.raises(PrerequisiteError) as exc_info:
            size_in_mb("hf://buckets/org/bucket/path")

    assert "huggingface_hub" in str(exc_info.value.message)
    url_to_fs.assert_not_called()


def test_hf_filesystem_missing_dependency():
    with patch.object(importlib, "import_module", side_effect=ImportError):
        with pytest.raises(PrerequisiteError) as exc_info:
            filesystem("hf://buckets/org/bucket/path")

    assert "huggingface_hub" in str(exc_info.value.message)
    assert HF_FILESYSTEM_REQUIRED_VERSION in str(exc_info.value.message)


@pytest.mark.parametrize(
    "installed_version", ["1.5.0", "1.6.0rc0", "1.6.0.dev1", "unknown"]
)
def test_hf_filesystem_old_dependency(installed_version: str):
    huggingface_hub = SimpleNamespace(
        HfFileSystem=MagicMock(), __version__=installed_version
    )
    with (
        patch.object(
            importlib,
            "import_module",
            return_value=huggingface_hub,
        ),
        patch.object(fsspec, "register_implementation") as register,
    ):
        with pytest.raises(PrerequisiteError) as exc_info:
            filesystem("hf://buckets/org/bucket/path")

    assert "Hugging Face Storage Buckets" in str(exc_info.value.message)
    assert installed_version in str(exc_info.value.message)
    assert HF_FILESYSTEM_REQUIRED_VERSION in str(exc_info.value.message)
    register.assert_not_called()


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
        # Hugging Face bucket URIs should pass through unchanged
        (
            "hf://buckets/org/bucket/file.eval",
            "hf://buckets/org/bucket/file.eval",
        ),
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


def test_local_path_round_trips_spaces() -> None:
    """to_uri percent-encodes, so local_path must decode (#5025)."""
    path = "/tmp/logs dir/my eval.eval"
    assert local_path(to_uri(path)) == path


def test_local_path_round_trips_literal_percent() -> None:
    """Literal percent sequence in a filename round trips.

    to_uri encodes the percent itself (%25), so decoding restores the
    original name rather than treating the sequence as an escape.
    """
    path = "/tmp/report%20final.eval"
    assert local_path(to_uri(path)) == path


def test_local_path_decodes_encoded_uri() -> None:
    """Behavior change pinned: an encoded file:// URI now decodes.

    Previously the escapes passed through intact.
    """
    assert local_path("file:///tmp/report%20final.eval") == "/tmp/report final.eval"


def test_local_path_passthrough_non_file() -> None:
    """Non-file:// values are returned untouched, escapes and all."""
    assert local_path("/tmp/plain path.eval") == "/tmp/plain path.eval"
    assert local_path("s3://bucket/key%20name") == "s3://bucket/key%20name"


def test_local_path_idempotent() -> None:
    """Applying local_path twice never double-decodes.

    The first call strips file:// and decodes; its result is a plain path,
    so a second call is a no-op — a %-containing filename can't be decoded
    twice by accidental double application.
    """
    path = "/tmp/report%20final.eval"
    once = local_path(to_uri(path))
    assert local_path(once) == once == path


def test_local_path_is_the_only_file_uri_decoder() -> None:
    """Tripwire: file:// percent-decoding stays centralized in local_path.

    A second decode site consuming log locations would double-decode
    (%2520 -> %20 -> space). If this fails, either route the new code
    through local_path()/to_uri() or extend the allowlist deliberately.
    """
    src = Path(__file__).parent.parent.parent / "src" / "inspect_ai"
    allowed = {
        src / "_util" / "file.py",  # local_path itself
        src / "_util" / "package.py",  # setuptools direct_url.json, separate domain
    }
    offenders = [
        str(f)
        for f in src.rglob("*.py")
        if "url2pathname" in f.read_text(encoding="utf-8") and f not in allowed
    ]
    assert offenders == [], f"new file-URI decode sites: {offenders}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows drive-path form")
def test_local_path_windows_drive() -> None:
    assert local_path("file:///C:/logs/eval%20run.eval") == "C:\\logs\\eval run.eval"


async def test_cleanup_s3_sessions_no_instances() -> None:
    """cleanup_s3_sessions is a no-op when there are no cached instances."""
    with patch("s3fs.S3FileSystem") as mock_s3fs:
        mock_s3fs._cache = {}
        await cleanup_s3_sessions()
        mock_s3fs.clear_instance_cache.assert_not_called()


async def test_cleanup_s3_sessions_closes_creator() -> None:
    """cleanup_s3_sessions calls __aexit__ on each cached instance's _s3creator."""
    mock_creator = AsyncMock()
    mock_instance = MagicMock()
    mock_instance._s3creator = mock_creator

    with patch("s3fs.S3FileSystem") as mock_s3fs:
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

    with patch("s3fs.S3FileSystem") as mock_s3fs:
        mock_s3fs._cache = {"k1": mock_instance, "k2": mock_instance2}
        await cleanup_s3_sessions()

        mock_creator2.__aexit__.assert_awaited_once_with(None, None, None)
        mock_s3fs.clear_instance_cache.assert_called_once()


def _close_session_finalizers(instance: Any) -> list[weakref.finalize]:
    """The s3fs ``close_session`` finalizers still armed on ``instance``."""
    close_session = type(instance).close_session
    finalizers: list[weakref.finalize] = []
    for ref in weakref.getweakrefs(instance):
        finalizer = ref.__callback__
        if isinstance(finalizer, weakref.finalize):
            info = finalizer.peek()
            if info is not None and info[1] is close_session:
                finalizers.append(finalizer)
    return finalizers


@pytest.fixture
def real_s3fs(monkeypatch: pytest.MonkeyPatch) -> Any:
    """An S3FileSystem class with credentials in place; clients are never connected."""
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "unused_id")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "unused_key")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-1")
    S3FileSystem = fsspec.get_filesystem_class("s3")
    S3FileSystem.clear_instance_cache()
    yield S3FileSystem
    S3FileSystem.clear_instance_cache()


@skip_if_trio
async def test_cleanup_s3_sessions_disarms_s3fs_finalizer(real_s3fs: Any) -> None:
    """cleanup_s3_sessions detaches s3fs's GC-time close_session finalizer.

    The finalizer would otherwise exit the already-exited client a second time
    as a bare task on the running loop, failing with "Session was never entered".
    """
    fs = real_s3fs(cache_regions=False)
    await fs.set_session()
    finalizers = _close_session_finalizers(fs)
    assert len(finalizers) == 1 and finalizers[0].alive
    creator = fs._s3creator

    await cleanup_s3_sessions()

    assert _close_session_finalizers(fs) == []
    assert not finalizers[0].alive
    # the creator was exited once; a second exit is what the finalizer would do
    with pytest.raises(AssertionError, match="Session was never entered"):
        await creator.__aexit__(None, None, None)


@skip_if_trio
async def test_cleanup_s3_sessions_keeps_finalizers_of_other_creators(
    real_s3fs: Any,
) -> None:
    """A refreshed session leaves an older creator whose finalizer must stay armed."""
    fs = real_s3fs(cache_regions=False)
    await fs.set_session()
    old_creator = fs._s3creator
    await fs.set_session(refresh=True)
    assert fs._s3creator is not old_creator
    assert len(_close_session_finalizers(fs)) == 2

    await cleanup_s3_sessions()

    remaining = _close_session_finalizers(fs)
    assert len(remaining) == 1
    info = remaining[0].peek()
    assert info is not None and info[2][1] is old_creator
    # the older client is still open and still closes cleanly
    remaining[0].detach()
    await old_creator.__aexit__(None, None, None)


class _FakeS3FileSystem:
    def __init__(self, creator: Any) -> None:
        self._s3creator = creator

    @staticmethod
    def close_session(loop: Any, s3: Any) -> None:
        pass


async def test_cleanup_s3_sessions_keeps_finalizer_when_cancelled() -> None:
    """A close that is cancelled mid-await leaves s3fs's finalizer in place."""
    entered = anyio.Event()

    class BlockingCreator:
        async def __aexit__(self, *exc: Any) -> None:
            entered.set()
            await anyio.sleep_forever()

    creator = BlockingCreator()
    fs = _FakeS3FileSystem(creator)
    finalizer = weakref.finalize(fs, _FakeS3FileSystem.close_session, None, creator)
    try:
        with patch("s3fs.S3FileSystem") as mock_s3fs:
            mock_s3fs._cache = {"key": fs}
            async with anyio.create_task_group() as tg:
                tg.start_soon(cleanup_s3_sessions)
                await entered.wait()
                tg.cancel_scope.cancel()

            assert finalizer.alive
            mock_s3fs.clear_instance_cache.assert_called_once()
    finally:
        finalizer.detach()


async def test_cleanup_s3_sessions_keeps_finalizer_when_close_fails() -> None:
    """A close that raises leaves s3fs's finalizer in place."""
    creator = AsyncMock()
    creator.__aexit__.side_effect = OSError("connection closed")
    fs = _FakeS3FileSystem(creator)
    finalizer = weakref.finalize(fs, _FakeS3FileSystem.close_session, None, creator)
    try:
        with patch("s3fs.S3FileSystem") as mock_s3fs:
            mock_s3fs._cache = {"key": fs}
            await cleanup_s3_sessions()

            assert finalizer.alive
            mock_s3fs.clear_instance_cache.assert_called_once()
    finally:
        finalizer.detach()


async def test_cleanup_s3_sessions_no_s3creator() -> None:
    """cleanup_s3_sessions skips instances without _s3creator."""
    mock_instance = MagicMock(spec=[])

    with patch("s3fs.S3FileSystem") as mock_s3fs:
        mock_s3fs._cache = {"key": mock_instance}
        await cleanup_s3_sessions()

        mock_s3fs.clear_instance_cache.assert_called_once()
