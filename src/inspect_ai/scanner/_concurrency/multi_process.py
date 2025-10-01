"""Multi-process work pool implementation for scanner operations.

This module provides a process-based concurrency strategy using fork-based
ProcessPoolExecutor. Each worker process runs its own async event loop with
multiple concurrent tasks, allowing efficient parallel execution of scanner work.
"""

from __future__ import annotations

import multiprocessing
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from typing import TYPE_CHECKING, AsyncIterator, Awaitable, Callable

if TYPE_CHECKING:
    from multiprocessing.queues import Queue as MPQueue

    from .._recorder.recorder import ScanResults, ScanStatus
    from .._scanspec import ScanSpec

import anyio
from anyio import create_task_group

from inspect_ai.util._anyio import inner_exception

from .._recorder.recorder import ScanRecorder
from .._scanner.result import ResultReport
from .._transcript.types import TranscriptInfo
from .common import ConcurrencyStrategy, ParseJob, ScannerJob
from .single_process import single_process_strategy

# Module-level storage for invariant data (accessible after fork)
_PARSE_FUNCTION: Callable[[ParseJob], Awaitable[list[ScannerJob]]] | None = None
_SCAN_FUNCTION: Callable[[ScannerJob], Awaitable[list[ResultReport]]] | None = None
# Module-level queues (avoid passing through ProcessPoolExecutor which attempts to pickle)
_WORK_QUEUE: "MPQueue[ParseJob | None]" | None = None
_RESULT_QUEUE: (
    "MPQueue[tuple[TranscriptInfo, str, list[ResultReport]] | Exception | None]" | None
) = None


class _QueueBasedRecorder(ScanRecorder):
    """Recorder that sends results to a multiprocessing queue instead of writing to disk.

    This is a minimal implementation that only implements the `record` method,
    which is the only method called by single_process_strategy.
    """

    def __init__(
        self,
        result_queue: "MPQueue[tuple[TranscriptInfo, str, list[ResultReport]] | Exception | None]",
    ) -> None:
        self.result_queue = result_queue

    async def init(self, spec: "ScanSpec", scans_location: str) -> None:
        """Not used in worker processes."""
        pass

    async def resume(self, scan_location: str) -> "ScanSpec":
        """Not used in worker processes."""
        raise NotImplementedError("resume not supported in worker processes")

    async def location(self) -> str:
        """Not used in worker processes."""
        return ""

    async def is_recorded(self, transcript: TranscriptInfo, scanner: str) -> bool:
        """Not used in worker processes."""
        return False

    async def record(
        self,
        transcript: TranscriptInfo,
        scanner: str,
        results: Sequence[ResultReport],
    ) -> None:
        """Send results to the result queue for the main process to handle."""
        await anyio.to_thread.run_sync(
            self.result_queue.put,
            (transcript, scanner, list(results)),
        )

    async def flush(self) -> None:
        """Not used in worker processes."""
        pass

    async def complete(self) -> "ScanStatus":
        """Not used in worker processes."""
        raise NotImplementedError("complete not supported in worker processes")

    @staticmethod
    async def status(scan_location: str) -> "ScanStatus":
        """Not used in worker processes."""
        raise NotImplementedError("status not supported in worker processes")

    @staticmethod
    async def results(scan_location: str, scanner: str | None = None) -> "ScanResults":
        """Not used in worker processes."""
        raise NotImplementedError("results not supported in worker processes")


def _parse_job_info(job: ParseJob) -> str:
    return f"{job.transcript_info.id, job.scanner_indices}"


