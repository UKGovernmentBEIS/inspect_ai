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

    _validate_scan_config(scanner)
    scanners_dict = _normalize_scanners(scanner)
    scan_dir = _scan_dir(log_dir, eval_set_id, scanner)
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
        scan_name=_normalize_scan_name(scanner),
        scanners=_spec_scanners(scanners_dict),
        options=ScanOptions(),
        tags=_normalize_tags(scanner),
        metadata=_normalize_metadata(scanner),
    )
    await recorder.init(
        spec, _scans_location(log_dir, scanner), concurrent_writers=True
    )


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
    scan_dir = _scan_dir(dirname(log_location), eval_set_id, scanner)
    if not exists(scan_dir):
        return

    # honor any SQL filter on a `ScanJobConfig` — samples that don't
    # match are not scanned at all (no parquet row, no entry in the
    # snapshot). Mirrors how scout's direct scan path filters via
    # `Transcripts.where(...)`, applied here per-sample because we
    # dispatch per-sample rather than reading from a query.
    if not _sample_matches_filters(eval_sample, _normalize_filters(scanner)):
        return

    from inspect_scout._concurrency.common import ScannerJob
    from inspect_scout._recorder.file import FileRecorder
    from inspect_scout._scan import _scan_one

    _install_scan_model_context(scanner)
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
    scanner: "Scanners | None" = None,
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
    scan_dir = _scan_dir(log_dir, eval_set_id, scanner)
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
        run_coroutine(
            scan_eval_set_finalize(
                eval_set_id=eval_set_id, log_dir=log_dir, scanner=scanner
            )
        )


def _scans_location(log_dir: str, scanner: "Scanners | None" = None) -> str:
    """Where scan outputs land.

    Defaults to `<log_dir>/scans/`. A `ScanJob`/`ScanJobConfig` may
    override via its `scans` field — that gets used as the location
    directly so the user can write scan results to a different
    filesystem (e.g. an S3 bucket) than the eval logs.
    """
    base = _normalize_scans(scanner) or f"{log_dir.rstrip('/')}/scans"
    return base.rstrip("/")


def _scan_dir(log_dir: str, eval_set_id: str, scanner: "Scanners | None" = None) -> str:
    return f"{_scans_location(log_dir, scanner)}/scan_id={eval_set_id}"


def _normalize_scanners(
    scanner: "Scanners | None",
) -> "dict[str, Scanner[Any]]":
    from inspect_scout import ScanJob, ScanJobConfig

    if scanner is None:
        return {}
    if isinstance(scanner, ScanJob):
        return scanner._scanners
    if isinstance(scanner, ScanJobConfig):
        return ScanJob.from_config(scanner)._scanners
    return ScanJob(scanners=scanner)._scanners


def _normalize_scans(scanner: "Scanners | None") -> str | None:
    """Extract the scan-output-location override (`scans`), if any."""
    from inspect_scout import ScanJob, ScanJobConfig

    if isinstance(scanner, (ScanJob, ScanJobConfig)):
        return scanner.scans
    return None


def _normalize_tags(scanner: "Scanners | None") -> list[str] | None:
    """Tags carried on `ScanJob`/`ScanJobConfig`, written into the scan spec."""
    from inspect_scout import ScanJob, ScanJobConfig

    if isinstance(scanner, (ScanJob, ScanJobConfig)):
        return scanner.tags
    return None


def _normalize_scan_name(scanner: "Scanners | None") -> str:
    """Scan-name override from `ScanJob`/`ScanJobConfig`, else "eval_set"."""
    from inspect_scout import ScanJob, ScanJobConfig

    if isinstance(scanner, (ScanJob, ScanJobConfig)):
        return scanner.name or "eval_set"
    return "eval_set"


def _normalize_metadata(scanner: "Scanners | None") -> "dict[str, Any] | None":
    """Metadata carried on `ScanJob`/`ScanJobConfig`, written into the scan spec."""
    from inspect_scout import ScanJob, ScanJobConfig

    if isinstance(scanner, (ScanJob, ScanJobConfig)):
        return scanner.metadata
    return None


def _install_scan_model_context(scanner: "Scanners | None") -> None:
    """Install scout's scan-time model context for this sample, if set.

    When a `ScanJob`/`ScanJobConfig` carries `model` (or related
    `model_base_url` / `model_args` / `generate_config` / `model_roles`),
    call scout's `init_scan_model_context` so the scanner's
    `get_model()` resolves to the scan-side model rather than the eval's
    active model. The override lives on the per-sample async context —
    each sample inherits a fresh copy of the task's context, so setting
    it here does not leak to other samples or back into the eval's
    solver path. (The eval's `model_usage` for this sample is already
    snapshotted into `EvalSample` before `scan_eval_sample` is called.)
    No-op when nothing's set, so the scanner inherits the eval's model.
    """
    from inspect_scout import ScanJob, ScanJobConfig
    from inspect_scout._scan import init_scan_model_context

    if not isinstance(scanner, (ScanJob, ScanJobConfig)):
        return

    kwargs: dict[str, Any] = {}
    if scanner.model is not None:
        kwargs["model"] = scanner.model
    if scanner.generate_config is not None:
        kwargs["model_config"] = scanner.generate_config
    if scanner.model_base_url is not None:
        kwargs["model_base_url"] = scanner.model_base_url
    if scanner.model_args is not None:
        kwargs["model_args"] = scanner.model_args
    if scanner.model_roles is not None:
        kwargs["model_roles"] = scanner.model_roles

    if kwargs:
        init_scan_model_context(**kwargs)


