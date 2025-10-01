"""Multi-process work pool implementation for scanner operations.

This module provides a process-based concurrency strategy using fork-based
ProcessPoolExecutor. Each worker process runs its own async event loop with
multiple concurrent tasks, allowing efficient parallel execution of scanner work.
"""

from __future__ import annotations

import multiprocessing
import time
from collections.abc import Set as AbstractSet
from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING, AsyncIterator, Awaitable, Callable

if TYPE_CHECKING:
    from multiprocessing.queues import Queue as MPQueue

import anyio
from anyio import create_task_group

from inspect_ai._util.registry import registry_info
from inspect_ai.util._anyio import inner_exception

from .._recorder.recorder import ScanRecorder
from .._scanner.result import ResultReport
from .._transcript.types import TranscriptInfo
from .common import ParseJob, ScannerJob

# Module-level storage for invariant data (accessible after fork)
_PARSE_FUNCTION: Callable[[ParseJob], Awaitable[list[ScannerJob]]] | None = None
_SCAN_FUNCTION: Callable[[ScannerJob], Awaitable[list[ResultReport]]] | None = None
# Module-level queues (avoid passing through ProcessPoolExecutor which attempts to pickle)
_WORK_QUEUE: "MPQueue[tuple[TranscriptInfo, AbstractSet[int]] | None]" | None = None
_RESULT_QUEUE: (
    "MPQueue[tuple[TranscriptInfo, str, list[ResultReport]] | Exception | None]" | None
) = None


