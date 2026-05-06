"""Helpers for downloading external files with SHA256 verification.

These helpers are intended for fetching dataset files, zipped corpora, and
other external assets at eval load time. Pinning a SHA256 at the call site
makes upstream changes or corruption detectable immediately rather than
silently poisoning results.

The implementations skip the network entirely when the destination already
exists with a matching checksum, retry on transient HTTP failures (408, 429,
5xx) using the same policy as model providers, and write atomically via a
sibling tempfile + rename so a failed download never leaves a partial file
in place.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential_jitter,
)

from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.httpx import httpx_should_retry, log_httpx_retry_attempt

_CHUNK_SIZE = 1 << 20  # 1 MiB


def download(
    url: str,
    sha256: str,
    dest: Path,
    *,
    headers: dict[str, str] | None = None,
) -> Path:
    """Download a file and verify its SHA256 checksum.

    If `dest` already exists and its checksum matches, the download is
    skipped. Retries on transient HTTP errors (408, 429, 5xx) with
    exponential backoff; gives up immediately on other 4xx responses.

    The download is streamed to a sibling tempfile and atomically renamed
    to `dest` only after the checksum has been verified, so a failed or
    corrupted download never leaves a partial file at `dest`. Two
    processes targeting the same `dest` are safe under last-write-wins
    semantics; no locking is performed.

    Args:
        url: URL to download from.
        sha256: Expected SHA256 hex digest of the file contents.
        dest: Destination path. Parent directory is created if missing.
        headers: Optional HTTP headers to include with the request.

    Returns:
        The destination path.

    Raises:
        ValueError: If the downloaded file's SHA256 does not match `sha256`.
        httpx.HTTPStatusError: On non-retryable HTTP error responses.
    """
    dest = Path(dest)
    if dest.exists() and _sha256_of(dest) == sha256:
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")

    @retry(
        wait=wait_exponential_jitter(),
        stop=stop_after_attempt(5) | stop_after_delay(60),
        retry=retry_if_exception(httpx_should_retry),
        before_sleep=log_httpx_retry_attempt(f"download {url}"),
    )
    def _stream_to_tmp() -> str:
        hasher = hashlib.sha256()
        with httpx.stream(
            "GET", url, headers=headers, follow_redirects=True
        ) as response:
            response.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in response.iter_bytes(_CHUNK_SIZE):
                    f.write(chunk)
                    hasher.update(chunk)
        return hasher.hexdigest()

    try:
        actual = _stream_to_tmp()
        if actual != sha256:
            raise ValueError(
                f"Checksum mismatch for {url}: expected {sha256}, got {actual}"
            )
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()

    return dest


def gdrive_download(file_id: str, sha256: str, dest: Path) -> Path:
    """Download a Google Drive file via `gdown` and verify SHA256.

    Useful for fetching public-link Google Drive assets (datasets, zipped
    corpora) without OAuth. Requires the optional `gdown` dependency:

        pip install gdown

    Skip-if-checksum-matches and atomic-write semantics are identical to
    `download()`.

    Args:
        file_id: Google Drive file id.
        sha256: Expected SHA256 hex digest of the file contents.
        dest: Destination path. Parent directory is created if missing.

    Returns:
        The destination path.

    Raises:
        ValueError: If the downloaded file's SHA256 does not match `sha256`.
        PrerequisiteError: If `gdown` is not installed.
    """
    dest = Path(dest)
    if dest.exists() and _sha256_of(dest) == sha256:
        return dest

    try:
        import gdown  # type: ignore[import-not-found]
    except ImportError:
        raise pip_dependency_error("Google Drive download", ["gdown"])

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")

    try:
        gdown.download(id=file_id, output=str(tmp), quiet=False)
        actual = _sha256_of(tmp)
        if actual != sha256:
            raise ValueError(
                f"Checksum mismatch for Google Drive file {file_id}: "
                f"expected {sha256}, got {actual}"
            )
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()

    return dest


def _sha256_of(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
