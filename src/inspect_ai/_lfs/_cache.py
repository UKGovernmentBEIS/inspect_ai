"""LFS object downloading and cache management.

Downloads real file content from GitHub LFS into a local cache directory,
replacing pointer stubs with their actual content.
"""

import logging
import os
import time
from pathlib import Path

from ._client import (
    LFSDownloadInfo,
    download_lfs_object,
    fetch_download_urls,
)
from ._pointer import LFSPointer, is_lfs_pointer, parse_lfs_pointer
from .exceptions import LFSDownloadError

logger = logging.getLogger(__name__)


def download_lfs_objects(
    source_dir: Path,
    cache_dir: Path,
    repo_url: str,
) -> None:
    """Download LFS objects from GitHub into cache_dir.

    Walks source_dir, identifies LFS pointer files, checks the cache for each
    one, and downloads any missing or stale files via the LFS batch API.

    The cache mirrors the source directory structure. Each downloaded file has a
    sidecar ``<name>.oid`` file storing the SHA-256 OID. On subsequent runs, a
    cached file is considered fresh only when both the file and its sidecar
    exist and the sidecar OID matches the pointer's OID. Stale, incomplete, or
    missing entries are (re-)downloaded. Files in cache_dir that no longer exist
    in source_dir are pruned along with their sidecars.

    Args:
        source_dir: Directory containing LFS pointer files.
        cache_dir: Cache directory (will contain real files after download).
        repo_url: HTTPS URL of the git repository.

    Raises:
        LFSDownloadError: If any critical file fails to download.
    """
    # Collect pointers and check cache status.
    needs_download: list[tuple[Path, LFSPointer]] = []
    source_rel_paths: set[Path] = set()

    for repo_file in _walk_files(source_dir):
        rel = repo_file.relative_to(source_dir)
        source_rel_paths.add(rel)

        # .gitattributes applies uniformly, so all files should be pointers.
        assert is_lfs_pointer(repo_file), (
            f"Unexpected real file in LFS directory: {repo_file}"
        )

        parsed = parse_lfs_pointer(repo_file)
        if parsed is None:
            logger.warning("Could not parse LFS pointer: %s", repo_file)
            continue
        pointer = parsed

        cache_file = cache_dir / rel
        oid_file = cache_file.with_suffix(cache_file.suffix + ".oid")

        # Cache hit: file exists and OID matches.
        if cache_file.exists() and oid_file.exists():
            cached_oid = oid_file.read_text(encoding="utf-8").strip()
            if cached_oid == pointer.oid:
                logger.debug("%s: already up to date", rel)
                continue
            # OID mismatch — remove stale cache files before re-download.
            cache_file.unlink(missing_ok=True)
            oid_file.unlink(missing_ok=True)
        elif cache_file.exists() or oid_file.exists():
            # Incomplete cache entry — clean up orphaned files.
            cache_file.unlink(missing_ok=True)
            oid_file.unlink(missing_ok=True)

        needs_download.append((repo_file, pointer))

    if not needs_download:
        logger.debug("LFS cache is up to date")
        _prune_cache(cache_dir, source_rel_paths)
        return

    logger.info("Downloading %d LFS objects...", len(needs_download))

    # Batch request for download URLs.
    batch_objects = [(p.oid, p.size) for _, p in needs_download]
    oid_labels = {p.oid: str(f.relative_to(source_dir)) for f, p in needs_download}
    download_infos = fetch_download_urls(
        batch_objects, repo_url=repo_url, oid_labels=oid_labels
    )

    # Index by OID for lookup.
    info_by_oid: dict[str, LFSDownloadInfo] = {d.oid: d for d in download_infos}

    # Download each file.
    failed: list[str] = []
    for repo_file, pointer in needs_download:
        rel = repo_file.relative_to(source_dir)
        cache_file = cache_dir / rel
        oid_file = cache_file.with_suffix(cache_file.suffix + ".oid")
        marker_file = cache_file.with_suffix(cache_file.suffix + ".downloading")

        info = info_by_oid.get(pointer.oid)
        if info is None:
            logger.warning("%s: no download URL (%s)", rel, pointer.oid[:12])
            failed.append(str(rel))
            continue

        # Multiprocess coordination: skip if another process is downloading.
        if not _try_create_marker(marker_file):
            logger.debug("Another process is downloading %s, waiting...", rel)
            _wait_for_marker(marker_file)
            if cache_file.exists():
                continue
            # Other process may have failed; try to acquire marker ourselves.
            if not _try_create_marker(marker_file):
                _wait_for_marker(marker_file)
                if cache_file.exists():
                    continue
                logger.warning("Could not acquire download marker for %s", rel)
                failed.append(str(rel))
                continue

        try:
            download_lfs_object(info, marker_file)
            marker_file.rename(cache_file)
            oid_file.write_text(pointer.oid, encoding="utf-8")
            logger.info("%s: downloaded", rel)
        except Exception as e:
            # Clean up all partial state.
            marker_file.unlink(missing_ok=True)
            cache_file.unlink(missing_ok=True)
            oid_file.unlink(missing_ok=True)
            failed.append(str(rel))
            logger.warning("%s: download failed — %s", rel, e, exc_info=True)

    if failed:
        raise LFSDownloadError(
            f"Failed to download {len(failed)} LFS object(s): {', '.join(failed)}"
        )

    _prune_cache(cache_dir, source_rel_paths)


def _prune_cache(cache_dir: Path, source_rel_paths: set[Path]) -> None:
    """Remove cached files that no longer exist in the source directory."""
    if not cache_dir.is_dir():
        return

    # Metadata suffixes managed by this module.
    metadata_suffixes = {".oid", ".downloading"}

    for cached_file in _walk_files(cache_dir):
        rel = cached_file.relative_to(cache_dir)

        # Skip metadata files — they'll be orphaned when their parent is removed.
        if rel.suffix in metadata_suffixes:
            continue

        if rel not in source_rel_paths:
            cached_file.unlink(missing_ok=True)
            # Clean up associated metadata.
            for suffix in metadata_suffixes:
                cached_file.with_suffix(cached_file.suffix + suffix).unlink(
                    missing_ok=True
                )
            logger.info("Pruned orphaned cache entry: %s", rel)


def _walk_files(directory: Path) -> list[Path]:
    """Recursively list all files in a directory."""
    return [e for e in sorted(directory.rglob("*")) if e.is_file()]


def _try_create_marker(marker_file: Path) -> bool:
    """Atomically create a marker file. Returns True if we created it."""
    marker_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(marker_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _wait_for_marker(marker_file: Path, timeout_seconds: int = 180) -> None:
    """Wait for a marker file to be removed (another process finished).

    If the marker still exists after timeout, removes it as likely orphaned.
    """
    deadline = time.monotonic() + timeout_seconds
    while marker_file.exists() and time.monotonic() < deadline:
        time.sleep(0.5)

    # If marker still exists after timeout, it's likely orphaned by a crashed
    # process. Remove it so subsequent attempts can proceed.
    if marker_file.exists():
        marker_file.unlink(missing_ok=True)
        logger.warning("Removed orphaned marker file: %s", marker_file)
