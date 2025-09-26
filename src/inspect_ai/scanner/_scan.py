import os
import re
from typing import Any, Mapping

from dotenv import find_dotenv, load_dotenv
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from shortuuid import uuid

from inspect_ai._eval.context import init_model_context
from inspect_ai._eval.task.task import resolve_model_roles
from inspect_ai._util._async import run_coroutine
from inspect_ai._util.config import resolve_args
from inspect_ai._util.platform import platform_init
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import Model, resolve_models
from inspect_ai.model._model_config import (
    model_config_to_model,
    model_roles_config_to_model_roles,
)
from inspect_ai.scanner._recorder.recorder import ScanRecorder, ScanResults
from inspect_ai.scanner._recorder.types import (
    scan_recorder_for_location,
)
from inspect_ai.scanner._scandef import ScanDef
from inspect_ai.scanner._scanjob import ScanJob, create_scan_job, resume_scan_job
from inspect_ai.scanner._scanspec import ScanConfig

from ._transcript.transcripts import Transcripts
from ._work_pool import ScannerWorkPool


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

    # resolve transcripts
    transcripts = transcripts or scandef.transcripts
    if transcripts is None:
        raise ValueError("No 'transcripts' specified for scan.")

    # resolve scans_dir
    scans_dir = scans_dir or str(os.getenv("INSPECT_SCAN_DIR", "./scans"))

    # initialize config
    scan_config = ScanConfig(limit=limit, shuffle=shuffle)

    # initialize runtime context
    resolved_model, resolved_model_args, resolved_model_roles = init_runtime_context(
        model=model,
        model_config=model_config,
        model_base_url=model_base_url,
        model_args=model_args,
        model_roles=model_roles,
    )

    # create job and recorder
    job = await create_scan_job(
        scandef=scandef,
        transcripts=transcripts,
        model=resolved_model,
        model_args=resolved_model_args,
        model_roles=resolved_model_roles,
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
    # resume job
    job = await resume_scan_job(scan_dir)

    # can't resume a job with non-deterministic shuffling
    if job.spec.config.shuffle is True:
        raise RuntimeError(
            "Cannot resume scans with transcripts shuffled without a seed."
        )

    # create model
    if job.spec.model is not None:
        model = model_config_to_model(job.spec.model)
    else:
        model = None

    # create/initialize models then call init runtime context
    init_runtime_context(
        model=model,
        model_roles=model_roles_config_to_model_roles(job.spec.model_roles),
    )

    # create recorder and scan
    recorder = scan_recorder_for_location(scan_dir)
    return await _scan_async(job=job, recorder=recorder)


def init_runtime_context(
    model: str | Model | None = None,
    model_config: GenerateConfig | None = None,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | str | None = None,
    model_roles: Mapping[str, str | Model] | None = None,
) -> tuple[Model, dict[str, Any], dict[str, Model] | None]:
    # platform init
    platform_init(hooks=False)

    # apply dotenv
    dotenv_file = find_dotenv(usecwd=True)
    load_dotenv(dotenv_file)

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


async def _scan_async(*, job: ScanJob, recorder: ScanRecorder) -> ScanResults:
    # naive scan with:
    #  No parallelism
    #  No content filtering
    #  Supporting only Transcript

    # TODO: plumb these for real
    max_llm_connections = 100
    max_concurrent_scanners: int | None = 100
    lookahead_buffer_multiple: float = 1.0
    # TODO ^^^^^^^

    if max_concurrent_scanners is None:
        max_concurrent_scanners = max_llm_connections

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

            # Create and execute the work pool
            pool = ScannerWorkPool(
                job=job,
                recorder=recorder,
                max_concurrent_scanners=max_concurrent_scanners,
                lookahead_buffer_multiple=lookahead_buffer_multiple,
            )
            await pool.execute(transcripts, progress, task_id)

            # read all scan results for this scan
            results = await recorder.complete()

    return results
