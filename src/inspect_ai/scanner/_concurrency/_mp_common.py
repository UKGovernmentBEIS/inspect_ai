"""Shared context for multiprocessing communication.

This module contains the module-level globals that are shared between the main
process and worker subprocesses via fork. The main process initializes these
values, and forked workers inherit them through copy-on-write memory.
"""

from __future__ import annotations

from multiprocessing.queues import Queue as MPQueue
from typing import Awaitable, Callable, TypeAlias, TypeVar

import anyio

from .._scanner.result import ResultReport
from .._transcript.types import TranscriptInfo
from .common import ParseJob, ScannerJob

# Module-level storage for invariant data (accessible after fork)
PARSE_FUNCTION: Callable[[ParseJob], Awaitable[list[ScannerJob]]] | None = None
SCAN_FUNCTION: Callable[[ScannerJob], Awaitable[list[ResultReport]]] | None = None
BUFFER_MULTIPLE: float | None = None
DIAGNOSTICS: bool = False
OVERALL_START_TIME: float = 0.0

# Module-level queues (avoid passing through ProcessPoolExecutor which attempts to pickle)
WORK_QUEUE: MPQueue[ParseJob | None] | None = None
ResultItem: TypeAlias = tuple[TranscriptInfo, str, list[ResultReport]]
ResultQueueItem: TypeAlias = ResultItem | Exception | None
RESULT_QUEUE: MPQueue[ResultQueueItem] | None = None


def parse_job_info(job: "ParseJob") -> str:
    """Format ParseJob info for diagnostic messages."""
    return f"{job.transcript_info.id, job.scanner_indices}"


T = TypeVar("T")


async def run_sync_on_thread(func: Callable[[], T]) -> T:
    """Run a blocking callable in a thread, preserving its return type.

    This is a type-safe wrapper around anyio.to_thread.run_sync that preserves
    the return type of the callable, enabling proper downstream type checking.

    Args:
        func: A blocking callable with no arguments

    Returns:
        The return value of func, with proper type information preserved
    """
    return await anyio.to_thread.run_sync(func)
