"""Multi-process work pool implementation for scanner operations.

This module provides a process-based concurrency strategy using fork-based
ProcessPoolExecutor. Each worker process runs its own async event loop with
multiple concurrent tasks, allowing efficient parallel execution of scanner work.
"""

from __future__ import annotations

# pylint: disable=unsubscriptable-object
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING, Any, AsyncIterator, Awaitable, Callable

if TYPE_CHECKING:
    from multiprocessing.queues import Queue as MPQueue

import anyio
from anyio import create_task_group

from inspect_ai._util.registry import registry_info
from inspect_ai.util._anyio import inner_exception

from .._recorder.recorder import ScanRecorder
from .._scanner.result import ResultReport
from .._transcript.types import TranscriptContent, TranscriptInfo
from .common import ConcurrencyStrategy, WorkItem

# Module-level storage for invariant data (accessible after fork)
_ITEM_PROCESSOR: (
    Callable[[WorkItem], Awaitable[dict[str, list[ResultReport]]]] | None
) = None
_ALL_SCANNERS: list[Any] | None = None
_UNION_CONTENT: TranscriptContent | None = None
# Module-level queues (avoid passing through ProcessPoolExecutor which attempts to pickle)
_WORK_QUEUE: "MPQueue[TranscriptInfo | None]" | None = None
_RESULT_QUEUE: (
    "MPQueue[tuple[TranscriptInfo, dict[str, list[ResultReport]]] | Exception | None]"
    | None
) = None


