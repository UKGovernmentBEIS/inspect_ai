"""Multi-process work pool implementation for scanner operations.

This module provides a process-based concurrency strategy using fork-based
ProcessPoolExecutor. Each worker process runs its own async event loop with
multiple concurrent tasks, allowing efficient parallel execution of scanner work.
"""

from __future__ import annotations

import multiprocessing
import time
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from concurrent.futures import ProcessPoolExecutor
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
from .common import ParseJob, ScannerJob
from .single_process import single_process_strategy

# Module-level storage for invariant data (accessible after fork)
_PARSE_FUNCTION: Callable[[ParseJob], Awaitable[list[ScannerJob]]] | None = None
_SCAN_FUNCTION: Callable[[ScannerJob], Awaitable[list[ResultReport]]] | None = None
# Module-level queues (avoid passing through ProcessPoolExecutor which attempts to pickle)
_WORK_QUEUE: "MPQueue[tuple[TranscriptInfo, AbstractSet[int]] | None]" | None = None
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


def multi_process_strategy(
    *,
    max_tasks: int,
    max_processes: int,
    max_queue_size: int | None,
    diagnostics: bool = True,
) -> Callable[
    [
        ScanRecorder,
        AsyncIterator[ParseJob],
        Callable[[ParseJob], Awaitable[list[ScannerJob]]],
        Callable[[ScannerJob], Awaitable[list[ResultReport]]],
        Callable[[], None],
    ],
    Awaitable[None],
]:
    """Multi-process execution strategy with nested async concurrency.

    Args:
        max_tasks: Target total scanner concurrency across all processes
        max_processes: Number of worker processes to spawn
        max_queue_size: Maximum work queue size for backpressure
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

        # Peek at first work item to determine scanner count and calculate concurrency
        first_item: ParseJob | None = None
        try:
            first_item = await parse_jobs.__anext__()
        except StopAsyncIteration:
            # No work items, nothing to do
            return

        scanners_per_item = len(first_item.scanner_indices)
        if scanners_per_item == 0:
            return

        # Calculate how many WorkItems to process concurrently
        # Since each WorkItem runs scanners_per_item scanners concurrently,
        # we need: max_concurrent_work_items = max_tasks / scanners_per_item
        max_concurrent_work_items = max(1, max_tasks // scanners_per_item)
        tasks_per_process = max(1, max_concurrent_work_items // max_processes)

        # Adjust max_processes if needed to match desired concurrency
        actual_max_processes = min(max_processes, max_concurrent_work_items)

        overall_start_time = time.time()

        def print_diagnostics(actor_name: str, *message_parts: object) -> None:
            if diagnostics:
                running_time = f"+{time.time() - overall_start_time:.3f}s"
                print(running_time, f"{actor_name}:", *message_parts)

        print_diagnostics(
            "Setup",
            f"Multi-process strategy: {actual_max_processes} processes × "
            f"{tasks_per_process} tasks = {actual_max_processes * tasks_per_process} concurrent WorkItems "
            f"({scanners_per_item} scanners/item = ~{actual_max_processes * tasks_per_process * scanners_per_item} total concurrency)",
        )

        work_queue_size = (
            max_queue_size if max_queue_size is not None else max_concurrent_work_items
        )

        # Create queues and store globally so forked processes inherit them directly.
        global _WORK_QUEUE, _RESULT_QUEUE
        _WORK_QUEUE = multiprocessing.Queue(work_queue_size)
        _RESULT_QUEUE = multiprocessing.Queue()

        # Non-None local aliases for type checking clarity
        assert _WORK_QUEUE is not None
        assert _RESULT_QUEUE is not None
        work_queue = _WORK_QUEUE
        result_queue = _RESULT_QUEUE

        def _work_item_info(transcript_info: TranscriptInfo) -> str:
            return f"({transcript_info.id})"

        async def _producer() -> None:
            """Producer task that feeds work items into the queue."""
            # First, send the item we peeked at
            if first_item is not None:
                await anyio.to_thread.run_sync(
                    work_queue.put,
                    (first_item.transcript_info, first_item.scanner_indices),
                )
                print_diagnostics(
                    "MP Producer",
                    f"Added work item {_work_item_info(first_item.transcript_info)}",
                )

            # Then send remaining items
            async for item in parse_jobs:
                await anyio.to_thread.run_sync(
                    work_queue.put,
                    (item.transcript_info, item.scanner_indices),
                )
                print_diagnostics(
                    "Producer",
                    f"Added work item {_work_item_info(item.transcript_info)}",
                )

            # Send sentinel values to signal worker TASKS to stop (one per task)
            sentinel_count = actual_max_processes * tasks_per_process
            for _ in range(sentinel_count):
                await anyio.to_thread.run_sync(work_queue.put, None)

            print_diagnostics("Producer", "FINISHED PRODUCING ALL WORK")

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
                        "Collector",
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
                    "Collector",
                    f"Recorded results for {_work_item_info(transcript_info)} (total: {items_processed})",
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
                            tasks_per_process,
                            worker_id,
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

                print_diagnostics("Main", "All worker processes completed")

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
    max_tasks: int,
    worker_id: int,
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

    def _work_item_info(transcript_info: TranscriptInfo) -> str:
        return f"({transcript_info.id})"

    async def _worker_main() -> None:
        """Main async function for worker process."""

        def print_diagnostics(actor_name: str, *message_parts: object) -> None:
            if diagnostics:
                running_time = f"+{time.time() - overall_start_time:.3f}s"
                print(running_time, f"P{worker_id} ", f"{actor_name}:", *message_parts)

        print_diagnostics(
            f"Worker P{worker_id}", f"Starting with {max_tasks} concurrent tasks"
        )

        # Create an async iterator that pulls ParseJob items from the work queue
        async def _parse_job_iterator() -> AsyncIterator[ParseJob]:
            """Yields ParseJob items from the work queue until sentinel is received."""
            items_pulled = 0
            while True:
                work_item_data: (
                    tuple[TranscriptInfo, AbstractSet[int]] | None
                ) = await anyio.to_thread.run_sync(_WORK_QUEUE.get)

                if work_item_data is None:
                    # Sentinel value - time to stop
                    print_diagnostics(
                        f"Worker P{worker_id}",
                        f"Received stop signal after pulling {items_pulled} items",
                    )
                    break

                transcript_info, scanner_indices = work_item_data
                items_pulled += 1
                print_diagnostics(
                    f"Worker P{worker_id}", f"Pulled {_work_item_info(transcript_info)}"
                )

                yield ParseJob(
                    transcript_info=transcript_info,
                    scanner_indices=scanner_indices,
                )

        # Create a queue-based recorder that sends results back to main process
        recorder = _QueueBasedRecorder(_RESULT_QUEUE)

        # Use single_process_strategy to coordinate the async tasks
        strategy = single_process_strategy(
            max_tasks=max_tasks,
            max_queue_size=None,  # Let single_process_strategy use its default
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
