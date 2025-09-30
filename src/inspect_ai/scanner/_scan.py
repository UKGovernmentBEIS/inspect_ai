import os
import sys
from typing import Any, Mapping, Sequence

import anyio
from dotenv import find_dotenv, load_dotenv
from rich import print
from rich.console import RenderableType
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

from inspect_ai._display.core.rich import rich_theme
from inspect_ai._eval.context import init_model_context
from inspect_ai._eval.task.task import resolve_model_roles
from inspect_ai._util._async import run_coroutine
from inspect_ai._util.config import resolve_args
from inspect_ai._util.path import pretty_path
from inspect_ai._util.platform import platform_init
from inspect_ai._util.registry import registry_info
from inspect_ai._util.rich import rich_traceback
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import Model, resolve_models
from inspect_ai.model._model_config import (
    model_config_to_model,
    model_roles_config_to_model_roles,
)
from inspect_ai.scanner._scanner.types import ScannerInput
from inspect_ai.scanner._util.contstants import DEFAULT_MAX_TRANSCRIPTS

from ._recorder.factory import scan_recorder_for_location
from ._recorder.recorder import ScanRecorder, ScanStatus
from ._scancontext import ScanContext, create_scan, resume_scan
from ._scanjob import ScanJob
from ._scanner.result import Result
from ._scanner.scanner import Scanner, config_for_scanner
from ._scanspec import ScanConfig, ScanSpec
from ._transcript.transcripts import Transcripts
from ._transcript.util import filter_transcript
from ._work_pool import WorkItem, scan_with_work_pool


