import functools
import os
import re
import time
from typing import Any, Protocol, Sequence, TypeAlias

import anyio
from anyio import create_task_group
from anyio.abc import TaskGroup
from anyio.streams.memory import MemoryObjectReceiveStream
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from shortuuid import uuid

from inspect_ai._eval.context import init_runtime_context
from inspect_ai._util._async import run_coroutine
from inspect_ai._util.platform import platform_init
from inspect_ai._util.registry import registry_unqualified_name
from inspect_ai.scanner._recorder.recorder import ScanRecorder, ScanResults
from inspect_ai.scanner._recorder.types import (
    scan_recorder_for_location,
)
from inspect_ai.scanner._scandef import ScanDef
from inspect_ai.scanner._scanjob import ScanJob, create_scan_job, resume_scan_job
from inspect_ai.scanner._scanner.result import Result
from inspect_ai.scanner._scanspec import ScanConfig
from inspect_ai.scanner._transcript.types import (
    Transcript,
)
from inspect_ai.scanner._transcript.util import (
    filter_transcript,
    union_transcript_contents,
)

from ._scanner.scanner import Scanner, config_for_scanner
from ._transcript.transcripts import Transcripts


def scan(
    scandef: ScanDef,
    transcripts: Transcripts | None = None,
    limit: int | None = None,
    shuffle: bool | int | None = None,
    scans_dir: str | None = None,
    scan_id: str | None = None,
) -> ScanResults:
    return run_coroutine(
        scan_async(
            scandef=scandef,
            transcripts=transcripts,
            limit=limit,
            shuffle=shuffle,
            scans_dir=scans_dir,
            scan_id=scan_id,
        )
    )


async def scan_async(
    scandef: ScanDef,
    transcripts: Transcripts | None = None,
    limit: int | None = None,
    shuffle: bool | int | None = None,
    scans_dir: str | None = None,
    scan_id: str | None = None,
) -> ScanResults:
    # resolve id
    scan_id = scan_id or uuid()

    # validate name
    # TODO: move this earlier?
    if not re.match(r"^[a-zA-Z0-9-]+$", scandef.name):
        raise ValueError("scan 'name' may use only letters, numbers, and dashes")

    # resolve transcripts
    transcripts = transcripts or scandef.transcripts
    if transcripts is None:
        raise ValueError("No 'transcripts' specified for scan.")

    # resolve scans_dir
    scans_dir = scans_dir or str(os.getenv("INSPECT_SCANS_DIR", "./scans"))

    # initialize config
    scan_config = ScanConfig(limit=limit, shuffle=shuffle)

    # create job and recorder
    job = await create_scan_job(
        scandef, transcripts, config=scan_config, scan_id=scan_id
    )
    recorder = scan_recorder_for_location(scans_dir)
    await recorder.init(job.spec, scans_dir)

    return await _scan_async(
        job=await create_scan_job(
            scandef, transcripts, config=scan_config, scan_id=scan_id
        ),
        recorder=recorder,
    )


async def scan_resume(
    scan_dir: str,
) -> ScanResults:
    return run_coroutine(scan_resume_async(scan_dir))


async def scan_resume_async(
    scan_dir: str,
) -> ScanResults:
    # resume job and create recorder
    job = await resume_scan_job(scan_dir)
    recorder = scan_recorder_for_location(scan_dir)
    return await _scan_async(job=job, recorder=recorder)


class ScanReport(Protocol):
    async def __call__(self, results: Sequence[Result]) -> None: ...


WorkItem: TypeAlias = tuple[Transcript, Scanner[Any], str, ScanReport]


def _is_cpu_blocking_scanner(scanner: Scanner[Any], name: str) -> bool:
    # TODO: Temporary for testing - just to see if it's worth it
    return False
    # return name == "dummy_scanner"


