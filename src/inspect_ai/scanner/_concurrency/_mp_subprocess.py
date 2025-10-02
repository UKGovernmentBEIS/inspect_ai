"""Worker subprocess entry point for multiprocessing scanner execution.

This module contains the code that runs in forked worker processes. The main
process spawns these workers via ProcessPoolExecutor, and they inherit shared
state from _mp_context through fork.
"""

from __future__ import annotations

import time
from typing import AsyncIterator

import anyio

from .._scanner.result import ResultReport
from .._transcript.types import TranscriptInfo
from . import _mp_common
from ._mp_common import run_sync_on_thread
from .common import ParseJob
from .single_process import single_process_strategy


def worker_process_main(
    max_concurrent_scans: int,
    worker_id: int,
) -> None:
    """Worker process main function.

    Runs in a forked subprocess with access to parent's memory.
    Uses single_process_strategy internally to coordinate async tasks.

    Args:
        max_concurrent_scans: Number of concurrent scans this worker should run
        worker_id: Unique identifier for this worker process
    """
    # Verify globals were initialized by parent process
    assert _mp_common.PARSE_FUNCTION is not None, "parse_function not initialized"
    assert _mp_common.SCAN_FUNCTION is not None, "scan_function not initialized"
    assert _mp_common.WORK_QUEUE is not None, "work_queue not initialized"
    assert _mp_common.RESULT_QUEUE is not None, "result_queue not initialized"

    async def _worker_main() -> None:
        """Main async function for worker process."""

        def print_diagnostics(actor_name: str, *message_parts: object) -> None:
            if _mp_common.DIAGNOSTICS:
                running_time = f"+{time.time() - _mp_common.OVERALL_START_TIME:.3f}s"
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
                work_item_data = await run_sync_on_thread(_mp_common.WORK_QUEUE.get)

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
                    f"Pulled {_mp_common.parse_job_info(work_item_data)}",
                )

                yield work_item_data

        # Use single_process_strategy to coordinate the async tasks
        strategy = single_process_strategy(
            max_concurrent_scans=max_concurrent_scans,
            buffer_multiple=_mp_common.BUFFER_MULTIPLE,
            diagnostics=_mp_common.DIAGNOSTICS,
            diag_prefix=f"P{worker_id}",
            overall_start_time=_mp_common.OVERALL_START_TIME,
        )

        # Define callback to send results back to main process via queue
        async def _record_to_queue(
            transcript: TranscriptInfo, scanner: str, results: list[ResultReport]
        ) -> None:
            _mp_common.RESULT_QUEUE.put((transcript, scanner, results))

        try:
            await strategy(
                record_results=_record_to_queue,
                parse_jobs=_parse_job_iterator(),
                parse_function=_mp_common.PARSE_FUNCTION,
                scan_function=_mp_common.SCAN_FUNCTION,
                bump_progress=lambda: None,  # Progress is bumped in main process
            )
        except Exception as ex:
            # Send exception back to main process
            _mp_common.RESULT_QUEUE.put(ex)
            raise

        print_diagnostics("All tasks completed")

        # Send completion sentinel to result collector
        _mp_common.RESULT_QUEUE.put(None)

    # Run the async event loop in this worker process
    anyio.run(_worker_main)