def scan(
    scanners: Sequence[Scanner[ScannerInput] | tuple[str, Scanner[ScannerInput]]]
    | dict[str, Scanner[ScannerInput]]
    | ScanJob,
    transcripts: Transcripts | None = None,
    results: str | None = None,
    model: str | Model | None = None,
    model_config: GenerateConfig | None = None,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | str | None = None,
    model_roles: dict[str, str | Model] | None = None,
    max_transcripts: int | None = None,
    limit: int | None = None,
    shuffle: bool | int | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ScanStatus:
    return run_coroutine(
        scan_async(
            scanners=scanners,
            transcripts=transcripts,
            results=results,
            model=model,
            model_config=model_config,
            model_base_url=model_base_url,
            model_args=model_args,
            model_roles=model_roles,
            max_transcripts=max_transcripts,
            limit=limit,
            shuffle=shuffle,
            tags=tags,
            metadata=metadata,
        )
    )


async def scan_async(
    scanners: Sequence[Scanner[ScannerInput] | tuple[str, Scanner[ScannerInput]]]
    | dict[str, Scanner[ScannerInput]]
    | ScanJob,
    transcripts: Transcripts | None = None,
    results: str | None = None,
    model: str | Model | None = None,
    model_config: GenerateConfig | None = None,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | str | None = None,
    model_roles: dict[str, str | Model] | None = None,
    max_transcripts: int | None = None,
    limit: int | None = None,
    shuffle: bool | int | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ScanStatus:
    # init runtime
    init_runtime_context()

    # resolve scanjob
    if isinstance(scanners, ScanJob):
        scanjob = scanners
    else:
        scanjob = ScanJob(scanners=scanners)

    # resolve transcripts
    transcripts = transcripts or scanjob.transcripts
    if transcripts is None:
        raise ValueError("No 'transcripts' specified for scan.")

    # resolve results
    results = results or str(os.getenv("INSPECT_SCAN_RESULTS", "./scans"))

    # initialize scan config
    scan_config = ScanConfig(
        max_transcripts=max_transcripts or DEFAULT_MAX_TRANSCRIPTS,
        limit=limit,
        shuffle=shuffle,
    )

    # derive max_connections if not specified
    model_config = model_config or GenerateConfig()
    if model_config.max_connections is None:
        model_config.max_connections = scan_config.max_transcripts

    # initialize runtime context
    resolved_model, resolved_model_args, resolved_model_roles = init_scan_model_context(
        model=model,
        model_config=model_config,
        model_base_url=model_base_url,
        model_args=model_args,
        model_roles=model_roles,
    )

    # create job and recorder
    scan = await create_scan(
        scanjob=scanjob,
        transcripts=transcripts,
        model=resolved_model,
        model_args=resolved_model_args,
        model_roles=resolved_model_roles,
        config=scan_config,
        tags=tags,
        metadata=metadata,
    )
    recorder = scan_recorder_for_location(results)
    await recorder.init(scan.spec, results)

    # run the scan
    return await _scan_async(scan=scan, recorder=recorder)


def scan_resume(
    scan_dir: str,
) -> ScanStatus:
    return run_coroutine(scan_resume_async(scan_dir))


async def scan_resume_async(
    scan_dir: str,
) -> ScanStatus:
    # init runtime
    init_runtime_context()

    # resume job
    scan = await resume_scan(scan_dir)

    # can't resume a job with non-deterministic shuffling
    if scan.spec.config.shuffle is True:
        raise RuntimeError(
            "Cannot resume scans with transcripts shuffled without a seed."
        )

    # create model
    if scan.spec.model is not None:
        model = model_config_to_model(scan.spec.model)
    else:
        model = None

    # create/initialize models then call init runtime context
    init_scan_model_context(
        model=model,
        model_roles=model_roles_config_to_model_roles(scan.spec.model_roles),
    )

    # create recorder and scan
    recorder = scan_recorder_for_location(scan_dir)
    await recorder.resume(scan_dir)
    return await _scan_async(scan=scan, recorder=recorder)


async def _scan_async(*, scan: ScanContext, recorder: ScanRecorder) -> ScanStatus:
    """Execute a scan by orchestrating concurrent scanner execution across transcripts.

    This function is the orchestration layer that coordinates scanner execution
    with a focus on maximizing LLM call throughput. Since scanners often make LLM
    calls, which are orders of magnitude slower than local computation, the primary
    optimization goal is to keep `max_transcripts` concurrent LLM calls in flight
    at all times.

    Optimization Strategy:
        - Concurrency control: `max_transcripts` sets both the worker pool size
          and the model's `max_connections`, ensuring N concurrent LLM calls can
          execute simultaneously
        - Lazy loading: Transcripts are loaded on-demand only when needed by a scanner,
          minimizing memory usage and I/O
        - Backpressure: A bounded queue (size = max_transcripts × LOOKAHEAD_BUFFER_MULTIPLE)
          ensures work items are ready when workers finish, preventing worker starvation
          while controlling memory growth

    Args:
        scan: The scan context containing scanners, transcripts, and configuration
        recorder: The scan recorder for tracking completed work and persisting results

    Returns:
        ScanStatus indicating completion status, spec, and location for resumption
    """
    try:
        LOOKAHEAD_BUFFER_MULTIPLE: float = 1.0

        # establish max_transcripts
        max_transcripts = scan.spec.config.max_transcripts or DEFAULT_MAX_TRANSCRIPTS

        # apply limits/shuffle
        if scan.spec.config.limit is not None:
            transcripts = scan.transcripts.limit(scan.spec.config.limit)
        if scan.spec.config.shuffle is not None:
            transcripts = transcripts.shuffle(
                scan.spec.config.shuffle
                if isinstance(scan.spec.config.shuffle, int)
                else None
            )
        else:
            transcripts = scan.transcripts

        async with transcripts:
            with Progress(
                TextColumn("Scanning"),
                BarColumn(),
                TimeElapsedColumn(),
                transient=True,
            ) as progress:
                total_ticks = (await transcripts.count()) * len(scan.scanners)
                task_id = progress.add_task("Scan", total=total_ticks)

                async def _execute_work_item(item: WorkItem) -> dict[str, list[Result]]:
                    # Load transcript once for all scanners in this work item
                    transcript = await transcripts.read(
                        item.transcript_info, item.union_content
                    )

                    # Execute each scanner with the loaded transcript
                    return {
                        registry_info(scanner).name: (
                            # TODO: For now, scanners return a single Result, but
                            # it probably will allow multiple in the future
                            [result]
                            if (
                                result := await scanner(
                                    filter_transcript(
                                        transcript,
                                        config_for_scanner(scanner).content,
                                    )
                                )
                            )
                            else []
                        )
                        for scanner in item.scanners
                    }

                await scan_with_work_pool(
                    context=scan,
                    recorder=recorder,
                    max_tasks=max_transcripts,
                    max_queue_size=int(max_transcripts * LOOKAHEAD_BUFFER_MULTIPLE),
                    item_processor=_execute_work_item,
                    progress=lambda: progress.update(task_id, advance=1),
                    transcripts=transcripts,
                )

                scan_info = await recorder.complete()

        return scan_info
    except Exception as ex:
        type, value, traceback = sys.exc_info()
        type = type if type else BaseException
        value = value if value else ex
        tb = rich_traceback(type, value, traceback)
        return await handle_scan_interruped(tb, scan.spec, await recorder.location())

    except anyio.get_cancelled_exc_class():
        return await handle_scan_interruped(
            "Cancelled!", scan.spec, await recorder.location()
        )


def init_runtime_context() -> None:
    # platform init
    platform_init(hooks=False)

    # apply dotenv
    dotenv_file = find_dotenv(usecwd=True)
    load_dotenv(dotenv_file)


def init_scan_model_context(
    model: str | Model | None = None,
    model_config: GenerateConfig | None = None,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | str | None = None,
    model_roles: Mapping[str, str | Model] | None = None,
) -> tuple[Model, dict[str, Any], dict[str, Model] | None]:
    # resolve from inspect eval model env var if rquired
    if model is None:
        model = os.getenv("INSPECT_SCAN_MODEL", os.getenv("INSPECT_EVAL_MODEL", None))

    # init model context
    resolved_model_args = resolve_args(model_args or {})
    model = resolve_models(
        model, model_base_url, resolved_model_args, model_config or GenerateConfig()
    )[0]
    resolved_model_roles = resolve_model_roles(model_roles)
    init_model_context(
        model=model,
        model_roles=resolved_model_roles,
        config=model_config or GenerateConfig(),
    )

    return model, resolved_model_args, resolved_model_roles


async def handle_scan_interruped(
    message: RenderableType, spec: ScanSpec, location: str
) -> ScanStatus:
    theme = rich_theme()

    print(message)

    resume_message = (
        f"\n[bold][{theme.error}]Scan interrupted. Resume scan with:[/{theme.error}]\n\n"
        + f'[bold][{theme.light}]scan_resume("{pretty_path(location)}")[/{theme.light}][/bold]\n'
    )
    print(resume_message)

    return ScanStatus(
        complete=False,
        spec=spec,
        location=location,
    )
