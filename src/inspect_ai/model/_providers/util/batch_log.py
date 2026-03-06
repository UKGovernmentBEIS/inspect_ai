"""Logging utilities for batch operations."""

import dataclasses
import time
from collections.abc import Callable

from inspect_ai._util.format import format_progress_time


@dataclasses.dataclass(frozen=True)
class BatchStatus:
    """Immutable status of batch processing."""

    batch_count: int
    pending_requests: int
    completed_requests: int
    failed_requests: int
    oldest_created_at: int | None
    """unix timestamp in seconds - or None if batch_count is 0"""


BatchStatusCallback = Callable[[BatchStatus], None]
BatchLogCallback = Callable[[str], None]

_batch_status_callback: BatchStatusCallback | None = None
_batch_log_callback: BatchLogCallback | None = None


def set_batch_status_callback(callback: BatchStatusCallback | None) -> None:
    global _batch_status_callback
    _batch_status_callback = callback


def set_batch_log_callback(callback: BatchLogCallback | None) -> None:
    global _batch_log_callback
    _batch_log_callback = callback


def _default_batch_status_callback(status: BatchStatus) -> None:
    oldest_age = (
        int(time.time() - status.oldest_created_at) if status.oldest_created_at else 0
    )
    log_batch(
        f"Current batches: {status.batch_count}, "
        f"requests (pending/completed/failed): {status.pending_requests}/{status.completed_requests}/{status.failed_requests}, "
        f"oldest batch age: {format_progress_time(oldest_age, False)}"
    )


def emit_batch_status(status: BatchStatus) -> None:
    """Emit batch status to callback or default handler."""
    (_batch_status_callback or _default_batch_status_callback)(status)


def log_batch(message: str) -> None:
    """Log batch operation messages.

    For now, this simply calls print() but provides a centralized point
    for future custom logging implementation.

    Args:
        message: The message to log
    """
    (_batch_log_callback or print)(message)