async def _scan_async(*, job: ScanJob, recorder: ScanRecorder) -> ScanResults:
    # naive scan with:
    #  No parallelism
    #  No content filtering
    #  Supporting only Transcript

    platform_init()
    init_runtime_context()

    # TODO: plumb these for real
    max_llm_connections = 15
    max_concurrent_scanners: int | None = max_llm_connections
    lookahead_buffer_multiple: float = 1.0
    # TODO ^^^^^^^

    if max_concurrent_scanners is None:
        max_concurrent_scanners = max_llm_connections

    overall_start_time = time.time()

    # IO-blocking worker tracking
    io_worker_count = 0
    io_workers_waiting = 0
    io_workers_scanning = 0
    workers_reporting = 0  # Shared between both worker types
    io_worker_id_counter = 0
    io_scans_completed = 0
    cpu_scans_completed = 0

    # Compute queue sizes
    io_queue_size = int(max_concurrent_scanners * lookahead_buffer_multiple)
    cpu_queue_size = 20  # Small buffer for fast CPU operations

    # Create dual queues for IO-blocking and CPU-blocking scanners
    io_work_send_stream, io_work_receive_stream = anyio.create_memory_object_stream[
        WorkItem
    ](io_queue_size)

    cpu_work_send_stream, cpu_work_receive_stream = anyio.create_memory_object_stream[
        WorkItem
    ](cpu_queue_size)

    union_content = union_transcript_contents(
        [config_for_scanner(scanner).content for scanner in job.scanners.values()]
    )

    def _running_time() -> str:
        return f"+{time.time() - overall_start_time:.3f}s"

    # apply limits/shuffle
    if job.spec.config.limit is not None:
        transcripts = job.transcripts.limit(job.spec.config.limit)
    if job.spec.config.shuffle is not None:
        transcripts = transcripts.shuffle(
            job.spec.config.shuffle
            if isinstance(job.spec.config.shuffle, int)
            else None
        )
    else:
        transcripts = job.transcripts

    async with transcripts:
        with Progress(
            TextColumn("Scanning"),
            BarColumn(),
            TimeElapsedColumn(),
            transient=True,
        ) as progress:
            total_ticks = (await transcripts.count()) * len(job.scanners)
            task_id = progress.add_task("Scan", total=total_ticks)

            async def producer(tg: TaskGroup) -> None:
                # set up our reporter (stores results and lets us skip results we already have)
                nonlocal \
                    io_worker_count, \
                    io_workers_scanning, \
                    workers_reporting, \
                    io_workers_waiting, \
                    io_worker_id_counter

                # Start single CPU worker at beginning
                tg.start_soon(cpu_worker_task, cpu_work_receive_stream)
                print(f"{_running_time()} Producer: Started CPU worker")

                for t in await transcripts.index():
                    transcript: Transcript | None = None
                    for name, scanner in job.scanners.items():
                        # get reporter for this transcript/scanner (if None we already did this work)
                        if await recorder.is_recorded(t, name):
                            continue

                        # Lazy load transcript on first scanner that needs it
                        if transcript is None:
                            s_time = time.time()
                            transcript = await transcripts.read(t, union_content)
                            if (read_time := time.time() - s_time) > 1:
                                print(
                                    f"{_running_time()} Producer: Read transcript {t.id} in {read_time:.3f}s"
                                )

                        # Route work item to appropriate queue based on scanner type
                        is_cpu_blocking = _is_cpu_blocking_scanner(scanner, name)

                        if is_cpu_blocking:
                            target_queue = cpu_work_send_stream
                            target_receive_stream = cpu_work_receive_stream
                            queue_size = cpu_queue_size
                            queue_name = "cpu"
                        else:
                            target_queue = io_work_send_stream
                            target_receive_stream = io_work_receive_stream
                            queue_size = io_queue_size
                            queue_name = "io"

                        # Check backpressure
                        backpressure = (
                            target_receive_stream.statistics().current_buffer_used
                            >= queue_size
                        )

                        new_item = (
                            transcript,
                            scanner,
                            name,
                            functools.partial(recorder.record, t, name),
                        )
                        await target_queue.send(new_item)
                        print(
                            f"{_running_time()} Producer: Added {queue_name} work item {_work_item_info(new_item)} {' after backpressure relieved' if backpressure else ''}\n\t{_metrics_info()}"
                        )

                        # Only spawn IO workers dynamically (CPU worker is already started)
                        # Spawn when there's actual backlog: queue depth exceeds the number
                        # of workers currently waiting to receive, or when there are no IO workers yet.
                        if not is_cpu_blocking:
                            io_depth = (
                                io_work_receive_stream.statistics().current_buffer_used
                            )
                            should_spawn = (
                                io_worker_count < max_concurrent_scanners
                                and (
                                    io_worker_count == 0
                                    or io_depth > io_workers_waiting
                                )
                            )
                            if should_spawn:
                                io_worker_count += 1
                                io_worker_id_counter += 1

                                print(
                                    f"{_running_time()} Producer: Spawned IO worker #{io_worker_id_counter}\n\t{_metrics_info()}"
                                )

                                tg.start_soon(
                                    io_worker_task,
                                    io_work_receive_stream,
                                    io_worker_id_counter,
                                )

                        # We need to sleep whenever we add work and/or a new task.
                        # without doing this, the producer greedily keeps producing
                        # transcripts
                        await anyio.sleep(0)

                print(f"{_running_time()} Producer: FINISHED PRODUCING ALL WORK")

            async def io_worker_task(
                work_item_stream: MemoryObjectReceiveStream[WorkItem], worker_id: int
            ) -> None:
                """IO worker that pulls work items from IO stream until empty."""
                nonlocal \
                    io_worker_count, \
                    io_workers_scanning, \
                    io_workers_waiting, \
                    io_scans_completed

                items_processed = 0
                # print(f"{_running_time()} Worker #{worker_id} starting")

                try:
                    # Continuously process items from stream
                    while True:
                        queue_was_empty_start_time = (
                            time.time()
                            if work_item_stream.statistics().current_buffer_used == 0
                            else None
                        )

                        # Use anyio's timeout handling
                        try:
                            io_workers_waiting += 1
                            # Use a slightly longer timeout to avoid short-lived workers exiting
                            # during brief producer pauses (e.g., transcript reads).
                            with anyio.move_on_after(5.0) as timeout_scope:
                                item = await work_item_stream.receive()
                        finally:
                            io_workers_waiting -= 1

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
                        await _execute_work_item(item, True)
                        print(
                            f"{_running_time()} Worker #{worker_id} completed {_work_item_info(item)} in {(time.time() - exec_start_time):.3f}s"
                        )

                        items_processed += 1
                        io_scans_completed += 1

                    print(
                        f"{_running_time()} IO Worker #{worker_id} finished after processing {items_processed} items.\n\t{_metrics_info()}"
                    )
                finally:
                    io_worker_count -= 1

            async def cpu_worker_task(
                work_item_stream: MemoryObjectReceiveStream[WorkItem],
            ) -> None:
                """Single CPU worker for fast, CPU-bound scanners."""
                nonlocal cpu_scans_completed
                max_consecutive = 10  # Process N items before yielding

                print(f"{_running_time()} CPU Worker starting")

                try:
                    while True:
                        # Use timeout to detect when no more work is available
                        try:
                            with anyio.move_on_after(2.0) as timeout_scope:
                                item = await work_item_stream.receive()
                        except Exception as e:
                            print(f"CPU worker receive error: {e}")
                            break

                        # If timeout occurred, break out of loop
                        if timeout_scope.cancelled_caught:
                            break

                        exec_start_time = time.time()
                        await _execute_work_item(item, False)
                        cpu_scans_completed += 1
                        print(
                            f"{_running_time()} CPU Worker completed {_work_item_info(item)} in {(time.time() - exec_start_time):.3f}s"
                        )

                        # Yield periodically to allow IO callbacks and other tasks to run
                        if cpu_scans_completed % max_consecutive == 0:
                            await anyio.sleep(0)  # Force yield

                    print(
                        f"{_running_time()} CPU Worker finished after processing {cpu_scans_completed} items."
                    )
                except Exception as e:
                    print(f"CPU worker error: {e}")

            async def _execute_work_item(item: WorkItem, is_io_scanner: bool) -> None:
                nonlocal io_workers_scanning
                raw_transcript, scanner, name, report = item
                transcript = _transcript_for_scanner(raw_transcript, scanner)

                # call the scanner (note that later this may accumulate multiple
                # scanner calls e.g. for ChatMessage scanners and then report all
                # of the results together)
                result = await _call_scanner(scanner, transcript, is_io_scanner)
                if result is not None:
                    await _call_report(report, result)
                    await report([result])

                # tick progress
                progress.update(task_id, advance=1)

            async def _call_scanner(
                scanner: Scanner[Any], transcript: Transcript, is_io_scanner: bool
            ) -> Result | None:
                nonlocal io_workers_scanning
                try:
                    if is_io_scanner:
                        io_workers_scanning += 1
                    return await scanner(transcript)
                finally:
                    if is_io_scanner:
                        io_workers_scanning -= 1

            async def _call_report(report: ScanReport, result: Result) -> None:
                nonlocal workers_reporting
                try:
                    workers_reporting += 1
                    await report([result])
                finally:
                    workers_reporting -= 1

            def _metrics_info() -> str:
                io_queue_depth = io_work_receive_stream.statistics().current_buffer_used
                cpu_queue_depth = (
                    cpu_work_receive_stream.statistics().current_buffer_used
                )

                return (
                    f"io_workers: {io_worker_count} "
                    f"(scanning: {io_workers_scanning}, reporting: {workers_reporting}, stalled: {io_workers_waiting}, done: {io_scans_completed}) "
                    f"io_queue: {io_queue_depth}/{io_queue_size} | "
                    f"cpu scans completed: {cpu_scans_completed}, cpu_queue: {cpu_queue_depth}/{cpu_queue_size}"
                )

            def _work_item_info(item: WorkItem) -> str:
                return f"{item[0].id, item[2]}"

            try:
                async with create_task_group() as tg:
                    await producer(tg)
            except Exception as ex:
                print(f"caught {ex}")
                raise

            # read all scan results for this scan
            results = await recorder.complete()

    return results


def _transcript_for_scanner(
    transcript: Transcript, scanner: Scanner[Any]
) -> Transcript:
    return filter_transcript(transcript, config_for_scanner(scanner).content)