_REJECTED_SCAN_FIELDS: dict[str, str] = {
    "transcripts": (
        "eval_set scans the eval's own samples; an external transcripts "
        "source would override that."
    ),
    "worklist": (
        "the per-sample dispatch in eval_set is the source of truth for "
        "what gets scanned."
    ),
    "limit": "sample selection belongs to the eval (use `eval_set(limit=...)`).",
    "shuffle": (
        "sample ordering belongs to the eval (shuffle the dataset at the eval level)."
    ),
    "max_processes": (
        "concurrency belongs to the eval (use `eval_set(max_samples=...)` / "
        "`eval_set(max_tasks=...)`)."
    ),
    "max_transcripts": (
        "scout uses this for batch transcript concurrency, but eval_set "
        "dispatches scanners per-sample as the eval emits them; per-sample "
        "concurrency is set at the eval layer (`eval_set(max_samples=...)`)."
    ),
    "validation": (
        "validation cases match by transcript_id, but eval_set generates "
        "transcripts at run time so there is no labelled ground truth to "
        "attach in advance."
    ),
    "log_level": (
        "scout uses `log_level` to (re)init the process-wide logger; "
        "eval_set already owns logging — use `eval_set(log_level=...)`."
    ),
}


def _validate_scan_config(scanner: "Scanners | None") -> None:
    """Reject `ScanJob`/`ScanJobConfig` fields that conflict with eval_set.

    See `_REJECTED_SCAN_FIELDS` for the field→reason map; each rejected
    field is reported with its own reason so the user sees exactly what
    to remove.
    """
    from inspect_scout import ScanJob, ScanJobConfig

    from inspect_ai._util.error import PrerequisiteError

    if not isinstance(scanner, (ScanJob, ScanJobConfig)):
        return

    rejected: list[str] = []
    for field, reason in _REJECTED_SCAN_FIELDS.items():
        if getattr(scanner, field, None) is not None:
            rejected.append(f"  - {field!r}: {reason}")

    if rejected:
        raise PrerequisiteError(
            "ScanJob/ScanJobConfig has fields that are not supported when "
            "passing a scanner to eval_set:\n" + "\n".join(rejected)
        )


def _normalize_filters(scanner: "Scanners | None") -> list[str]:
    """Extract SQL filter clauses from the scanner argument.

    `ScanJobConfig.filter` is the user-facing surface — a string or list
    of SQL WHERE clauses applied to the transcripts to scan. Scout's
    direct scan path applies these via `Transcripts.where(...)`; we lift
    them out and apply per-sample in `scan_eval_sample`.
    """
    from inspect_scout import ScanJobConfig

    if not isinstance(scanner, ScanJobConfig):
        return []
    raw = scanner.filter
    if isinstance(raw, list):
        return [f for f in raw if f]
    return [raw] if raw else []


def _sample_matches_filters(eval_sample: EvalSample, filters: list[str]) -> bool:
    """Return True if all SQL filter clauses match this sample.

    Filters are parsed and emitted as parameterized SQLite SQL via
    scout's `condition_from_sql` / `condition_as_sql` so the same
    column conventions (e.g. `error = ''`, JSON-path shorthand on
    `metadata.*`) work here as in scout's direct scan path. We then
    evaluate against a one-row in-memory sqlite table built from a
    small set of eval-sample fields scout exposes as standard
    transcript columns.
    """
    if not filters:
        return True

    import sqlite3
    from contextlib import closing

    from inspect_scout._query import condition_as_sql, condition_from_sql

    error_msg = eval_sample.error.message if eval_sample.error is not None else ""
    score_val = _score_value(eval_sample)
    success = _score_success(eval_sample)
    row: dict[str, Any] = {
        "error": error_msg,
        "task_id": str(eval_sample.id),
        "id": str(eval_sample.id),
        "task_repeat": eval_sample.epoch,
        "epoch": eval_sample.epoch,
        "score": score_val if isinstance(score_val, (int, float)) else None,
        "success": int(success) if isinstance(success, bool) else None,
        "message_count": len(eval_sample.messages),
        "total_time": eval_sample.total_time,
    }

    with closing(sqlite3.connect(":memory:")) as conn:
        cols_def = ", ".join(f'"{k}"' for k in row.keys())
        conn.execute(f"CREATE TABLE t ({cols_def})")
        placeholders = ", ".join(["?"] * len(row))
        conn.execute(f"INSERT INTO t VALUES ({placeholders})", list(row.values()))
        for clause in filters:
            where_sql, params = condition_as_sql(condition_from_sql(clause), "sqlite")
            cursor = conn.execute(f"SELECT 1 FROM t WHERE {where_sql}", params)
            if cursor.fetchone() is None:
                return False
    return True


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
