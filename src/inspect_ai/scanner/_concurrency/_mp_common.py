"""Shared context for multiprocessing communication.

This module contains the module-level globals that are shared between the main
process and worker subprocesses via fork. The main process initializes these
values, and forked workers inherit them through copy-on-write memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from multiprocessing.queues import Queue as MPQueue
from typing import Awaitable, Callable, TypeAlias, TypeVar, cast

import anyio

from .._scanner.result import ResultReport
from .._transcript.types import TranscriptInfo
from .common import ParseJob, ScannerJob

ResultItem: TypeAlias = tuple[TranscriptInfo, str, list[ResultReport]]
ResultQueueItem: TypeAlias = ResultItem | Exception | None


@dataclass
class IPCContext:
    """Shared state for IPC between main process and forked workers."""

    parse_function: Callable[[ParseJob], Awaitable[list[ScannerJob]]]
    scan_function: Callable[[ScannerJob], Awaitable[list[ResultReport]]]
    buffer_multiple: float | None
    diagnostics: bool
    overall_start_time: float
    parse_job_queue: MPQueue[ParseJob | None]
    result_queue: MPQueue[ResultQueueItem]


# Global IPC context shared between main process and forked subprocesses.
# Initialized by multi_process strategy, inherited by workers via fork.
# Type is non-None but runtime starts as None (cast) to avoid | None everywhere.
ipc_context = cast(IPCContext, None)


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
