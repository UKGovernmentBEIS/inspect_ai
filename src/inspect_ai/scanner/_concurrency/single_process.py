"""Work pool implementation for scanner operations.

This module now provides a strategy-based abstraction (``ConcurrencyStrategy``)
for executing scanner work. Currently only the asynchronous in-process task
strategy (``AsyncTaskStrategy``) is implemented. A future
``ProcessPoolStrategy`` will enable multi-process
execution without altering the public API.
"""

import time
from typing import AsyncIterator, Awaitable, Callable

import anyio
from anyio import create_task_group
from anyio.abc import TaskGroup
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from inspect_ai._util.registry import registry_info
from inspect_ai.util._anyio import inner_exception

from .._recorder.recorder import ScanRecorder
from .._scanner.result import ResultReport
from .common import ConcurrencyStrategy, WorkerMetrics, WorkItem


def single_process_strategy(
    *,
    max_tasks: int,
    max_queue_size: int | None,
    diagnostics: bool = False,
) -> ConcurrencyStrategy:
    """In-process asynchronous task-based execution strategy (function form)."""

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
        metrics = WorkerMetrics()
        overall_start_time = time.time()
        work_queue_size = max_queue_size if max_queue_size is not None else max_tasks

        work_item_send_stream: MemoryObjectSendStream[WorkItem]
        work_item_receive_stream: MemoryObjectReceiveStream[WorkItem]
        (
            work_item_send_stream,
            work_item_receive_stream,
        ) = anyio.create_memory_object_stream[WorkItem](work_queue_size)

        def _running_time() -> str:
            return f"+{time.time() - overall_start_time:.3f}s"

        def _metrics_info() -> str:
            return (
                f"workers: {metrics.worker_count} "
                f"(scanning: {metrics.workers_scanning}, "
                f"stalled: {metrics.workers_waiting}) "
                f"queue size: {work_item_receive_stream.statistics().current_buffer_used} "
            )

        def _work_item_info(item: WorkItem) -> str:
            scanner_names = ", ".join(
                registry_info(scanner).name for scanner in item.scanners
            )
            return f"({item.transcript_info.id}, [{scanner_names}])"

        async def _execute_work_item(item: WorkItem) -> None:
            try:
                metrics.workers_scanning += 1
                for name, results in (await item_processor(item)).items():
                    await recorder.record(item.transcript_info, name, results)
                    bump_progress()
            finally:
                metrics.workers_scanning -= 1

        async def _worker_task(
            work_item_stream: MemoryObjectReceiveStream[WorkItem], worker_id: int
        ) -> None:
            items_processed = 0
            try:
                while True:
                    queue_was_empty_start_time = (
                        time.time()
                        if work_item_receive_stream.statistics().current_buffer_used
                        == 0
                        else None
                    )
                    try:
                        metrics.workers_waiting += 1
                        with anyio.move_on_after(2.0) as timeout_scope:
                            item = await work_item_stream.receive()
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
                        f"{_running_time()} Worker #{worker_id} starting on {_work_item_info(item)} item{stall_phrase}\n\t{_metrics_info()}"
                    )
                    exec_start_time = time.time()
                    await _execute_work_item(item)
                    print_diagnostics(
                        f"{_running_time()} Worker #{worker_id} completed {_work_item_info(item)} in {(time.time() - exec_start_time):.3f}s"
                    )
                    items_processed += 1
                print_diagnostics(
                    f"{_running_time()} Worker #{worker_id} finished after processing {items_processed} items.\n\t{_metrics_info()}"
                )
            finally:
                metrics.worker_count -= 1

        async def _producer(tg: TaskGroup) -> None:
            async for new_item in work_items:
                backpressure = (
                    work_item_receive_stream.statistics().current_buffer_used
                    >= work_queue_size
                )
                await work_item_send_stream.send(new_item)
                print_diagnostics(
                    f"{_running_time()} Producer: Added work item {_work_item_info(new_item)} "
                    f"{' after backpressure relieved' if backpressure else ''}\n\t{_metrics_info()}"
                )
                if metrics.worker_count < max_tasks:
                    metrics.worker_count += 1
                    metrics.worker_id_counter += 1
                    tg.start_soon(
                        _worker_task,
                        work_item_receive_stream,
                        metrics.worker_id_counter,
                    )
                    print_diagnostics(
                        f"{_running_time()} Producer: Spawned worker #{metrics.worker_id_counter}\n\t{_metrics_info()}"
                    )
                await anyio.sleep(0)
            print_diagnostics(
                f"{_running_time()} Producer: FINISHED PRODUCING ALL WORK"
            )

        try:
            async with create_task_group() as tg:
                await _producer(tg)
        except Exception as ex:
            raise inner_exception(ex)

    return the_func
