"""Retry helpers for csv_dataset / json_dataset.

Mirrors the structure of the HF retry helper in `hf.py` but classifies generic
HTTP/connection failure modes raised by the fsspec/urllib/requests/aiohttp
backends used by `inspect_ai._util.file.file`.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

# HTTP statuses worth retrying. 408 (request timeout), 429 (rate limit), and the
# 5xx family covered by the standard cloud-storage providers.
_RETRYABLE_HTTP_STATUSES: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})

# Exponential backoff bounds. Kept short relative to `hf.py` since CSV/JSON
# loads are typically small individual requests rather than multi-file HF
# dataset downloads.
_INITIAL_WAIT_SECS = 1.0
_MAX_WAIT_SECS = 60.0
_MAX_TRIES_DEFAULT = 3
_MAX_TRIES_CI = 5


def _dataset_max_tries() -> int:
    return _MAX_TRIES_CI if os.getenv("CI") else _MAX_TRIES_DEFAULT


def _http_status_of(err: BaseException) -> int | None:
    """Best-effort HTTP status extraction.

    Reads the status off any of the common HTTP client exception shapes
    (aiohttp, requests, urllib, generic duck-typed `status`/`code`).
    """
    # urllib.error.HTTPError exposes `.code`
    code = getattr(err, "code", None)
    if isinstance(code, int):
        return code
    # aiohttp.ClientResponseError exposes `.status`
    status = getattr(err, "status", None)
    if isinstance(status, int):
        return status
    # requests.exceptions.HTTPError holds the response on `.response`
    response = getattr(err, "response", None)
    if response is not None:
        rstatus = getattr(response, "status_code", None)
        if isinstance(rstatus, int):
            return rstatus
    return None


def _should_retry_dataset_io_error(err: BaseException) -> bool:
    """Return True if `err` is a transient network failure worth retrying.

    Covers the four backends `inspect_ai._util.file.file` can dispatch to:
    direct local filesystem, fsspec HTTP (aiohttp), fsspec S3/GCS/Azure
    (which surface as either aiohttp or requests errors depending on the
    backend), and bare urllib for direct HTTP.

    Intentionally narrow: does not retry `FileNotFoundError`,
    `PermissionError`, `IsADirectoryError`, `ValueError`, decode errors,
    or any other non-network failure mode.
    """
    # Built-in network errors raised by the standard library and fsspec.
    if isinstance(err, (ConnectionError, TimeoutError)):
        return True

    # aiohttp errors (fsspec's HTTPFileSystem and some S3/GCS backends).
    try:
        from aiohttp import ClientConnectionError, ClientResponseError

        if isinstance(err, ClientConnectionError):
            return True
        if isinstance(err, ClientResponseError):
            return err.status in _RETRYABLE_HTTP_STATUSES
    except ImportError:
        pass

    # requests-based backends (some fsspec implementations, urllib3 wrappers).
    try:
        from requests.exceptions import ConnectionError as RequestsConnectionError
        from requests.exceptions import HTTPError as RequestsHTTPError
        from requests.exceptions import Timeout as RequestsTimeout

        if isinstance(err, (RequestsConnectionError, RequestsTimeout)):
            return True
        if isinstance(err, RequestsHTTPError):
            status = _http_status_of(err)
            if status is not None:
                return status in _RETRYABLE_HTTP_STATUSES
    except ImportError:
        pass

    # urllib stdlib errors (used by some fsspec backends as a fallback).
    import urllib.error

    if isinstance(err, urllib.error.HTTPError):
        return err.code in _RETRYABLE_HTTP_STATUSES
    if isinstance(err, urllib.error.URLError):
        # URLError wraps lower-level network failures (DNS, connection reset).
        reason = getattr(err, "reason", None)
        if isinstance(reason, (ConnectionError, TimeoutError, OSError)):
            return True

    return False


_T = TypeVar("_T")


def _call_with_dataset_retry(
    fn: Callable[[], _T],
    *,
    label: str = "dataset",
) -> _T:
    """Run `fn` with exponential-backoff retry on transient I/O failures.

    Args:
        fn: Zero-argument callable that performs the dataset read.
        label: Human-readable label used in the warning log line.

    Returns:
        The successful return value of `fn`.

    Raises:
        Whatever `fn` raises after exhausting retries, or the first
        non-retryable error.
    """
    import tenacity.nap
    from tenacity import (
        RetryCallState,
        Retrying,
        retry_if_exception,
        stop_after_attempt,
        wait_random_exponential,
    )

    def log_before_sleep(rs: RetryCallState) -> None:
        if rs.outcome is None:
            return
        ex = rs.outcome.exception()
        if ex is None:
            return
        logger.warning(
            "%s read failed with %s (attempt %d); retrying in %.1fs",
            label,
            type(ex).__name__,
            rs.attempt_number,
            rs.upcoming_sleep,
        )

    retrier = Retrying(
        sleep=tenacity.nap.sleep,
        retry=retry_if_exception(_should_retry_dataset_io_error),
        wait=wait_random_exponential(multiplier=_INITIAL_WAIT_SECS, max=_MAX_WAIT_SECS),
        stop=stop_after_attempt(_dataset_max_tries()),
        before_sleep=log_before_sleep,
        reraise=True,
    )
    return retrier(fn)
