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

    Validates that the scanner set passed on resume matches the one in
    the on-disk spec. Scout's `RecorderBuffer.record` looks up scanner
    metadata by name in the spec; any unknown scanner would `KeyError`
    mid-sample, get caught as a sample error, and silently corrupt the
    eval's success/failure result. We refuse upfront with a clear message.
    """
    from inspect_scout._recorder.file import FileRecorder
    from inspect_scout._scancontext import _spec_scanners
    from inspect_scout._scanspec import ScanOptions, ScanSpec

    from inspect_ai._util.error import PrerequisiteError

    scanners_dict = _normalize_scanners(scanner)
    scan_dir = _scan_dir(log_dir, eval_set_id)
    recorder = FileRecorder()

    if exists(scan_dir):
        await recorder.attach(scan_dir, concurrent_writers=True)
        existing_names = set(recorder.scan_spec.scanners.keys())
        requested_names = set(scanners_dict.keys())
        if existing_names != requested_names:
            raise PrerequisiteError(
                "Scanner set has changed from the prior eval_set call on "
                "this log_dir.\n"
                f"  Prior:     {sorted(existing_names)}\n"
                f"  Requested: {sorted(requested_names)}\n"
                "Either match the prior scanner set or use a different "
                "log_dir / eval_set_id."
            )
        return

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
        await recorder.attach(scan_dir, concurrent_writers=True)
        await recorder.record(info, name, reports, metrics=None)


async def scan_eval_set_finalize(
    *,
    eval_set_id: str,
    log_dir: str,
) -> None:
    """Compact buffer parquets and snapshot the recorded transcripts.

    The transcripts snapshot is what scout's `scan_resume` uses to know
    which transcripts existed in the scan. We sync first — that merges
    this call's buffer with the previously-compacted parquet (via
    `extra_inputs`) into the canonical output. The post-sync compacted
    parquet contains every transcript ever recorded for this eval_set
    across all calls; we read its `transcript_id` /
    `transcript_source_uri` columns to build the snapshot, then write it
    into `scan.json`. Errored scans show up too: their per-transcript row
    has `scan_error` populated and `is_recorded` will return False on
    resume, marking them for retry.

    The snapshot is written by reading and re-writing `scan.json`
    directly rather than via `recorder.attach() + snapshot_transcripts`,
    because `attach` recreates the buffer dir (which `sync(complete=True)`
    just cleaned up) and would leave the scan looking "in progress".

    `complete` is True only when no scanner errors are present; with
    errors we leave the scan resumable so scout's `scan_resume` can
    re-run just the failed scans.
    """
    scan_dir = _scan_dir(log_dir, eval_set_id)
    if not exists(scan_dir):
        return

    from inspect_scout._recorder.file import FileRecorder

    # only mark complete if no scanner errors — otherwise leave the scan
    # in an "incomplete" state so scout's `scan_resume` can pick up the
    # failed scans. status() reads errors from the buffer dir while it
    # still exists (cleanup happens inside sync when complete=True).
    pre_sync_status = await FileRecorder.status(scan_dir)
    complete = not pre_sync_status.errors

    # sync so the compacted parquet has the union of all calls
    await FileRecorder.sync(scan_dir, complete=complete)

    # build snapshot from the compacted output and write into scan.json
    from upath import UPath

    snapshot = _snapshot_from_compacted(UPath(scan_dir), log_dir=log_dir)
    if snapshot is None:
        return
    _write_snapshot_to_scan_spec(UPath(scan_dir), snapshot)


def _write_snapshot_to_scan_spec(scan_dir: Any, snapshot: Any) -> None:
    """Read the on-disk scan spec, attach the snapshot, write it back.

    Bypasses `FileRecorder.attach` so we don't recreate the buffer dir
    that `sync(complete=True)` just removed — keeping the scan in the
    "complete" state for `FileRecorder.status`.
    """
    from inspect_scout._recorder.file import SCAN_JSON
    from inspect_scout._scanspec import ScanSpec

    from inspect_ai._util.file import file
    from inspect_ai._util.json import to_json_str_safe

    scan_json = (scan_dir / SCAN_JSON).as_posix()
    with file(scan_json, "r") as f:
        spec = ScanSpec.model_validate_json(f.read())
    spec.transcripts = snapshot
    with file(scan_json, "w") as f:
        f.write(to_json_str_safe(spec))


def _snapshot_from_compacted(scan_dir: Any, *, log_dir: str) -> Any:
    """Build a `ScanTranscripts` from the post-sync compacted parquet.

    Reads `transcript_id` + `transcript_source_uri` from any scanner's
    compacted output — every scanner sees every transcript, so any one
    is a complete index. Returns None if no scanner parquets exist (e.g.
    scan ran with no samples).
    """
    import io

    import pyarrow.parquet as pq
    from inspect_scout._scanspec import ScanTranscripts

    parquets = sorted(p for p in scan_dir.iterdir() if p.suffix == ".parquet")
    if not parquets:
        return None

    pf = pq.ParquetFile(io.BytesIO(parquets[0].read_bytes()))
    table = pf.read(columns=["transcript_id", "transcript_source_uri"])
    transcript_ids: dict[str, str | None] = {}
    for tid, uri in zip(
        table.column("transcript_id").to_pylist(),
        table.column("transcript_source_uri").to_pylist(),
    ):
        if tid is not None and tid not in transcript_ids:
            transcript_ids[tid] = uri

    if not transcript_ids:
        return None
    return ScanTranscripts(
        type="eval_log",
        location=log_dir,
        transcript_ids=transcript_ids,
    )


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

    from inspect_ai.analysis._dataframe.samples.extract import auto_sample_id

    # use the same id derivation as inspect_ai's samples_df (which scout's
    # EvalLogTranscripts reads): `sample.uuid` if present, else a stable
    # hash of (eval_id, sample.id, sample.epoch). Aligning with that
    # convention is what lets scout's tooling cross-reference our records
    # against the same transcripts read out of the eval logs.
    return TranscriptInfo(
        transcript_id=eval_sample.uuid or auto_sample_id(eval_id, eval_sample),
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
