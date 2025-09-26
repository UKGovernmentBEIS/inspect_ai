"""Work pool implementation for scanner operations."""

import functools
import time
from dataclasses import dataclass
from typing import Any, NamedTuple, Protocol, Sequence

import anyio
from anyio import create_task_group
from anyio.abc import TaskGroup
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from rich.progress import Progress

from inspect_ai.scanner._recorder.recorder import ScanRecorder
from inspect_ai.scanner._scanjob import ScanJob
from inspect_ai.scanner._scanner.result import Result
from inspect_ai.scanner._scanner.scanner import Scanner, config_for_scanner
from inspect_ai.scanner._transcript.transcripts import Transcripts
from inspect_ai.scanner._transcript.types import Transcript
from inspect_ai.scanner._transcript.util import (
    filter_transcript,
    union_transcript_contents,
)


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

    worker_task_count: int = 0
    workers_waiting: int = 0
    workers_scanning: int = 0
    workers_reporting: int = 0
    worker_id_counter: int = 0


class ScannerWorkPool:
    """Manages concurrent scanner execution with backpressure and worker pooling."""

    def __init__(
        self,
        job: ScanJob,
        recorder: ScanRecorder,
        max_concurrent_scanners: int,
        lookahead_buffer_multiple: float = 1.0,
    ):
        self.job = job
        self.recorder = recorder
        self.max_concurrent_scanners = max_concurrent_scanners
        self.lookahead_buffer_multiple = lookahead_buffer_multiple

        # Initialize metrics
        self.metrics = WorkerMetrics()
        self.overall_start_time = time.time()

        # Compute work queue size from buffered transcripts
        self.work_queue_size = int(max_concurrent_scanners * lookahead_buffer_multiple)

        # Create bounded work queue
        self.work_item_send_stream: MemoryObjectSendStream[WorkItem]
        self.work_item_receive_stream: MemoryObjectReceiveStream[WorkItem]
        (
            self.work_item_send_stream,
            self.work_item_receive_stream,
        ) = anyio.create_memory_object_stream[WorkItem](self.work_queue_size)

        # Compute union content for all scanners
        self.union_content = union_transcript_contents(
            [config_for_scanner(scanner).content for scanner in job.scanners.values()]
        )

    async def execute(
        self, transcripts: Transcripts, progress: Progress, task_id: Any
    ) -> None:
        """Execute the scan with worker pool management."""
        self.progress = progress
        self.task_id = task_id

        try:
            async with create_task_group() as tg:
                await self._producer(tg, transcripts)
        except Exception as ex:
            print(f"caught {ex}")
            raise

    def _running_time(self) -> str:
        """Get formatted runtime since start."""
        return f"+{time.time() - self.overall_start_time:.3f}s"

    def _metrics_info(self) -> str:
        """Get formatted metrics string for debugging."""
        return (
            f"worker tasks: {self.metrics.worker_task_count} "
            f"(scanning: {self.metrics.workers_scanning}, "
            f"reporting: {self.metrics.workers_reporting}, "
            f"stalled: {self.metrics.workers_waiting}) "
            f"queue size: {self.work_item_receive_stream.statistics().current_buffer_used} "
        )

    def _work_item_info(self, item: WorkItem) -> str:
        """Get formatted work item info for debugging."""
        return f"{item.transcript.id, item.scanner_name}"

    async def _producer(self, tg: TaskGroup, transcripts: Transcripts) -> None:
        """Produce work items and manage worker spawning."""
        for t in await transcripts.index():
            transcript: Transcript | None = None
            for name, scanner in self.job.scanners.items():
                # Skip if already recorded
                if await self.recorder.is_recorded(t, name):
                    continue

                # Lazy load transcript on first scanner that needs it
                if transcript is None:
                    s_time = time.time()
                    transcript = await transcripts.read(t, self.union_content)
                    if (read_time := time.time() - s_time) > 1:
                        print(
                            f"{self._running_time()} Producer: Read transcript {t.id} in {read_time:.3f}s"
                        )

                # Check for backpressure
                backpressure = (
                    self.work_item_receive_stream.statistics().current_buffer_used
                    >= self.work_queue_size
                )

                new_item = WorkItem(
                    transcript=transcript,
                    scanner=scanner,
                    scanner_name=name,
                    report_callback=functools.partial(self.recorder.record, t, name),
                )

                # This send will block if queue is full (backpressure)
                await self.work_item_send_stream.send(new_item)

                print(
                    f"{self._running_time()} Producer: Added work item {self._work_item_info(new_item)} "
                    f"{' after backpressure relieved' if backpressure else ''}\n\t{self._metrics_info()}"
                )

                # Spawn workers as needed
                if self.metrics.worker_task_count < self.max_concurrent_scanners:
                    self.metrics.worker_task_count += 1
                    self.metrics.worker_id_counter += 1

                    print(
                        f"{self._running_time()} Producer: Spawned worker #{self.metrics.worker_id_counter}\n\t{self._metrics_info()}"
                    )

                    tg.start_soon(
                        self._worker_task,
                        self.work_item_receive_stream,
                        self.metrics.worker_id_counter,
                    )

                # Yield control to allow other tasks to run
                await anyio.sleep(0)

        print(f"{self._running_time()} Producer: FINISHED PRODUCING ALL WORK")

    async def _worker_task(
        self, work_item_stream: MemoryObjectReceiveStream[WorkItem], worker_id: int
    ) -> None:
        """Worker that pulls work items from stream until empty."""
        items_processed = 0

        try:
            # Continuously process items from stream
            while True:
                queue_was_empty_start_time = (
                    time.time()
                    if self.work_item_receive_stream.statistics().current_buffer_used
                    == 0
                    else None
                )

                # Use anyio's timeout handling
                try:
                    self.metrics.workers_waiting += 1
                    with anyio.move_on_after(2.0) as timeout_scope:
                        item = await work_item_stream.receive()
                finally:
                    self.metrics.workers_waiting -= 1

                # If timeout occurred, break out of loop
                if timeout_scope.cancelled_caught:
                    break

                stall_phrase = (
                    f" after stalling for {time.time() - queue_was_empty_start_time:.3f}s"
                    if queue_was_empty_start_time
                    else ""
                )
                print(
                    f"{self._running_time()} Worker #{worker_id} starting on {self._work_item_info(item)} item{stall_phrase}\n\t{self._metrics_info()}"
                )

                exec_start_time = time.time()
                await self._execute_work_item(item)
                print(
                    f"{self._running_time()} Worker #{worker_id} completed {self._work_item_info(item)} in {(time.time() - exec_start_time):.3f}s"
                )

                items_processed += 1

            print(
                f"{self._running_time()} Worker #{worker_id} finished after processing {items_processed} items.\n\t{self._metrics_info()}"
            )
        finally:
            self.metrics.worker_task_count -= 1

    async def _execute_work_item(self, item: WorkItem) -> None:
        """Execute a single work item."""
        raw_transcript = item.transcript
        scanner = item.scanner
        report = item.report_callback
        transcript = filter_transcript(
            raw_transcript, config_for_scanner(scanner).content
        )

        # Call the scanner
        result = await self._call_scanner(scanner, transcript)
        if result is not None:
            await self._call_report(report, result)

        # Update progress
        self.progress.update(self.task_id, advance=1)

    async def _call_scanner(
        self, scanner: Scanner[Any], transcript: Transcript
    ) -> Result | None:
        """Call scanner with metrics tracking."""
        try:
            self.metrics.workers_scanning += 1
            return await scanner(transcript)
        finally:
            self.metrics.workers_scanning -= 1

    async def _call_report(self, report: ScanReport, result: Result) -> None:
        """Report result with metrics tracking."""
        try:
            self.metrics.workers_reporting += 1
            await report([result])
        finally:
            self.metrics.workers_reporting -= 1
