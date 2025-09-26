"""Work pool implementation for scanner operations."""

import functools
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, NamedTuple, Protocol, Sequence

import anyio
from anyio import create_task_group
from anyio.abc import TaskGroup
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from ._recorder.recorder import ScanRecorder
from ._scanjob import ScanJob
from ._scanner.result import Result
from ._scanner.scanner import Scanner
from ._transcript.transcripts import Transcripts
from ._transcript.types import Transcript, TranscriptContent


class ScanReport(Protocol):
    async def __call__(self, results: Sequence[Result]) -> None: ...


class WorkItem(NamedTuple):
    """Represents a unit of work for scanning a transcript."""

    transcript: Transcript
    scanner: Scanner[Any]
    scanner_name: str
    report_callback: ScanReport


@dataclass
class WorkerMetrics:
    """Encapsulates all worker-related metrics."""

    worker_count: int = 0
    workers_waiting: int = 0
    workers_scanning: int = 0
    worker_id_counter: int = 0


async def scan_with_work_pool(
    job: ScanJob,
    recorder: ScanRecorder,
    max_tasks: int,
    max_queue_size: int,
    item_processor: Callable[[WorkItem], Awaitable[Result | None]],
    transcripts: Transcripts,
    content: TranscriptContent,
) -> None:
    """Manages concurrent scanner execution with backpressure and worker pooling.

    This function is responsible for HOW work is executed (concurrency management),
    not WHAT work needs to be done (which is determined by the caller).

    Core responsibilities:
    - Work item generation (iterating transcripts and scanners)
    - Checking for already-completed work via recorder
    - Lazy loading of transcripts as needed
    - Queue management and backpressure control
    - Worker lifecycle management (spawning, reusing, terminating)
    - Concurrency control and rate limiting
    - Metrics collection for worker states
    - Efficient work distribution across workers

    The caller (_scan.py) is responsible for:
    - Scanner-specific execution logic (via item_processor callback)
    - Transcript filtering and content determination
    - Progress reporting and UI updates
    - Overall scan orchestration and configuration

    This separation allows the pool to handle all concurrency and work generation
    concerns while the caller maintains control over scanner execution and UI.

    Args:
        job: The scan job containing scanners and configuration.
            Used to iterate through scanners and determine what work needs to be done.

        recorder: The scan recorder for checking if work is already complete
            and for recording results. Used to skip already-processed work items.

        max_tasks: Maximum number of concurrent worker tasks that can execute
            simultaneously. Controls the level of parallelism and resource usage.
            Workers are spawned dynamically up to this limit as work becomes available.

        max_queue_size: Size of the bounded work queue. Controls how many work items
            can be buffered before the producer blocks (backpressure). Higher values
            allow more lookahead and can improve throughput but use more memory.
            When the queue is full, the producer will block until workers consume items.

        item_processor: Async function to process work items.
            Should take a WorkItem and return a Result or None.
            Allows the caller to customize how scanners are executed while
            still leveraging the pool's concurrency management.

        transcripts: The transcripts to process.

        content: The union of all scanner content requirements, used to
            efficiently read only the necessary data from each transcript.
    """
    # Initialize metrics
    metrics = WorkerMetrics()
    overall_start_time = time.time()

    # Set work queue size (default to max_tasks if not specified)
    work_queue_size = max_queue_size if max_queue_size is not None else max_tasks

    # Create bounded work queue
    work_item_send_stream: MemoryObjectSendStream[WorkItem]
    work_item_receive_stream: MemoryObjectReceiveStream[WorkItem]
    (
        work_item_send_stream,
        work_item_receive_stream,
    ) = anyio.create_memory_object_stream[WorkItem](work_queue_size)

    def _running_time() -> str:
        """Get formatted runtime since start."""
        return f"+{time.time() - overall_start_time:.3f}s"

    def _metrics_info() -> str:
        """Get formatted metrics string for debugging."""
        return (
            f"workers: {metrics.worker_count} "
            f"(scanning: {metrics.workers_scanning}, "
            f"stalled: {metrics.workers_waiting}) "
            f"queue size: {work_item_receive_stream.statistics().current_buffer_used} "
        )

    def _work_item_info(item: WorkItem) -> str:
        """Get formatted work item info for debugging."""
        return f"{item.transcript.id, item.scanner_name}"

    async def _execute_work_item(item: WorkItem) -> None:
        """Call scanner with metrics tracking."""
        try:
            metrics.workers_scanning += 1
            await item_processor(item)
        finally:
            metrics.workers_scanning -= 1

    async def _worker_task(
        work_item_stream: MemoryObjectReceiveStream[WorkItem], worker_id: int
    ) -> None:
        """Worker that pulls work items from stream until empty."""
        items_processed = 0

        try:
            # Continuously process items from stream
            while True:
                queue_was_empty_start_time = (
                    time.time()
                    if work_item_receive_stream.statistics().current_buffer_used == 0
                    else None
                )

                # Use anyio's timeout handling
                try:
                    metrics.workers_waiting += 1
                    with anyio.move_on_after(2.0) as timeout_scope:
                        item = await work_item_stream.receive()
                finally:
                    metrics.workers_waiting -= 1

                # If timeout occurred, break out of loop
                if timeout_scope.cancelled_caught:
                    break

                stall_phrase = (
                    f" after stalling for {time.time() - queue_was_empty_start_time:.3f}s"
                    if queue_was_empty_start_time
                    else ""
                )
                print(
                    f"{_running_time()} Worker #{worker_id} starting on {_work_item_info(item)} item{stall_phrase}\n\t{_metrics_info()}"
                )

                exec_start_time = time.time()
                await _execute_work_item(item)
                print(
                    f"{_running_time()} Worker #{worker_id} completed {_work_item_info(item)} in {(time.time() - exec_start_time):.3f}s"
                )

                items_processed += 1

            print(
                f"{_running_time()} Worker #{worker_id} finished after processing {items_processed} items.\n\t{_metrics_info()}"
            )
        finally:
            metrics.worker_count -= 1

    async def _producer(
        tg: TaskGroup, transcripts: Transcripts, content: TranscriptContent
    ) -> None:
        """Produce work items and manage worker spawning."""
        for t in await transcripts.index():
            transcript: Transcript | None = None
            for name, scanner in job.scanners.items():
                # Skip if already recorded
                if await recorder.is_recorded(t, name):
                    continue

                # Lazy load transcript on first scanner that needs it
                if transcript is None:
                    s_time = time.time()
                    transcript = await transcripts.read(t, content)
                    if (read_time := time.time() - s_time) > 1:
                        print(
                            f"{_running_time()} Producer: Read transcript {t.id} in {read_time:.3f}s"
                        )

                # Check for backpressure
                backpressure = (
                    work_item_receive_stream.statistics().current_buffer_used
                    >= work_queue_size
                )

                new_item = WorkItem(
                    transcript=transcript,
                    scanner=scanner,
                    scanner_name=name,
                    report_callback=functools.partial(recorder.record, t, name),
                )

                # This send will block if queue is full (backpressure)
                await work_item_send_stream.send(new_item)

                print(
                    f"{_running_time()} Producer: Added work item {_work_item_info(new_item)} "
                    f"{' after backpressure relieved' if backpressure else ''}\n\t{_metrics_info()}"
                )

                # Spawn workers as needed
                if metrics.worker_count < max_tasks:
                    metrics.worker_count += 1
                    metrics.worker_id_counter += 1

                    tg.start_soon(
                        _worker_task,
                        work_item_receive_stream,
                        metrics.worker_id_counter,
                    )
                    print(
                        f"{_running_time()} Producer: Spawned worker #{metrics.worker_id_counter}\n\t{_metrics_info()}"
                    )

                # Yield control to allow other tasks to run
                await anyio.sleep(0)

        print(f"{_running_time()} Producer: FINISHED PRODUCING ALL WORK")

    # Execute the scan with worker pool management
    try:
        async with create_task_group() as tg:
            await _producer(tg, transcripts, content)
    except Exception as ex:
        print(f"caught {ex}")
        raise