def multi_process_strategy(
    *,
    max_concurrent_scans: int,
    max_processes: int | None = None,
    buffer_multiple: float | None = None,
    diagnostics: bool = False,
) -> ConcurrencyStrategy:
    """Multi-process execution strategy with nested async concurrency.

    Distributes ParseJob work items across multiple worker processes. Each worker
    uses single-process strategy internally to control scan concurrency and buffering.
    The ParseJob queue is unbounded since ParseJobs are lightweight metadata objects.

    Args:
        max_concurrent_scans: Target total scanner concurrency across all processes
        max_processes: Number of worker processes to spawn (None = auto-detect from CPU count)
        buffer_multiple: Buffer size multiple passed to each worker's single-process strategy
        diagnostics: Whether to print diagnostic information
    """

    async def the_func(
        *,
        recorder: ScanRecorder,
        parse_jobs: AsyncIterator[ParseJob],
        parse_function: Callable[[ParseJob], Awaitable[list[ScannerJob]]],
        scan_function: Callable[[ScannerJob], Awaitable[list[ResultReport]]],
        bump_progress: Callable[[], None],
    ) -> None:
        global _PARSE_FUNCTION, _SCAN_FUNCTION
        _PARSE_FUNCTION = parse_function
        _SCAN_FUNCTION = scan_function

        # Auto-detect number of processes if not specified
        actual_max_processes = (
            max_processes if max_processes is not None else multiprocessing.cpu_count()
        )

        # Calculate scans per process
        hack_factor = 3
        scans_per_process = hack_factor * max(
            1, max_concurrent_scans // actual_max_processes
        )

        overall_start_time = time.time()

        def print_diagnostics(actor_name: str, *message_parts: object) -> None:
            if diagnostics:
                running_time = f"+{time.time() - overall_start_time:.3f}s"
                print(running_time, f"{actor_name}:", *message_parts)

        print_diagnostics(
            "Setup",
            f"Multi-process strategy: {actual_max_processes} processes × "
            f"{scans_per_process} scans = {actual_max_processes * scans_per_process} total concurrency",
        )

        # Create queues and store globally so forked processes inherit them directly.
        # ParseJob queue is unbounded - ParseJobs are tiny metadata objects with no backpressure needed.
        # Real backpressure happens inside each worker via single-process strategy's ScannerJob buffer.
        global _WORK_QUEUE, _RESULT_QUEUE
        _WORK_QUEUE = multiprocessing.Queue()
        _RESULT_QUEUE = multiprocessing.Queue()

        # Non-None local aliases for type checking clarity
        assert _WORK_QUEUE is not None
        assert _RESULT_QUEUE is not None
        work_queue = _WORK_QUEUE
        result_queue = _RESULT_QUEUE

        async def _producer() -> None:
            """Producer task that feeds work items into the queue."""
            async for item in parse_jobs:
                await anyio.to_thread.run_sync(partial(work_queue.put, item))
                print_diagnostics(
                    "MP Producer",
                    f"Added ParseJob {_parse_job_info(item)}",
                )

            # Send sentinel values to signal worker tasks to stop (one per task)
            sentinel_count = actual_max_processes * scans_per_process
            for _ in range(sentinel_count):
                await anyio.to_thread.run_sync(work_queue.put, None)

            print_diagnostics("MP Producer", "FINISHED PRODUCING ALL WORK")

        async def _result_collector() -> None:
            """Collector task that receives results and records them."""
            items_processed = 0
            workers_finished = 0

            while workers_finished < actual_max_processes:
                result = await anyio.to_thread.run_sync(result_queue.get)

                if result is None:
                    # Sentinel from a worker process indicating it's done
                    workers_finished += 1
                    print_diagnostics(
                        "MP Collector",
                        f"Worker finished ({workers_finished}/{actual_max_processes})",
                    )
                    continue

                if isinstance(result, Exception):
                    raise result

                transcript_info, scanner_name, results = result
                await recorder.record(transcript_info, scanner_name, results)
                bump_progress()

                items_processed += 1
                print_diagnostics(
                    "MP Collector",
                    f"Recorded results for {transcript_info.id} (total: {items_processed})",
                )

        try:
            # Start worker processes
            ctx = multiprocessing.get_context("fork")
            with ProcessPoolExecutor(
                max_workers=actual_max_processes, mp_context=ctx
            ) as executor:
                # Submit worker processes
                futures = []
                for worker_id in range(actual_max_processes):
                    try:
                        future = executor.submit(
                            _worker_process_main,
                            scans_per_process,
                            worker_id,
                            buffer_multiple,
                            diagnostics,
                            overall_start_time,
                        )
                        futures.append(future)
                        print_diagnostics(
                            "Main", f"Spawned worker process #{worker_id}"
                        )
                    except Exception as ex:
                        print(ex)
                        raise

                # Run producer and result collector concurrently
                async with create_task_group() as tg:
                    tg.start_soon(_producer)
                    tg.start_soon(_result_collector)

                # Wait for all worker processes to complete
                for future in futures:
                    await anyio.to_thread.run_sync(future.result)

                print_diagnostics("MP Main", "All worker processes completed")

        except Exception as ex:
            raise inner_exception(ex)
        finally:
            # Cleanup globals to prevent leakage between runs
            _WORK_QUEUE = None
            _RESULT_QUEUE = None
            _PARSE_FUNCTION = None
            _SCAN_FUNCTION = None

    return the_func


