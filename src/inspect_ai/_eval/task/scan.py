"""Per-sample scanner dispatch within `eval_set`.

See `design/eval-set-scanners.md` for the full design.
"""

import contextlib
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from inspect_ai._util._async import run_coroutine
from inspect_ai._util.file import absolute_file_path, dirname, exists
from inspect_ai.log._log import EvalSample

if TYPE_CHECKING:
    from inspect_scout import Scanner, Scanners


async def scan_eval_set_init(
    scanner: "Scanners",
    *,
    eval_set_id: str,
    log_dir: str,
) -> None:
    """Lay down the scan dir + initial summary for an eval_set.

    On second-and-later `eval_set` calls (e.g. resume after a partial
    failure), the scan dir already exists. Use `resume()` so the
    accumulated `_summary.json` is preserved and extended; `init()` would
    wipe it via `reset=True`.
    """
    from inspect_scout._recorder.file import FileRecorder
    from inspect_scout._scancontext import _spec_scanners
    from inspect_scout._scanspec import ScanOptions, ScanSpec

    scan_dir = _scan_dir(log_dir, eval_set_id)
    recorder = FileRecorder()
    if exists(scan_dir):
        await recorder.resume(scan_dir, concurrent_writers=True)
        return

    scanners_dict = _normalize_scanners(scanner)
    spec = ScanSpec(
        scan_id=eval_set_id,
        scan_name="eval_set",
        scanners=_spec_scanners(scanners_dict),
        options=ScanOptions(),
    )
    await recorder.init(spec, _scans_location(log_dir), concurrent_writers=True)


async def scan_eval_sample(
    eval_sample: EvalSample,
    scanner: "Scanners | None",
    *,
    eval_set_id: str | None,
    eval_id: str,
    log_location: str,
    model: str | None = None,
) -> None:
    """Run scanners over a completed sample's transcript.

    `log_location` may be relative (the value passed to `task_run_sample`
    is relative-to-eval_wd in the common case); resolved here to absolute
    so the derived scan dir matches the one registered by `scan_eval_set_init`.
    """
    if scanner is None or eval_set_id is None:
        return
    log_location = absolute_file_path(log_location)
    scan_dir = _scan_dir(dirname(log_location), eval_set_id)
    if not exists(scan_dir):
        return

    from inspect_scout._concurrency.common import ScannerJob
    from inspect_scout._recorder.file import FileRecorder
    from inspect_scout._scan import _scan_one

    scanners_dict = _normalize_scanners(scanner)
    info = _transcript_info(
        eval_sample, eval_id=eval_id, model=model, log_location=log_location
    )
    transcript = _transcript(eval_sample, info=info)

    for name, scanner_fn in scanners_dict.items():
        job = ScannerJob(
            union_transcript=transcript,
            scanner=scanner_fn,
            scanner_name=name,
        )
        reports = await _scan_one(job)
        recorder = FileRecorder()
        await recorder.resume(scan_dir, concurrent_writers=True)
        await recorder.record(info, name, reports, metrics=None)


async def scan_eval_set_finalize(
    *,
    eval_set_id: str,
    log_dir: str,
) -> None:
    """Compact buffer parquets into canonical `<scanner>.parquet` files."""
    scan_dir = _scan_dir(log_dir, eval_set_id)
    if not exists(scan_dir):
        return

    from inspect_scout._recorder.file import FileRecorder

    await FileRecorder.sync(scan_dir, complete=True)


@contextlib.contextmanager
def scan_eval_set_context(
    scanner: "Scanners | None",
    *,
    eval_set_id: str,
    log_dir: str,
) -> Iterator[None]:
    """Initialize scan state on enter, compact on exit. No-op when scanner is None."""
    if scanner is None:
        yield
        return
    run_coroutine(scan_eval_set_init(scanner, eval_set_id=eval_set_id, log_dir=log_dir))
    try:
        yield
    finally:
        run_coroutine(scan_eval_set_finalize(eval_set_id=eval_set_id, log_dir=log_dir))


def _scans_location(log_dir: str) -> str:
    return f"{log_dir.rstrip('/')}/scans"


def _scan_dir(log_dir: str, eval_set_id: str) -> str:
    return f"{_scans_location(log_dir)}/scan_id={eval_set_id}"


def _normalize_scanners(scanner: "Scanners") -> "dict[str, Scanner[Any]]":
    from inspect_scout import ScanJob, ScanJobConfig

    if isinstance(scanner, ScanJob):
        return scanner._scanners
    if isinstance(scanner, ScanJobConfig):
        return ScanJob.from_config(scanner)._scanners
    return ScanJob(scanners=scanner)._scanners


def _transcript_info(
    eval_sample: EvalSample,
    *,
    eval_id: str,
    model: str | None,
    log_location: str | None,
) -> Any:
    from inspect_scout import TranscriptInfo

    return TranscriptInfo(
        transcript_id=eval_sample.uuid or f"{eval_sample.id}_{eval_sample.epoch}",
        source_type="eval_sample",
        source_id=eval_id,
        source_uri=log_location,
        date=eval_sample.completed_at or eval_sample.started_at,
        task_id=str(eval_sample.id),
        task_repeat=eval_sample.epoch,
        model=model,
        score=_score_value(eval_sample),
        success=_score_success(eval_sample),
        message_count=len(eval_sample.messages),
        total_time=eval_sample.total_time,
        error=eval_sample.error.message if eval_sample.error is not None else None,
        metadata=dict(eval_sample.metadata),
    )


def _transcript(eval_sample: EvalSample, *, info: Any) -> Any:
    from inspect_scout import Transcript

    timelines: list[Any] = list(eval_sample.timelines or [])
    if not timelines and eval_sample.events:
        from inspect_ai.event import timeline_build

        timelines = [timeline_build(eval_sample.events)]

    return Transcript.model_construct(
        **info.model_dump(),
        messages=list(eval_sample.messages),
        events=list(eval_sample.events),
        timelines=timelines,
    )


def _score_value(sample: EvalSample) -> Any:
    if sample.scores and len(sample.scores) == 1:
        return next(iter(sample.scores.values())).value
    return None


def _score_success(sample: EvalSample) -> bool | None:
    value = _score_value(sample)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    return None
