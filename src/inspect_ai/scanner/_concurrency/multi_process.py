"""Multi-process work pool implementation for scanner operations.

This module provides a process-based concurrency strategy using fork-based
ProcessPoolExecutor. Each worker process runs its own async event loop with
multiple concurrent tasks, allowing efficient parallel execution of scanner work.

Note: multiprocessing.Queue.get() is blocking with no async support, so we use
anyio.to_thread.run_sync to wrap .get() calls to prevent blocking the event loop.
Queue.put() on unbounded queues (our case) only blocks briefly for lock contention,
so threading is unnecessary.
See: https://stackoverflow.com/questions/75270606
"""

from __future__ import annotations

import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor
from typing import AsyncIterator, Awaitable, Callable

import anyio
from anyio import create_task_group

from inspect_ai.util._anyio import inner_exception

from .._scanner.result import ResultReport
from .._transcript.types import TranscriptInfo
from . import _mp_common
from ._mp_common import run_sync_on_thread
from ._mp_subprocess import worker_process_main
from .common import ConcurrencyStrategy, ParseJob, ScannerJob


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
        record_results: Callable[
            [TranscriptInfo, str, list[ResultReport]], Awaitable[None]
        ],
        parse_jobs: AsyncIterator[ParseJob],
        parse_function: Callable[[ParseJob], Awaitable[list[ScannerJob]]],
        scan_function: Callable[[ScannerJob], Awaitable[list[ResultReport]]],
        bump_progress: Callable[[], None],
    ) -> None:
        # Initialize shared context that will be inherited by forked workers
        _mp_common.PARSE_FUNCTION = parse_function
        _mp_common.SCAN_FUNCTION = scan_function
        _mp_common.BUFFER_MULTIPLE = buffer_multiple
        _mp_common.DIAGNOSTICS = diagnostics
        _mp_common.OVERALL_START_TIME = time.time()

        # Auto-detect number of processes if not specified
        actual_max_processes = (
            max_processes if max_processes is not None else multiprocessing.cpu_count()
        )

        # Calculate scans per process
        hack_factor = 3
        concurrent_scans_per_process = hack_factor * max(
            1, max_concurrent_scans // actual_max_processes
        )

        def print_diagnostics(actor_name: str, *message_parts: object) -> None:
            if diagnostics:
                running_time = f"+{time.time() - _mp_common.OVERALL_START_TIME:.3f}s"
                print(running_time, f"{actor_name}:", *message_parts)

        print_diagnostics(
            "Setup",
            f"Multi-process strategy: {actual_max_processes} processes × "
            f"{concurrent_scans_per_process} scans = {actual_max_processes * concurrent_scans_per_process} total concurrency",
        )

        # Create queues and store in shared context so forked processes inherit them.
        # ParseJob queue is unbounded - ParseJobs are tiny metadata objects with no backpressure needed.
        # Real backpressure happens inside each worker via single-process strategy's ScannerJob buffer.
        _mp_common.WORK_QUEUE = multiprocessing.Queue()
        _mp_common.RESULT_QUEUE = multiprocessing.Queue()

        # Non-None local aliases for convenience
        work_queue = _mp_common.WORK_QUEUE
        result_queue = _mp_common.RESULT_QUEUE

        async def _producer() -> None:
            """Producer task that feeds work items into the queue."""
            async for item in parse_jobs:
                work_queue.put(item)
                print_diagnostics(
                    "MP Producer",
                    f"Added ParseJob {_mp_common.parse_job_info(item)}",
                )

            # Send sentinel values to signal worker tasks to stop (one per task)
            sentinel_count = actual_max_processes * concurrent_scans_per_process
            for _ in range(sentinel_count):
                work_queue.put(None)

            print_diagnostics("MP Producer", "FINISHED PRODUCING ALL WORK")

        async def _result_collector() -> None:
            """Collector task that receives results and records them."""
            items_processed = 0
            workers_finished = 0

            while workers_finished < actual_max_processes:
                result = await run_sync_on_thread(result_queue.get)

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
                await record_results(transcript_info, scanner_name, results)
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
                            worker_process_main,
                            concurrent_scans_per_process,
                            worker_id,
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
            # Cleanup shared context to prevent leakage between runs
            _mp_common.WORK_QUEUE = None
            _mp_common.RESULT_QUEUE = None
            _mp_common.PARSE_FUNCTION = None
            _mp_common.SCAN_FUNCTION = None
            _mp_common.BUFFER_MULTIPLE = None
            _mp_common.DIAGNOSTICS = False
            _mp_common.OVERALL_START_TIME = 0.0

    return the_func