def _worker_process_main(
    max_concurrent_scans: int,
    worker_id: int,
    buffer_multiple: float | None,
    diagnostics: bool,
    overall_start_time: float,
) -> None:
    """Worker process main function.

    Runs in a forked subprocess with access to parent's memory.
    Uses single_process_strategy internally to coordinate async tasks.
    """
    global _PARSE_FUNCTION, _SCAN_FUNCTION, _WORK_QUEUE, _RESULT_QUEUE
    assert _PARSE_FUNCTION is not None, "parse_function not initialized"
    assert _SCAN_FUNCTION is not None, "scan_function not initialized"
    assert _WORK_QUEUE is not None, "work_queue not initialized"
    assert _RESULT_QUEUE is not None, "result_queue not initialized"
    parse_function = _PARSE_FUNCTION
    scan_function = _SCAN_FUNCTION

    async def _worker_main() -> None:
        """Main async function for worker process."""

        def print_diagnostics(actor_name: str, *message_parts: object) -> None:
            if diagnostics:
                running_time = f"+{time.time() - overall_start_time:.3f}s"
                print(running_time, f"P{worker_id} ", f"{actor_name}:", *message_parts)

        print_diagnostics(
            "worker main",
            f"Starting with {max_concurrent_scans} max concurrent scans",
        )

        # Create an async iterator that pulls ParseJob items from the work queue
        async def _parse_job_iterator() -> AsyncIterator[ParseJob]:
            """Yields ParseJob items from the work queue until sentinel is received."""
            items_pulled = 0
            while True:
                work_item_data: ParseJob | None = await anyio.to_thread.run_sync(
                    _WORK_QUEUE.get
                )

                if work_item_data is None:
                    # Sentinel value - time to stop
                    print_diagnostics(
                        "parse job iterator",
                        f"Received stop signal after pulling {items_pulled} items",
                    )
                    break

                items_pulled += 1
                print_diagnostics(
                    "parse job iterator",
                    f"Pulled {_parse_job_info(work_item_data)}",
                )

                yield work_item_data

        # Create a queue-based recorder that sends results back to main process
        recorder = _QueueBasedRecorder(_RESULT_QUEUE)

        # Use single_process_strategy to coordinate the async tasks
        strategy = single_process_strategy(
            max_concurrent_scans=max_concurrent_scans,
            buffer_multiple=buffer_multiple,
            diagnostics=diagnostics,
            diag_prefix=f"P{worker_id}",
            overall_start_time=overall_start_time,
        )

        try:
            await strategy(
                recorder=recorder,
                parse_jobs=_parse_job_iterator(),
                parse_function=parse_function,
                scan_function=scan_function,
                bump_progress=lambda: None,  # Progress is bumped in main process
            )
        except Exception as ex:
            # Send exception back to main process
            await anyio.to_thread.run_sync(_RESULT_QUEUE.put, ex)
            raise

        print_diagnostics("All tasks completed")

        # Send completion sentinel to result collector
        await anyio.to_thread.run_sync(_RESULT_QUEUE.put, None)

    # Run the async event loop in this worker process
    anyio.run(_worker_main)
