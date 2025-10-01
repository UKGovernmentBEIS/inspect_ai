"""Work pool implementation for scanner operations.

This module now provides a strategy-based abstraction (``ConcurrencyStrategy``)
for executing scanner work. Currently only the asynchronous in-process task
strategy (``AsyncTaskStrategy``) is implemented. A future
``ProcessPoolStrategy`` will enable multi-process
execution without altering the public API.
"""

import time
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable

import anyio
from anyio import create_task_group
from anyio.abc import TaskGroup

from inspect_ai._util.registry import registry_info
from inspect_ai.util._anyio import inner_exception

from .._recorder.recorder import ScanRecorder
from .._scanner.result import ResultReport
from .common import ConcurrencyStrategy, ParseJob, ScannerJob


@dataclass
class WorkerMetrics:
    """Encapsulates all worker-related metrics."""

    worker_count: int = 0
    workers_waiting: int = 0
    workers_scanning: int = 0
    worker_id_counter: int = 0


def single_process_strategy(
    *,
    max_concurrent_scans: int,
    buffer_multiple: float | None = 1.0,
    diagnostics: bool = False,
    diag_prefix: str | None = None,
    overall_start_time: float | None = None,
) -> ConcurrencyStrategy:
    """Single-process execution strategy with async concurrency.

    The strategy greedily parses and loads transcripts to fill the work buffer, keeping
    scan tasks saturated and preventing stalls.

    Args:
        max_concurrent_scans: Number of scanner executions to run concurrently
        buffer_multiple: Buffer size as multiple of max_concurrent_scans. Higher
            values reduce worker stalls when all scans complete simultaneously (benefit)
            at the cost of increased memory usage (cost). Default 1.0 = buffer one
            item per scan.
        diagnostics: Whether to print diagnostic information
        diag_prefix: Prefix for diagnostic messages (internal use)
        overall_start_time: Start time for diagnostics (internal use)
    """
    diag_prefix = f"{diag_prefix} " if diag_prefix else ""

    async def the_func(
        *,
        recorder: ScanRecorder,
        parse_jobs: AsyncIterator[ParseJob],
        parse_function: Callable[[ParseJob], Awaitable[list[ScannerJob]]],
        scan_function: Callable[[ScannerJob], Awaitable[list[ResultReport]]],
        bump_progress: Callable[[], None],
    ) -> None:
        metrics = WorkerMetrics()
        nonlocal overall_start_time
        if not overall_start_time:
            overall_start_time = time.time()
        queue_size = int(
            max_concurrent_scans
            * (buffer_multiple if buffer_multiple is not None else 1.0)
        )

        (scanner_job_send_stream, scanner_job_receive_stream) = (
            anyio.create_memory_object_stream[ScannerJob](queue_size)
        )

        def print_diagnostics(actor_name: str, *message_parts: object) -> None:
            if diagnostics:
                running_time = f"+{time.time() - overall_start_time:.3f}s"
                print(running_time, diag_prefix, f"{actor_name}:", *message_parts)

        def _metrics_info() -> str:
            return (
                f"workers: {metrics.worker_count} "
                f"(scanning: {metrics.workers_scanning}, "
                f"stalled: {metrics.workers_waiting}) "
                f"queue size: {scanner_job_receive_stream.statistics().current_buffer_used} "
            )

        def _scanner_job_info(item: ScannerJob) -> str:
            return f"{item.union_transcript.id, registry_info(item.scanner).name}"

        async def _worker_task(worker_id: int) -> None:
            items_processed = 0
            try:
                while True:
                    queue_was_empty_start_time = (
                        time.time()
                        if scanner_job_receive_stream.statistics().current_buffer_used
                        == 0
                        else None
                    )
                    try:
                        metrics.workers_waiting += 1
                        with anyio.move_on_after(2.0) as timeout_scope:
                            scanner_job = await scanner_job_receive_stream.receive()
                    finally:
                        metrics.workers_waiting -= 1
                    if timeout_scope.cancelled_caught:
                        break
                    stall_phrase = (
                        f" after stalling for {time.time() - queue_was_empty_start_time:.3f}s"
                        if queue_was_empty_start_time
                        else ""
                    )
                    print_diagnostics(
                        f"Worker #{worker_id}",
                        f"starting on {_scanner_job_info(scanner_job)} item{stall_phrase}\n\t{_metrics_info()}",
                    )
                    exec_start_time = time.time()
                    try:
                        metrics.workers_scanning += 1
                        await recorder.record(
                            scanner_job.union_transcript,
                            registry_info(scanner_job.scanner).name,
                            await scan_function(scanner_job),
                        )
                        bump_progress()
                    finally:
                        metrics.workers_scanning -= 1
                    print_diagnostics(
                        f"Worker #{worker_id}",
                        f"completed {_scanner_job_info(scanner_job)} in {(time.time() - exec_start_time):.3f}s",
                    )
                    items_processed += 1
                print_diagnostics(
                    f"Worker #{worker_id}",
                    f"finished after processing {items_processed} items.\n\t{_metrics_info()}",
                )
            finally:
                metrics.worker_count -= 1

        async def _producer(tg: TaskGroup) -> None:
            async for parse_job in parse_jobs:
                scanner_jobs = await parse_function(parse_job)
                print_diagnostics("Producer", f"Parsed {parse_job.transcript_info.id}")
                for scanner_job in scanner_jobs:
                    backpressure = (
                        scanner_job_receive_stream.statistics().current_buffer_used
                        >= queue_size
                    )
                    await scanner_job_send_stream.send(scanner_job)
                    print_diagnostics(
                        "Producer",
                        f"Added scanner job {_scanner_job_info(scanner_job)} "
                        f"{' after backpressure relieved' if backpressure else ''}\n\t{_metrics_info()}",
                    )
                    if metrics.worker_count < max_concurrent_scans:
                        metrics.worker_count += 1
                        metrics.worker_id_counter += 1
                        tg.start_soon(_worker_task, metrics.worker_id_counter)
                        print_diagnostics(
                            "Producer",
                            f"Spawned worker #{metrics.worker_id_counter}\n\t{_metrics_info()}",
                        )
                    await anyio.sleep(0)
            print_diagnostics("Producer", "FINISHED PRODUCING ALL WORK")

        try:
            async with create_task_group() as tg:
                await _producer(tg)
        except Exception as ex:
            raise inner_exception(ex)

    return the_func