class MultiProcessStrategy:
    """Multi-process execution strategy with nested async concurrency."""

    def __init__(
        self,
        *,
        max_tasks: int,
        max_processes: int,
        max_queue_size: int | None,
        diagnostics: bool = True,
    ) -> None:
        self.max_tasks = max_tasks
        self.max_processes = max_processes
        self.max_queue_size = max_queue_size
        self.diagnostics = diagnostics

    async def __call__(
        self,
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
        max_concurrent_work_items = max(1, self.max_tasks // scanners_per_item)
        tasks_per_process = max(1, max_concurrent_work_items // self.max_processes)

        # Adjust max_processes if needed to match desired concurrency
        actual_max_processes = min(self.max_processes, max_concurrent_work_items)

        def print_diagnostics(*values: object) -> None:
            if self.diagnostics:
                print(*values)

        print_diagnostics(
            f"Multi-process strategy: {actual_max_processes} processes × "
            f"{tasks_per_process} tasks = {actual_max_processes * tasks_per_process} concurrent WorkItems "
            f"({scanners_per_item} scanners/item = ~{actual_max_processes * tasks_per_process * scanners_per_item} total concurrency)"
        )

        overall_start_time = time.time()
        work_queue_size = (
            self.max_queue_size
            if self.max_queue_size is not None
            else max_concurrent_work_items
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

        def _running_time() -> str:
            return f"+{time.time() - overall_start_time:.3f}s"

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
                    f"{_running_time()} Producer: Added work item {_work_item_info(first_item.transcript_info)}"
                )

            # Then send remaining items
            async for item in parse_jobs:
                await anyio.to_thread.run_sync(
                    work_queue.put,
                    (item.transcript_info, item.scanner_indices),
                )
                print_diagnostics(
                    f"{_running_time()} Producer: Added work item {_work_item_info(item.transcript_info)}"
                )

            # Send sentinel values to signal worker TASKS to stop (one per task)
            sentinel_count = actual_max_processes * tasks_per_process
            for _ in range(sentinel_count):
                await anyio.to_thread.run_sync(work_queue.put, None)

            print_diagnostics(
                f"{_running_time()} Producer: FINISHED PRODUCING ALL WORK"
            )

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
                        f"{_running_time()} Collector: Worker finished "
                        f"({workers_finished}/{actual_max_processes})"
                    )
                    continue

                if isinstance(result, Exception):
                    raise result

                transcript_info, scanner_name, results = result
                await recorder.record(transcript_info, scanner_name, results)
                bump_progress()

                items_processed += 1
                print_diagnostics(
                    f"{_running_time()} Collector: Recorded results for {_work_item_info(transcript_info)} "
                    f"(total: {items_processed})"
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
                            self.diagnostics,
                            overall_start_time,
                        )
                        futures.append(future)
                        print_diagnostics(
                            f"{_running_time()} Main: Spawned worker process #{worker_id}"
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

                print_diagnostics(
                    f"{_running_time()} Main: All worker processes completed"
                )

        except Exception as ex:
            raise inner_exception(ex)
        finally:
            # Cleanup globals to prevent leakage between runs
            _WORK_QUEUE = None
            _RESULT_QUEUE = None
            _PARSE_FUNCTION = None
            _SCAN_FUNCTION = None


def multi_process_strategy(
    *,
    max_tasks: int,
    max_processes: int,
    max_queue_size: int | None,
    diagnostics: bool = True,
) -> MultiProcessStrategy:
    """Multi-process execution strategy with nested async concurrency.

    Args:
        max_tasks: Target total scanner concurrency across all processes
        max_processes: Number of worker processes to spawn
        max_queue_size: Maximum work queue size for backpressure
        diagnostics: Whether to print diagnostic information
    """
    return MultiProcessStrategy(
        max_tasks=max_tasks,
        max_processes=max_processes,
        max_queue_size=max_queue_size,
        diagnostics=diagnostics,
    )


def _worker_process_main(
    max_tasks: int,
    worker_id: int,
    diagnostics: bool,
    start_time: float,
) -> None:
    """Worker process main function.

    Runs in a forked subprocess with access to parent's memory.
    Creates an async event loop and spawns multiple concurrent tasks.
    """
    global _PARSE_FUNCTION, _SCAN_FUNCTION, _WORK_QUEUE, _RESULT_QUEUE
    assert _PARSE_FUNCTION is not None, "parse_function not initialized"
    assert _SCAN_FUNCTION is not None, "scan_function not initialized"
    assert _WORK_QUEUE is not None, "work_queue not initialized"
    assert _RESULT_QUEUE is not None, "result_queue not initialized"
    parse_function = _PARSE_FUNCTION
    scan_function = _SCAN_FUNCTION

    def print_diagnostics_worker(*values: object) -> None:
        if diagnostics:
            print(*values)

    def _running_time() -> str:
        return f"+{time.time() - start_time:.3f}s"

    def _work_item_info(transcript_info: TranscriptInfo) -> str:
        return f"({transcript_info.id})"

    async def _worker_task(task_id: int) -> None:
        """Async task that pulls work items and processes them."""
        items_processed = 0
        try:
            while True:
                # Get work item data from queue (blocking, but run in thread to not block event loop)
                work_item_data: (
                    tuple[TranscriptInfo, AbstractSet[int]] | None
                ) = await anyio.to_thread.run_sync(_WORK_QUEUE.get)

                if work_item_data is None:
                    # Sentinel value - time to stop (one per worker task; do NOT requeue)
                    print_diagnostics_worker(
                        f"{_running_time()} Worker P{worker_id}:T{task_id}: Received stop signal, "
                        f"processed {items_processed} items"
                    )
                    break

                transcript_info, scanner_indices = work_item_data

                # Reconstruct WorkItem from globals + received data
                item = ParseJob(
                    transcript_info=transcript_info,
                    scanner_indices=scanner_indices,
                )

                print_diagnostics_worker(
                    f"{_running_time()} Worker P{worker_id}:T{task_id}: Starting {_work_item_info(transcript_info)}"
                )
                exec_start_time = time.time()

                try:
                    # Step 1: Parse the transcript to get scanner jobs
                    scanner_jobs = await parse_function(item)

                    # Step 2: Execute each scanner job and send results
                    for scanner_job in scanner_jobs:
                        scanner_name = registry_info(scanner_job.scanner).name
                        results = await scan_function(scanner_job)

                        # Send results back to main process (one result per scanner)
                        await anyio.to_thread.run_sync(
                            _RESULT_QUEUE.put,
                            (transcript_info, scanner_name, results),
                        )

                    print_diagnostics_worker(
                        f"{_running_time()} Worker P{worker_id}:T{task_id}: Completed {_work_item_info(transcript_info)} "
                        f"in {time.time() - exec_start_time:.3f}s"
                    )
                    items_processed += 1

                except Exception as ex:
                    # Send exception back to main process
                    await anyio.to_thread.run_sync(_RESULT_QUEUE.put, ex)
                    break

        except Exception as ex:
            # Send exception back to main process
            try:
                await anyio.to_thread.run_sync(_RESULT_QUEUE.put, ex)
            except Exception:
                pass  # Best effort

    async def _worker_main() -> None:
        """Main async function for worker process."""
        print_diagnostics_worker(
            f"{_running_time()} Worker P{worker_id}: Starting with {max_tasks} concurrent tasks"
        )

        async with create_task_group() as tg:
            for task_id in range(max_tasks):
                tg.start_soon(_worker_task, task_id)

        print_diagnostics_worker(
            f"{_running_time()} Worker P{worker_id}: All tasks completed"
        )

        # Send completion sentinel to result collector
        await anyio.to_thread.run_sync(_RESULT_QUEUE.put, None)

    # Run the async event loop in this worker process
    anyio.run(_worker_main)
