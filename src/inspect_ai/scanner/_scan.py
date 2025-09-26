import functools
import os
import re
import time
from typing import Any, NamedTuple, Protocol, Sequence

import anyio
from anyio import create_task_group
from anyio.abc import TaskGroup
from anyio.streams.memory import MemoryObjectReceiveStream
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from shortuuid import uuid

from inspect_ai._eval.context import init_runtime_context
from inspect_ai._util._async import run_coroutine
from inspect_ai._util.platform import platform_init
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import Model
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
    model: str | Model | None = None,
    model_config: GenerateConfig | None = None,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | str | None = None,
    model_roles: dict[str, str | Model] | None = None,
    limit: int | None = None,
    shuffle: bool | int | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    scans_dir: str | None = None,
    scan_id: str | None = None,
) -> ScanResults:
    return run_coroutine(
        scan_async(
            scandef=scandef,
            transcripts=transcripts,
            model=model,
            model_config=model_config,
            model_base_url=model_base_url,
            model_args=model_args,
            model_roles=model_roles,
            limit=limit,
            shuffle=shuffle,
            tags=tags,
            metadata=metadata,
            scans_dir=scans_dir,
            scan_id=scan_id,
        )
    )


async def scan_async(
    scandef: ScanDef,
    transcripts: Transcripts | None = None,
    model: str | Model | None = None,
    model_config: GenerateConfig | None = None,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | str | None = None,
    model_roles: dict[str, str | Model] | None = None,
    limit: int | None = None,
    shuffle: bool | int | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
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
        scandef=scandef,
        transcripts=transcripts,
        model=model,
        model_config=model_config,
        model_base_url=model_base_url,
        model_args=model_args,
        model_roles=model_roles,
        config=scan_config,
        tags=tags,
        metadata=metadata,
        scan_id=scan_id,
    )
    recorder = scan_recorder_for_location(scans_dir)
    await recorder.init(job.spec, scans_dir)

    # run the scan
    return await _scan_async(job=job, recorder=recorder)


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


class WorkItem(NamedTuple):
    """Represents a unit of work for scanning a transcript."""

    transcript: Transcript
    scanner: Scanner[Any]
    scanner_name: str
    report_callback: ScanReport


async def _scan_async(*, job: ScanJob, recorder: ScanRecorder) -> ScanResults:
    # naive scan with:
    #  No parallelism
    #  No content filtering
    #  Supporting only Transcript

    platform_init()
    init_runtime_context()

    # TODO: plumb these for real
    max_llm_connections = 100
    max_concurrent_scanners: int | None = 100
    lookahead_buffer_multiple: float = 1.0
    # TODO ^^^^^^^

    if max_concurrent_scanners is None:
        max_concurrent_scanners = max_llm_connections

    overall_start_time = time.time()

    worker_task_count = 0
    workers_waiting = 0
    workers_scanning = 0
    workers_reporting = 0
    worker_id_counter = 0

    # Compute work queue size from buffered transcripts
    work_queue_size = int(max_concurrent_scanners * lookahead_buffer_multiple)

    # Create bounded work queue and result stream
    work_item_send_stream, work_item_receive_stream = anyio.create_memory_object_stream[
        WorkItem
    ](work_queue_size)

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
                    worker_task_count, \
                    workers_scanning, \
                    workers_reporting, \
                    workers_waiting, \
                    worker_id_counter

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

                        # This send into the work_item_send_stream is a point where backpressure
                        # can be applied

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
                        await work_item_send_stream.send(new_item)
                        print(
                            f"{_running_time()} Producer: Added work item {_work_item_info(new_item)} {' after backpressure relieved' if backpressure else ''}\n\t{_metrics_info()}"
                        )

                        if worker_task_count < max_concurrent_scanners:
                            worker_task_count += 1
                            worker_id_counter += 1

                            print(
                                f"{_running_time()} Producer: Spawned worker #{worker_id_counter}\n\t{_metrics_info()}"
                            )

                            tg.start_soon(
                                worker_task, work_item_receive_stream, worker_id_counter
                            )

                        # We need to sleep whenever we add work and/or a new task.
                        # without doing this, the producer greedily keeps producing
                        # transcripts
                        await anyio.sleep(0)

                print(f"{_running_time()} Producer: FINISHED PRODUCING ALL WORK")

            async def worker_task(
                work_item_stream: MemoryObjectReceiveStream[WorkItem], worker_id: int
            ) -> None:
                """Worker that pulls work items from stream until empty."""
                nonlocal worker_task_count, workers_scanning, workers_waiting
                items_processed = 0
                # print(f"{_running_time()} Worker #{worker_id} starting")

                try:
                    # Continuously process items from stream
                    while True:
                        queue_was_empty_start_time = (
                            time.time()
                            if work_item_receive_stream.statistics().current_buffer_used
                            == 0
                            else None
                        )

                        # Use anyio's timeout handling
                        try:
                            workers_waiting += 1
                            with anyio.move_on_after(2.0) as timeout_scope:
                                item = await work_item_stream.receive()
                        finally:
                            workers_waiting -= 1

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
                    worker_task_count -= 1

            async def _execute_work_item(item: WorkItem) -> None:
                nonlocal workers_scanning
                raw_transcript = item.transcript
                scanner = item.scanner
                report = item.report_callback
                transcript = _transcript_for_scanner(raw_transcript, scanner)

                # call the scanner (note that later this may accumulate multiple
                # scanner calls e.g. for ChatMessage scanners and then report all
                # of the results together)
                result = await _call_scanner(scanner, transcript)
                if result is not None:
                    await _call_report(report, result)

                # tick progress
                progress.update(task_id, advance=1)

            async def _call_scanner(
                scanner: Scanner[Any], transcript: Transcript
            ) -> Result | None:
                nonlocal workers_scanning
                try:
                    workers_scanning += 1
                    return await scanner(transcript)
                finally:
                    workers_scanning -= 1

            async def _call_report(report: ScanReport, result: Result) -> None:
                nonlocal workers_reporting
                try:
                    workers_reporting += 1
                    await report([result])
                finally:
                    workers_reporting -= 1

            def _metrics_info() -> str:
                return f"worker tasks: {worker_task_count} (scanning: {workers_scanning}, reporting: {workers_reporting}, stalled: {workers_waiting}) queue size: {work_item_receive_stream.statistics().current_buffer_used} "

            def _work_item_info(item: WorkItem) -> str:
                return f"{item.transcript.id, item.scanner_name}"

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