def multi_process_strategy(
    *,
    max_tasks: int,
    max_processes: int,
    max_queue_size: int | None,
    diagnostics: bool = True,
) -> ConcurrencyStrategy:
    """Multi-process execution strategy with nested async concurrency.

    Args:
        max_tasks: Target total scanner concurrency across all processes
        max_processes: Number of worker processes to spawn
        max_queue_size: Maximum work queue size for backpressure
        diagnostics: Whether to print diagnostic information
    """

    def print_diagnostics(*values: object) -> None:
        if diagnostics:
            print(*values)

    async def the_func(
        *,
        recorder: ScanRecorder,
        work_items: AsyncIterator[WorkItem],
        item_processor: Callable[[WorkItem], Awaitable[dict[str, list[ResultReport]]]],
        bump_progress: Callable[[], None],
    ) -> None:
        global _ITEM_PROCESSOR, _ALL_SCANNERS, _UNION_CONTENT
        _ITEM_PROCESSOR = item_processor

        # Peek at first work item to determine scanner count and calculate concurrency
        first_item: WorkItem | None = None
        try:
            first_item = await work_items.__anext__()
        except StopAsyncIteration:
            # No work items, nothing to do
            return

        scanners_per_item = len(first_item.scanners)
        if scanners_per_item == 0:
            return

        # Store invariant data globally so workers can reconstruct WorkItems
        _ALL_SCANNERS = list(first_item.scanners)
        _UNION_CONTENT = first_item.union_content

        # Calculate how many WorkItems to process concurrently
        # Since each WorkItem runs scanners_per_item scanners concurrently,
        # we need: max_concurrent_work_items = max_tasks / scanners_per_item
        max_concurrent_work_items = max(1, max_tasks // scanners_per_item)
        tasks_per_process = max(1, max_concurrent_work_items // max_processes)

        # Adjust max_processes if needed to match desired concurrency
        actual_max_processes = min(max_processes, max_concurrent_work_items)

        print_diagnostics(
            f"Multi-process strategy: {actual_max_processes} processes × "
            f"{tasks_per_process} tasks = {actual_max_processes * tasks_per_process} concurrent WorkItems "
            f"({scanners_per_item} scanners/item = ~{actual_max_processes * tasks_per_process * scanners_per_item} total concurrency)"
        )

        overall_start_time = time.time()
        work_queue_size = (
            max_queue_size if max_queue_size is not None else max_concurrent_work_items
        )

        # Create queues and store globally so forked processes inherit them directly.
        global _WORK_QUEUE, _RESULT_QUEUE
        _WORK_QUEUE = multiprocessing.Queue(work_queue_size)  # type: ignore[assignment]
        _RESULT_QUEUE = multiprocessing.Queue()  # type: ignore[assignment]

        # Non-None local aliases for type checking clarity
        assert _WORK_QUEUE is not None
        assert _RESULT_QUEUE is not None
        assert _ALL_SCANNERS is not None
        work_queue = _WORK_QUEUE
        result_queue = _RESULT_QUEUE
        all_scanners = _ALL_SCANNERS

        def _running_time() -> str:
            return f"+{time.time() - overall_start_time:.3f}s"

        def _work_item_info(transcript_info: TranscriptInfo) -> str:
            scanner_names = ", ".join(
                registry_info(scanner).name for scanner in all_scanners
            )
            return f"({transcript_info.id}, [{scanner_names}])"

        async def _producer() -> None:
            """Producer task that feeds work items into the queue."""
            # First, send the item we peeked at
            if first_item is not None:
                await anyio.to_thread.run_sync(
                    work_queue.put,
                    first_item.transcript_info,  # type: ignore[arg-type]
                )
                print_diagnostics(
                    f"{_running_time()} Producer: Added work item {_work_item_info(first_item.transcript_info)}"
                )

            # Then send remaining items
            async for item in work_items:
                await anyio.to_thread.run_sync(
                    work_queue.put,
                    item.transcript_info,  # type: ignore[arg-type]
                )
                print_diagnostics(
                    f"{_running_time()} Producer: Added work item {_work_item_info(item.transcript_info)}"
                )

            # Send sentinel values to signal worker TASKS to stop (one per task)
            sentinel_count = actual_max_processes * tasks_per_process
            for _ in range(sentinel_count):
                await anyio.to_thread.run_sync(work_queue.put, None)  # type: ignore[arg-type]

            print_diagnostics(
                f"{_running_time()} Producer: FINISHED PRODUCING ALL WORK"
            )

        async def _result_collector() -> None:
            """Collector task that receives results and records them."""
            items_processed = 0
            workers_finished = 0

            while workers_finished < actual_max_processes:
                result = await anyio.to_thread.run_sync(result_queue.get)  # type: ignore[arg-type]

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

                transcript_info, scanner_results = result
                for name, results in scanner_results.items():
                    await recorder.record(transcript_info, name, results)
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
                            diagnostics,
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
            _ITEM_PROCESSOR = None
            _ALL_SCANNERS = None
            _UNION_CONTENT = None

    return the_func


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
    global _ITEM_PROCESSOR, _ALL_SCANNERS, _UNION_CONTENT, _WORK_QUEUE, _RESULT_QUEUE
    assert _ITEM_PROCESSOR is not None, "item_processor not initialized"
    assert _ALL_SCANNERS is not None, "scanners not initialized"
    assert _UNION_CONTENT is not None, "union_content not initialized"
    assert _WORK_QUEUE is not None, "work_queue not initialized"
    assert _RESULT_QUEUE is not None, "result_queue not initialized"
    item_processor = _ITEM_PROCESSOR

    def print_diagnostics_worker(*values: object) -> None:
        if diagnostics:
            print(*values)

    def _running_time() -> str:
        return f"+{time.time() - start_time:.3f}s"

    def _work_item_info(transcript_info: TranscriptInfo) -> str:
        scanner_names = ", ".join(
            registry_info(scanner).name
            for scanner in _ALL_SCANNERS  # type: ignore[arg-type]
        )
        return f"({transcript_info.id}, [{scanner_names}])"

    async def _worker_task(task_id: int) -> None:
        """Async task that pulls work items and processes them."""
        items_processed = 0
        try:
            while True:
                # Get transcript info from queue (blocking, but run in thread to not block event loop)
                transcript_info: TranscriptInfo | None = await anyio.to_thread.run_sync(
                    _WORK_QUEUE.get  # type: ignore[arg-type]
                )

                if transcript_info is None:
                    # Sentinel value - time to stop (one per worker task; do NOT requeue)
                    print_diagnostics_worker(
                        f"{_running_time()} Worker P{worker_id}:T{task_id}: Received stop signal, "
                        f"processed {items_processed} items"
                    )
                    break

                # Reconstruct WorkItem from globals + received transcript_info
                item = WorkItem(
                    transcript_info=transcript_info,
                    union_content=_UNION_CONTENT,  # type: ignore[arg-type]
                    scanners=_ALL_SCANNERS,  # type: ignore[arg-type]
                )

                print_diagnostics_worker(
                    f"{_running_time()} Worker P{worker_id}:T{task_id}: Starting {_work_item_info(transcript_info)}"
                )
                exec_start_time = time.time()

                try:
                    # Process the work item (this is where scanners run)
                    results = await item_processor(item)

                    # Send results back to main process
                    await anyio.to_thread.run_sync(
                        _RESULT_QUEUE.put,
                        (transcript_info, results),  # type: ignore[arg-type]
                    )

                    print_diagnostics_worker(
                        f"{_running_time()} Worker P{worker_id}:T{task_id}: Completed {_work_item_info(transcript_info)} "
                        f"in {time.time() - exec_start_time:.3f}s"
                    )
                    items_processed += 1

                except Exception as ex:
                    # Send exception back to main process
                    await anyio.to_thread.run_sync(_RESULT_QUEUE.put, ex)  # type: ignore[arg-type]
                    break

        except Exception as ex:
            # Send exception back to main process
            try:
                await anyio.to_thread.run_sync(_RESULT_QUEUE.put, ex)  # type: ignore[arg-type]
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
        await anyio.to_thread.run_sync(_RESULT_QUEUE.put, None)  # type: ignore[arg-type]

    # Run the async event loop in this worker process
    anyio.run(_worker_main)
