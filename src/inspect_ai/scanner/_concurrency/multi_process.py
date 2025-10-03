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
from typing import AsyncIterator, Awaitable, Callable, cast

import anyio
from anyio import create_task_group

from inspect_ai.util._anyio import inner_exception

from .._scanner.result import ResultReport
from .._transcript.types import TranscriptInfo
from . import _mp_common
from ._mp_common import run_sync_on_thread
from ._mp_subprocess import subprocess_main
from .common import ConcurrencyStrategy, ParseJob, ScannerJob, WorkerMetrics


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
    if max_processes is None:
        max_processes = multiprocessing.cpu_count()

    async def the_func(
        *,
        record_results: Callable[
            [TranscriptInfo, str, list[ResultReport]], Awaitable[None]
        ],
        parse_jobs: AsyncIterator[ParseJob],
        parse_function: Callable[[ParseJob], Awaitable[list[ScannerJob]]],
        scan_function: Callable[[ScannerJob], Awaitable[list[ResultReport]]],
        bump_progress: Callable[[], None],
        update_metrics: Callable[[WorkerMetrics], None] | None = None,
    ) -> None:
        # Enforce single active instance - check if ipc_context is already set
        # (ipc_context is cast(IPCContext, None) initially, so we check truthiness)
        if _mp_common.ipc_context is not None:
            raise RuntimeError(
                "Another multi_process_strategy is already running. "
                "Only one instance can be active at a time."
            )

        # TODO: Obviously, hack_factor is just for exploration for now
        hack_factor = 3
        concurrent_scans_per_process = hack_factor * max(
            1, max_concurrent_scans // max_processes
        )
        # Initialize shared IPC context that will be inherited by forked workers
        _mp_common.ipc_context = _mp_common.IPCContext(
            parse_function=parse_function,
            scan_function=scan_function,
            concurrent_scans_per_process=concurrent_scans_per_process,
            buffer_multiple=buffer_multiple,
            diagnostics=diagnostics,
            overall_start_time=time.time(),
            parse_job_queue=multiprocessing.Queue(),
            result_queue=multiprocessing.Queue(),
        )

        def print_diagnostics(actor_name: str, *message_parts: object) -> None:
            if diagnostics:
                running_time = (
                    f"+{time.time() - _mp_common.ipc_context.overall_start_time:.3f}s"
                )
                print(running_time, f"{actor_name}:", *message_parts)

        print_diagnostics(
            "Setup",
            f"Multi-process strategy: {max_processes} processes × "
            f"{concurrent_scans_per_process} scans = {max_processes * concurrent_scans_per_process} total concurrency",
        )

        # Queues are part of IPC context and inherited by forked processes.
        # ParseJob queue is unbounded - ParseJobs are tiny metadata objects with no backpressure needed.
        # Real backpressure happens inside each worker via single-process strategy's ScannerJob buffer.
        work_queue = _mp_common.ipc_context.parse_job_queue
        result_queue = _mp_common.ipc_context.result_queue

        async def _producer() -> None:
            """Producer task that feeds work items into the queue."""
            async for item in parse_jobs:
                work_queue.put(item)
                print_diagnostics(
                    "MP Producer",
                    f"Added ParseJob {_mp_common.parse_job_info(item)}",
                )

            # Send sentinel values to signal worker tasks to stop (one per task)
            sentinel_count = max_processes * concurrent_scans_per_process
            for _ in range(sentinel_count):
                work_queue.put(None)

            print_diagnostics("MP Producer", "FINISHED PRODUCING ALL WORK")

        async def _result_collector() -> None:
            """Collector task that receives results and records them."""
            items_processed = 0
            workers_finished = 0

            while workers_finished < max_processes:
                result = await run_sync_on_thread(result_queue.get)

                if result is None:
                    # Sentinel from a worker process indicating it's done
                    workers_finished += 1
                    print_diagnostics(
                        "MP Collector",
                        f"Worker finished ({workers_finished}/{max_processes})",
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
                max_workers=max_processes, mp_context=ctx
            ) as executor:
                # Submit worker processes
                futures = []
                for worker_id in range(max_processes):
                    try:
                        # The only arguments passed to subprocess_main via this
                        # .submit should be subprocess specific. All subprocess invariant
                        # data used by the subprocess should be in the IPCContext
                        futures.append(executor.submit(subprocess_main, worker_id))
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
            # Reset IPC context to None to indicate no strategy is active
            # This also prevents leakage between runs and releases the implicit
            # lock. See comment in _mp_common.py for the need for/value of the cast.
            _mp_common.ipc_context = cast(_mp_common.IPCContext, None)

    return the_func
