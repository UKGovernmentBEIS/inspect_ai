"""Work pool implementation for scanner operations."""

import time
from dataclasses import dataclass
from typing import Awaitable, Callable, NamedTuple

import anyio
from anyio import create_task_group
from anyio.abc import TaskGroup
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from inspect_ai._util.registry import registry_info

from ._recorder.recorder import ScanRecorder
from ._scancontext import ScanContext
from ._scanner.result import Result
from ._scanner.scanner import Scanner, config_for_scanner
from ._scanner.types import ScannerInput
from ._transcript.transcripts import Transcripts
from ._transcript.types import TranscriptContent, TranscriptInfo
from ._transcript.util import union_transcript_contents


class WorkItem(NamedTuple):
    """Represents a unit of work for reading a transcript and scanning with multiple scanners.

    This groups all scanners that need to process the same transcript, allowing
    the transcript to be loaded once and reused across scanners within a single
    worker process.
    """

    transcript_info: TranscriptInfo
    union_content: TranscriptContent
    scanners: list[Scanner[ScannerInput]]


@dataclass
class WorkerMetrics:
    """Encapsulates all worker-related metrics."""

    worker_count: int = 0
    workers_waiting: int = 0
    workers_scanning: int = 0
    worker_id_counter: int = 0


async def scan_with_work_pool(
    context: ScanContext,
    recorder: ScanRecorder,
    max_tasks: int,
    max_queue_size: int,
    item_processor: Callable[[WorkItem], Awaitable[dict[str, list[Result]]]],
    progress: Callable[[], None],
    transcripts: Transcripts,
    diagnostics: bool = False,
) -> None:
    """Manages concurrent scanner execution with backpressure and worker pooling.

    This function is responsible for HOW work is executed (concurrency management),
    not WHAT work needs to be done (which is determined by the caller).

    Core responsibilities:
    - Work item generation (grouping scanners by transcript)
    - Checking for already-completed work via recorder
    - Queue management and backpressure control
    - Worker lifecycle management (spawning, reusing, terminating)
    - Concurrency control and rate limiting
    - Metrics collection for worker states
    - Efficient work distribution across workers

    The caller (_scan.py) is responsible for:
    - Transcript loading (within item_processor callback)
    - Scanner-specific execution logic (via item_processor callback)
    - Transcript filtering and content determination
    - Progress reporting and UI updates
    - Overall scan orchestration and configuration

    This separation allows the pool to handle all concurrency and work generation
    concerns while the caller maintains control over transcript loading, scanner
    execution, and UI.

    Args:
        context: The context containing scanners and configuration.
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
            Takes a WorkItem (containing TranscriptInfo and scanners) and loads
            the transcript, executes all scanners, and returns a dict mapping
            scanner names to lists of results. Allows the caller to customize
            transcript loading and scanner execution while still leveraging the
            pool's concurrency management.

        progress: Callable to report progress for both skipped and executed work items.
            Called once per scanner completion.

        transcripts: The transcripts to process.

        diagnostics: Print work pool diagnostics.
    """

    # helper to print diagnostics
    def print_diagnostics(*values: object) -> None:
        if diagnostics:
            print(*values)

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
        scanner_names = ", ".join(
            registry_info(scanner).name for scanner in item.scanners
        )
        return f"({item.transcript_info.id}, [{scanner_names}])"

    async def _execute_work_item(item: WorkItem) -> None:
        """Call scanner with metrics tracking and record results."""
        try:
            metrics.workers_scanning += 1
            for name, results in (await item_processor(item)).items():
                await recorder.record(item.transcript_info, name, results)
                progress()
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

    async def _producer(tg: TaskGroup, transcripts: Transcripts) -> None:
        """Produce work items and manage worker spawning."""
        union_content = union_transcript_contents(
            [
                config_for_scanner(scanner).content
                for scanner in context.scanners.values()
            ]
        )

        for transcript_info in await transcripts.index():
            # Collect scanners that need to process this transcript
            scanners_for_transcript: list[Scanner[ScannerInput]] = []

            for name, scanner in context.scanners.items():
                # Skip if already recorded
                if await recorder.is_recorded(transcript_info, name):
                    progress()
                    continue

                # Add scanner to this transcript's work item
                scanners_for_transcript.append(scanner)

            # Skip if no scanners need this transcript
            if not scanners_for_transcript:
                continue

            # Check for backpressure
            backpressure = (
                work_item_receive_stream.statistics().current_buffer_used
                >= work_queue_size
            )

            new_item = WorkItem(
                transcript_info=transcript_info,
                union_content=union_content,
                scanners=scanners_for_transcript,
            )

            # This send will block if queue is full (backpressure)
            await work_item_send_stream.send(new_item)

            print_diagnostics(
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
                print_diagnostics(
                    f"{_running_time()} Producer: Spawned worker #{metrics.worker_id_counter}\n\t{_metrics_info()}"
                )

            # Yield control to allow other tasks to run
            await anyio.sleep(0)

        print_diagnostics(f"{_running_time()} Producer: FINISHED PRODUCING ALL WORK")

    # Execute the scan with worker pool management
    try:
        async with create_task_group() as tg:
            await _producer(tg, transcripts)
    except Exception as ex:
        print(f"caught {ex}")
        raise
