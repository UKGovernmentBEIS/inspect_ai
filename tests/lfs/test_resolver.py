"""Tests for resolve_lfs_directory.

Mocks only the HTTP layer (client.fetch_download_urls / client.download_lfs_object)
so the full resolve → cache → pointer pipeline runs with real files.
"""

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from inspect_ai._lfs._client import LFSDownloadInfo
from inspect_ai._lfs._pointer import LFS_POINTER_VERSION
from inspect_ai._lfs.exceptions import LFSResolverError
from inspect_ai._lfs.resolver import resolve_lfs_directory

FAKE_REPO_URL = "https://github.com/example/repo.git"


def _write_real_file(path: Path, content: str = "<html>hello</html>") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_lfs_pointer(path: Path, content: bytes = b"real file content") -> str:
    """Write an LFS pointer file and return the OID for the real content."""
    oid = hashlib.sha256(content).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"{LFS_POINTER_VERSION}\noid sha256:{oid}\nsize {len(content)}\n",
        encoding="utf-8",
    )
    return oid


def _configure_lfs_mocks(
    mock_fetch: MagicMock,
    mock_download: MagicMock,
    items: list[tuple[bytes, str]],
) -> None:
    """Wire up fetch_download_urls and download_lfs_object mocks."""
    content_by_oid = {oid: content for content, oid in items}
    mock_fetch.return_value = [
        LFSDownloadInfo(oid=oid, size=len(content), href=f"https://fake/{oid[:8]}")
        for content, oid in items
    ]

    def _download(info: LFSDownloadInfo, dest_path: Path) -> None:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(content_by_oid[info.oid])

    mock_download.side_effect = _download


_PATCH_FETCH = patch("inspect_ai._lfs._cache.fetch_download_urls")
_PATCH_DOWNLOAD = patch("inspect_ai._lfs._cache.download_lfs_object")


def test_real_files_returns_source_dir(tmp_path: Path) -> None:
    """Directory with only real files is returned as-is."""
    source = tmp_path / "source"
    cache = tmp_path / "cache"
    _write_real_file(source / "index.html")

    result = resolve_lfs_directory(source, cache, FAKE_REPO_URL)

    assert result == source


@_PATCH_DOWNLOAD
@_PATCH_FETCH
def test_lfs_pointers_populates_cache(
    mock_fetch: MagicMock, mock_download: MagicMock, tmp_path: Path
) -> None:
    """LFS pointers are resolved: real content appears in cache_dir."""
    source = tmp_path / "source"
    cache = tmp_path / "cache"
    content = b"the real index content"
    oid = _make_lfs_pointer(source / "index.html", content)
    _configure_lfs_mocks(mock_fetch, mock_download, [(content, oid)])

    result = resolve_lfs_directory(source, cache, FAKE_REPO_URL)

    assert result == cache
    assert (cache / "index.html").read_bytes() == content


@_PATCH_DOWNLOAD
@_PATCH_FETCH
def test_subdirectories_resolved_recursively(
    mock_fetch: MagicMock, mock_download: MagicMock, tmp_path: Path
) -> None:
    """Pointers in subdirectories are detected and cached with structure preserved."""
    source = tmp_path / "source"
    cache = tmp_path / "cache"
    index_content = b"<html>index</html>"
    logo_content = b"nested asset content"
    index_oid = _make_lfs_pointer(source / "index.html", index_content)
    logo_oid = _make_lfs_pointer(source / "assets" / "logo.png", logo_content)
    _configure_lfs_mocks(
        mock_fetch,
        mock_download,
        [(index_content, index_oid), (logo_content, logo_oid)],
    )

    result = resolve_lfs_directory(source, cache, FAKE_REPO_URL)

    assert result == cache
    assert (cache / "assets" / "logo.png").read_bytes() == logo_content
    assert (cache / "index.html").read_bytes() == index_content


def test_missing_directory_raises(tmp_path: Path) -> None:
    """Non-existent source_dir raises LFSResolverError."""
    with pytest.raises(LFSResolverError, match="Directory not found"):
        resolve_lfs_directory(
            tmp_path / "nonexistent", tmp_path / "cache", FAKE_REPO_URL
        )


@_PATCH_FETCH
def test_download_failure_raises(mock_fetch: MagicMock, tmp_path: Path) -> None:
    """Network failure in download_lfs_objects is wrapped in LFSResolverError."""
    source = tmp_path / "source"
    cache = tmp_path / "cache"
    _make_lfs_pointer(source / "file.txt")
    mock_fetch.side_effect = ConnectionError("network down")

    with pytest.raises(LFSResolverError, match="Failed to download LFS objects"):
        resolve_lfs_directory(source, cache, FAKE_REPO_URL)


@_PATCH_DOWNLOAD
@_PATCH_FETCH
def test_pruning_removes_orphaned_cache_entries(
    mock_fetch: MagicMock, mock_download: MagicMock, tmp_path: Path
) -> None:
    """Files removed from source are pruned from cache on next resolve."""
    source = tmp_path / "source"
    cache = tmp_path / "cache"

    keep_content = b"keep"
    remove_content = b"remove"
    keep_oid = _make_lfs_pointer(source / "keep.html", keep_content)
    remove_oid = _make_lfs_pointer(source / "remove.html", remove_content)
    _configure_lfs_mocks(
        mock_fetch,
        mock_download,
        [(keep_content, keep_oid), (remove_content, remove_oid)],
    )

    resolve_lfs_directory(source, cache, FAKE_REPO_URL)
    assert (cache / "remove.html").exists()

    # Remove source file, re-configure mocks for second call (only keep.html).
    (source / "remove.html").unlink()
    _configure_lfs_mocks(mock_fetch, mock_download, [(keep_content, keep_oid)])

    resolve_lfs_directory(source, cache, FAKE_REPO_URL)

    assert (cache / "keep.html").exists()
    assert not (cache / "remove.html").exists()
