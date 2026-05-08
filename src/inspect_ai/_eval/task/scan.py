"""Per-sample scanner dispatch within `eval_set`.

See `design/eval-set-scanners.md` for the full design.
"""

import contextlib
import hashlib
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from inspect_ai._util._async import run_coroutine
from inspect_ai._util.file import absolute_file_path, dirname, exists
from inspect_ai._util.json import to_json_safe
from inspect_ai.log._log import EvalSample, EvalSpec

# Key used in `ScanSpec.metadata` to track inspect_ai-side scanner config
# that isn't captured by scout's `ScannerSpec`. Compared at scan_init's
# attach branch; mismatch raises `PrerequisiteError` so a config change
# can't silently leave historical transcripts unscanned.
_INSPECT_CONFIG_HASH_KEY = "__inspect_scan_config_hash__"

if TYPE_CHECKING:
    from inspect_scout import Scanner
    from inspect_scout._scanspec import ScanSpec


class EvalScannerConfig(BaseModel):
    """Configure scanners attached to an `eval_set` run.

    A subset of scout's `ScanJob` / `ScanJobConfig` schema, narrowed to
    the fields that make sense when `eval_set` is generating the
    transcripts.
    """

    # Fields from scout's `ScanJob` / `ScanJobConfig` are intentionally
    # omitted (rather than rejected at runtime) when they don't fit
    # eval_set's per-sample dispatch model:
    # - `transcripts` / `worklist`: would fight per-sample dispatch.
    # - `limit` / `shuffle` / `max_processes` / `max_transcripts`:
    #   sample-selection and concurrency knobs that belong to the eval.
    # - `validation`: needs labelled ground truth, which eval-generated
    #   transcripts don't have.
    # - `log_level`: collides with `eval_set`'s own logging setup.

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    scanners: Any
    """Scanners to run.

    `Sequence[Scanner | tuple[str, Scanner]]` for direct construction,
    `dict[str, Scanner]` for named scanners, or scout `ScannerSpec`
    references when loading from YAML/JSON config.
    """

    name: str | None = Field(default=None)
    """Override the scan name written to `_scan.json` (defaults to
    "eval_set")."""

    scans: str | None = Field(default=None)
    """Override scan output location. Defaults to `<log_dir>/scans/`."""

    tags: list[str] | None = Field(default=None)
    """Tags written to the scan spec."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Metadata written to the scan spec."""

    filter: str | list[str] = Field(default_factory=list)
    """SQL WHERE clause(s) applied per-sample to skip transcripts that
    don't match (e.g. `"error = ''"` to scan only successful samples).
    Mirrors scout's `Transcripts.where(...)` semantics."""

    model: Any = Field(default=None)
    """Model used by scanners' `get_model()`. Overrides the eval's
    active model just for the scanner call. `str | Model | None`."""

    model_base_url: str | None = Field(default=None)
    """Base URL for the scanner-side model API."""

    model_args: dict[str, Any] | None = Field(default=None)
    """Model creation args forwarded to scout."""

    generate_config: Any = Field(default=None)
    """`GenerateConfig` for scanner model calls."""

    model_roles: dict[str, Any] | None = Field(default=None)
    """Named roles available to scanners via `get_model(role=...)`."""

    @classmethod
    def from_file(cls, path: str) -> "EvalScannerConfig":
        """Load an `EvalScannerConfig` from a YAML or JSON config file.

        Scanner entries in the file are written as `ScannerSpec` references
        (a registry `name` plus optional `params` and `file`). They are
        resolved to live `Scanner` objects via scout's registry, loading
        any referenced `file` modules. `model_args` may also be a path to
        a separate YAML/JSON file, which is read and inlined.

        Args:
            path: Path or URL (e.g. `s3://...`) to a YAML or JSON file.

        Returns:
            A populated `EvalScannerConfig` ready to pass as
            `eval_set(scanner=...)`.
        """
        from inspect_ai._util.config import read_config_object, resolve_args
        from inspect_ai._util.error import PrerequisiteError
        from inspect_ai._util.file import file as open_fs_file
        from inspect_ai._util.file import filesystem
        from inspect_ai._util.path import pretty_path

        if not filesystem(path).exists(path):
            raise PrerequisiteError(
                f"Scanner config file '{pretty_path(path)}' does not exist."
            )

        with open_fs_file(path, "r") as f:
            raw = read_config_object(f.read())

        config = cls.model_validate(raw)

        # realize scanners from ScannerSpec form (list or dict of dicts)
        config.scanners = _realize_scanner_specs(config.scanners)

        # realize model_args if it points to a file
        if isinstance(config.model_args, str):
            config.model_args = resolve_args(config.model_args)

        return config


def _realize_scanner_specs(scanners: Any) -> Any:
    """Convert `ScannerSpec` entries (file form) to live `Scanner` objects."""
    from inspect_scout._scancontext import (
        scanners_from_spec_dict,
        scanners_from_spec_list,
    )
    from inspect_scout._scanspec import ScannerSpec

    if isinstance(scanners, dict):
        specs = {k: ScannerSpec.model_validate(v) for k, v in scanners.items()}
        return scanners_from_spec_dict(specs)
    if isinstance(scanners, list):
        spec_list = [ScannerSpec.model_validate(v) for v in scanners]
        return scanners_from_spec_list(spec_list)
    return scanners


EvalScanners: TypeAlias = (
    "Sequence[Scanner[Any] | tuple[str, Scanner[Any]]] "
    "| dict[str, Scanner[Any]] "
    "| EvalScannerConfig"
)
"""Argument shape accepted by `eval_set(scanner=...)`."""


async def scan_init(
    scanner: "EvalScanners",
    *,
    scan_id: str,
    log_dir: str,
) -> None:
    """Lay down the scan dir + initial summary for an eval run.

    On second-and-later runs against the same `scan_id` (e.g. eval_set
    resume after a partial failure), the scan dir already exists. Use
    `resume()` so the accumulated `_summary.json` is preserved and
    extended; `init()` would wipe it via `reset=True`.

    Validates that the scanner set passed on resume matches the one in
    the on-disk spec. Scout's `RecorderBuffer.record` looks up scanner
    metadata by name in the spec; any unknown scanner would `KeyError`
    mid-sample, get caught as a sample error, and silently corrupt the
    eval's success/failure result. We refuse upfront with a clear message.
    """
    from inspect_scout._recorder.file import FileRecorder
    from inspect_scout._scancontext import _spec_scanners
    from inspect_scout._scanspec import ScanOptions, ScanSpec

    scanners_dict = _normalize_scanners(scanner)
    scan_dir = _scan_dir(log_dir, scan_id, scanner)
    recorder = FileRecorder()

    from inspect_ai._eval.task.scan_display import reset_state, set_active

    reset_state()

    if exists(scan_dir):
        await recorder.attach(scan_dir, concurrent_writers=True)
        _verify_scanner_config_unchanged(
            prior=recorder.scan_spec,
            requested=scanner,
            requested_scanners_dict=scanners_dict,
        )
        _invalidate_finalized_flag(scan_dir)
        # don't seed samples_completed — the resume-scan short-circuit
        # path calls `mark_completed` for each reused sample, so the
        # counter naturally reaches `samples_total` over the run
        # without overcounting when re-executions happen (which they
        # do whenever PreviousTask reuse can't match samples)
        set_active(
            scan_dir=scan_dir,
            spec=_display_spec(recorder.scan_spec),
            summary=await recorder.summary(),
        )
        return

    # seed inspect_ai-side config hash into metadata so a future
    # reattach can detect changes to filter / model / model_args /
    # generate_config / model_roles / model_base_url
    metadata = dict(_normalize_metadata(scanner) or {})
    metadata[_INSPECT_CONFIG_HASH_KEY] = _scan_config_hash(scanner)
    spec = ScanSpec(
        scan_id=scan_id,
        scan_name=_normalize_scan_name(scanner),
        scanners=_spec_scanners(scanners_dict),
        options=ScanOptions(),
        tags=_normalize_tags(scanner),
        metadata=metadata,
    )
    await recorder.init(
        spec, _scans_location(log_dir, scanner), concurrent_writers=True
    )
    set_active(
        scan_dir=scan_dir,
        spec=_display_spec(spec),
        summary=await recorder.summary(),
    )


def _display_spec(spec: "ScanSpec") -> "ScanSpec":
    """Strip fields from `spec` that aren't meaningful for the display.

    `transcripts`: the on-disk snapshot from a prior finalize. Stale
    during a fresh run — `scan_title` would read its length and show
    e.g. "10 transcripts" while actually scanning 20. The progress
    bar's X/N surfaces the live total instead.

    `options.max_transcripts`: scout's worker-pool concurrency knob.
    inspect_ai's eval_set dispatches scanners via `_scan_one` directly
    instead of scout's process pool, so this value has no effect on
    the run — showing it in the panel header is misleading.
    """
    options = spec.options.model_copy(update={"max_transcripts": None})
    return spec.model_copy(update={"transcripts": None, "options": options})


async def scan_eval_sample(
    eval_sample: EvalSample,
    scanner: "EvalScanners | None",
    *,
    scan_id: str | None,
    eval_id: str,
    log_location: str,
    model: str | None = None,
    eval_spec: EvalSpec | None = None,
) -> None:
    """Run scanners over a completed sample's transcript.

    `log_location` may be relative (the value passed to `task_run_sample`
    is relative-to-eval_wd in the common case); resolved here to absolute
    so the derived scan dir matches the one registered by `scan_init`.

    `eval_spec` carries the eval-level metadata (model, task, tags,
    metadata, etc.) that scout's filter language can reference. The
    caller (`task_run_sample`) has it as `logger.eval`.
    """
    if scanner is None or scan_id is None:
        return
    log_location = absolute_file_path(log_location)
    scan_dir = _scan_dir(dirname(log_location), scan_id, scanner)
    if not exists(scan_dir):
        return

    # honor any SQL filter on a `ScanJobConfig` — samples that don't
    # match are not scanned at all (no parquet row, no entry in the
    # snapshot). Mirrors how scout's direct scan path filters via
    # `Transcripts.where(...)`, applied here per-sample because we
    # dispatch per-sample rather than reading from a query.
    if not _sample_matches_filters(
        eval_sample, _normalize_filters(scanner), eval_spec=eval_spec
    ):
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

    from inspect_ai._eval.task.scan_display import push_results

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
        push_results(summary=await recorder.summary(), scanner=name)


async def resume_scan_previous_sample(
    eval_sample: EvalSample,
    scanner: "EvalScanners | None",
    scanned_per_scanner: dict[str, set[str]],
    sample_semaphore: contextlib.AbstractAsyncContextManager[Any],
    *,
    scan_id: str | None,
    eval_id: str,
    log_location: str,
    model: str | None,
    eval_spec: EvalSpec | None = None,
) -> None:
    """Dispatch a scan for a reused sample if its row isn't already on disk.

    No-op when no scanner is configured, the snapshot says the prior
    scan finalized cleanly (`scanned_per_scanner` is empty), or every
    scanner already has a row for this transcript_id. Otherwise
    acquires `sample_semaphore` (so resume-scan work shares the same
    parallelism budget as the eval phase) and dispatches
    `scan_eval_sample`.
    """
    from inspect_ai._eval.task.scan_display import mark_completed

    tid = eval_sample.uuid
    if scanner is None or not scanned_per_scanner or tid is None:
        return
    if all(tid in s for s in scanned_per_scanner.values()):
        # every scanner already has this tid — no scan work needed.
        # Bump the progress counter for the (sample, scanner) pairs
        # that this skip represents so the bar reflects the work done
        # in prior runs.
        mark_completed(len(scanned_per_scanner))
        return
    async with sample_semaphore:
        await scan_eval_sample(
            eval_sample,
            scanner,
            scan_id=scan_id,
            eval_id=eval_id,
            log_location=log_location,
            model=model,
            eval_spec=eval_spec,
        )


async def scan_finalize(
    *,
    scan_id: str,
    log_dir: str,
    scanner: "EvalScanners | None" = None,
) -> None:
    """Compact buffer parquets and snapshot the recorded transcripts.

    The transcripts snapshot is what scout's `scan_resume` uses to know
    which transcripts existed in the scan. We sync first — that merges
    this call's buffer with the previously-compacted parquet (via
    `extra_inputs`) into the canonical output. The post-sync compacted
    parquet contains every transcript ever recorded for this scan
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
    from inspect_scout._recorder.file import FileRecorder
    from upath import UPath

    scan_dir = _scan_dir(log_dir, scan_id, scanner)
    if not exists(scan_dir):
        return

    # only mark complete if no scanner errors — otherwise leave the scan
    # in an "incomplete" state so scout's `scan_resume` can pick up the
    # failed scans. status() reads errors from the buffer dir while it
    # still exists (cleanup happens inside sync when complete=True).
    pre_sync_status = await FileRecorder.status(scan_dir)
    complete = not pre_sync_status.errors

    await FileRecorder.sync(scan_dir, complete=complete)

    if scanner is not None:
        await _cleanup_orphan_scan_rows(scan_dir, log_dir, scanner)

    snapshot = _snapshot_from_compacted(UPath(scan_dir), log_dir=log_dir)
    if snapshot is not None:
        _write_snapshot_to_scan_spec(UPath(scan_dir), snapshot)


def _invalidate_finalized_flag(scan_dir: str) -> None:
    """Flip `_summary.json`'s `complete` to `False` in place.

    Called by `scan_init` when attaching to an existing scan_dir, so
    the persisted finalize signal is reset for the current call.
    Stats (model_usage, tokens, per-scanner counts) are preserved;
    only the boolean flag is flipped. `scan_finalize` will rewrite
    the whole file at sync time with the correct flag.
    """
    import json

    from upath import UPath

    summary_path = UPath(scan_dir) / "_summary.json"
    if not summary_path.exists():
        return
    data = json.loads(summary_path.read_text())
    if data.get("complete") is True:
        data["complete"] = False
        summary_path.write_text(json.dumps(data))


def scan_already_clean(
    scanner: "EvalScanners | None", scan_id: str, log_dir: str
) -> bool:
    """True if the prior scan finalized cleanly and no call has run since.

    Used by `eval_set` to short-circuit the success-logs-as-PreviousTask
    routing when there's nothing for the per-sample resume-scan to find.
    Safe because `scan_init` invalidates `complete=False` on every
    attach, so this only reads `True` when the most recent prior
    call's finalize wrote it AND no subsequent call has started.

    Returns False when no scanner is configured, no scan dir exists,
    or `_summary.json`'s `complete` is False/missing.
    """
    if scanner is None:
        return False
    return _scan_finalized_clean(_scan_dir(log_dir, scan_id, scanner))


def _scan_finalized_clean(scan_dir: str) -> bool:
    """True if the most recent call's `scan_finalize` ran with no errors.

    Reads `_summary.json` at the scan_dir, which is rewritten by
    `_sync_status_files` at every `scan_finalize`. `scan_init`
    invalidates `complete` to `False` when attaching to an existing
    scan_dir, so a `True` value here means "the most recent call's
    finalize wrote this and recorded no errors" — i.e. every logged
    sample has a row, no resume-scan needed.

    A `False` (or absent) summary means either: a prior call crashed
    before finalize (the `complete=False` was written by `scan_init`
    of *this* call, and not yet overwritten), or the prior call had
    scanner errors. In either case the per-sample check has work to
    do — at minimum to confirm there are no missing rows.
    """
    import json

    from upath import UPath

    summary_path = UPath(scan_dir) / "_summary.json"
    if not summary_path.exists():
        return False
    return bool(json.loads(summary_path.read_text()).get("complete"))


def scanned_transcripts_for_resume(
    scanner: "EvalScanners | None",
    scan_id: str | None,
    log_location: str,
) -> dict[str, set[str]]:
    """Per-scanner set of transcript_ids that already have a parquet row.

    Returned dict gates the per-sample resume-scan check in
    `task_run`: if a reused sample's `transcript_id` is in any
    scanner's set, the dispatch is short-circuited and the display's
    progress counter is bumped via `mark_completed`. If a sample's tid
    isn't in every scanner's set, `scan_eval_sample` is dispatched and
    the display is updated via `push_results`.

    An empty dict means "skip the check entirely" and is returned
    when:

    - no scanner is configured;
    - no `scan_id` is set;
    - the scan dir doesn't exist (no prior scan laid it down — or
      this call's `scan_init` will create it fresh, in which case the
      caller's own per-sample dispatch already handles the work).

    Note: even on a cleanly-finalized prior scan, we return the full
    set — the membership check feeds the display's progress counter
    via `mark_completed`, so we can't elide the read.
    """
    if scanner is None or scan_id is None:
        return {}

    scan_dir = _scan_dir(dirname(absolute_file_path(log_location)), scan_id, scanner)
    if not exists(scan_dir):
        return {}

    return {
        name: _scanned_transcript_ids(scan_dir, name)
        for name in _normalize_scanners(scanner)
    }


async def _cleanup_orphan_scan_rows(
    scan_dir: str, log_dir: str, scanner: "EvalScanners"
) -> None:
    """Drop scan rows whose transcript_id has no corresponding sample.

    Sample-level retries (`retry_immediate`) and the legacy eval_set
    retry path re-run failed samples with fresh uuids, then
    `retry_cleanup` deletes the older log files. Their transcript_ids
    survive in the scan parquet (and possibly the buffer) but no
    longer match any `EvalSample`. This sweeps those orphans.

    Reads sample uuids from all surviving eval logs (cheap — only
    summaries), filters each scanner's compacted parquet to just
    those uuids, and unlinks any orphan buffer files.
    """
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    from inspect_scout._recorder.buffer import RecorderBuffer, _sanitize_component
    from upath import UPath

    from inspect_ai.log._file import (
        list_eval_logs,
        read_eval_log_sample_summaries_async,
    )

    live_tids: set[str] = set()
    for log_info in list_eval_logs(log_dir):
        for summary in await read_eval_log_sample_summaries_async(log_info.name):
            if summary.uuid is not None:
                live_tids.add(summary.uuid)

    live_array = pa.array(sorted(live_tids), type=pa.string())
    buffer_dir = RecorderBuffer.buffer_dir(scan_dir)

    for name in _normalize_scanners(scanner):
        # filter the compacted parquet — read per-row-group to avoid
        # cross-row-group schema merging (scout's writer can produce
        # row groups with differing dictionary states)
        parquet_path = UPath(scan_dir) / f"{name}.parquet"
        if parquet_path.exists():
            pf = pq.ParquetFile(parquet_path.as_posix())
            schema = pf.schema_arrow
            out_buf = pa.BufferOutputStream()
            writer = pq.ParquetWriter(
                out_buf, schema, compression="zstd", use_dictionary=True
            )
            removed = False
            for i in range(pf.num_row_groups):
                rg = pf.read_row_group(i)
                mask = pc.is_in(rg.column("transcript_id"), value_set=live_array)
                filtered = rg.filter(mask)
                if filtered.num_rows < rg.num_rows:
                    removed = True
                if filtered.num_rows > 0:
                    writer.write_table(filtered)
            writer.close()
            if removed:
                UPath(parquet_path).write_bytes(out_buf.getvalue().to_pybytes())

        # clean orphaned buffer files (relevant when complete=False
        # left the buffer in place; complete=True already cleaned it)
        sdir = buffer_dir / f"scanner={_sanitize_component(name)}"
        if sdir.exists():
            for p in sdir.glob("*.parquet"):
                if p.stem not in live_tids:
                    p.unlink()


def _scanned_transcript_ids(scan_dir: str, scanner_name: str) -> set[str]:
    """Transcript ids already recorded for `scanner_name` in `scan_dir`.

    Combines the in-flight buffer's per-transcript file stems with the
    `transcript_id` column of the compacted parquet (if present) so the
    "is this transcript scanned" check works whether or not the most
    recent sync was complete=True (which cleans the buffer).
    """
    import pyarrow.parquet as pq
    from inspect_scout._recorder.buffer import RecorderBuffer, _sanitize_component
    from upath import UPath

    ids: set[str] = set()

    # in-flight buffer: <buffer_dir>/scanner=<sanitized>/<tid>.parquet
    buffer_dir = RecorderBuffer.buffer_dir(scan_dir)
    sdir = buffer_dir / f"scanner={_sanitize_component(scanner_name)}"
    if sdir.exists():
        for p in sdir.glob("*.parquet"):
            ids.add(p.stem)

    # post-sync compacted parquet — read row-group-by-row-group to avoid
    # pyarrow's cross-row-group schema-merge error on scout's dictionary-
    # encoded `scan_id` column. Same pattern as `_cleanup_orphan_scan_rows`.
    parquet_path = UPath(scan_dir) / f"{scanner_name}.parquet"
    if parquet_path.exists():
        pf = pq.ParquetFile(parquet_path.as_posix())
        for i in range(pf.metadata.num_row_groups):
            rg = pf.read_row_group(i, columns=["transcript_id"])
            ids.update(t for t in rg.column("transcript_id").to_pylist() if t)

    return ids


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
def scan_context(
    scanner: "EvalScanners | None",
    *,
    scan_id: str,
    log_dir: str,
) -> Iterator[None]:
    """Initialize scan state on enter, compact on exit. No-op when scanner is None."""
    if scanner is None:
        yield
        return
    run_coroutine(scan_init(scanner, scan_id=scan_id, log_dir=log_dir))
    try:
        yield
    finally:
        run_coroutine(scan_finalize(scan_id=scan_id, log_dir=log_dir, scanner=scanner))


def print_scan_status(log_dir: str) -> None:
    """Print the most recent scan dir's final status as plain text.

    Called from `eval` / `eval_set` after they have rendered their
    final output (the display panel + `Log:` line / "Completed all
    tasks" message), so the message lands at the very end. Mirrors
    `scout scan`'s standalone output (the same
    `scout scan resume <path>` / `scout scan complete <path>` commands
    when there are errors), but rendered plain — no rich markup, no
    color — to keep the trailing summary unobtrusive.

    Picks the scan dir with the most recent `_summary.json` mtime
    when a `log_dir` has multiple, so the message reflects the call
    that just finished. No-op when no scan dir exists.

    Callers are responsible for ensuring there's a blank line of
    separation above this output — this function does not emit one.
    """
    import shlex
    from pathlib import Path

    from inspect_scout._recorder.file import FileRecorder

    from inspect_ai._util.path import pretty_path

    scans_dir = Path(log_dir) / "scans"
    if not scans_dir.exists():
        return

    scan_dirs = [
        d for d in scans_dir.iterdir() if d.is_dir() and (d / "_summary.json").exists()
    ]
    if not scan_dirs:
        return
    scan_dir = max(scan_dirs, key=lambda d: (d / "_summary.json").stat().st_mtime)

    status = run_coroutine(FileRecorder.status(str(scan_dir)))

    path = shlex.quote(pretty_path(str(scan_dir)))
    if status.complete:
        print(f"scan complete: {path}\n")
    else:
        print(f"{len(status.errors)} scan errors occurred!\n")
        print(f"Resume (retrying errors):   scout scan resume {path}")
        print(f"Complete (ignoring errors): scout scan complete {path}\n")


def _scans_location(log_dir: str, scanner: "EvalScanners | None" = None) -> str:
    """Where scan outputs land.

    Defaults to `<log_dir>/scans/`. A `ScanJob`/`ScanJobConfig` may
    override via its `scans` field — that gets used as the location
    directly so the user can write scan results to a different
    filesystem (e.g. an S3 bucket) than the eval logs.
    """
    base = _normalize_scans(scanner) or f"{log_dir.rstrip('/')}/scans"
    return base.rstrip("/")


def _scan_dir(log_dir: str, scan_id: str, scanner: "EvalScanners | None" = None) -> str:
    return f"{_scans_location(log_dir, scanner)}/scan_id={scan_id}"


def _normalize_scanners(
    scanner: "EvalScanners | None",
) -> "dict[str, Scanner[Any]]":
    from inspect_scout import ScanJob

    if scanner is None:
        return {}
    if isinstance(scanner, EvalScannerConfig):
        return ScanJob(scanners=scanner.scanners)._scanners
    return ScanJob(scanners=scanner)._scanners


def _normalize_scans(scanner: "EvalScanners | None") -> str | None:
    """Extract the scan-output-location override (`scans`), if any."""
    if isinstance(scanner, EvalScannerConfig):
        return scanner.scans
    return None


def _normalize_tags(scanner: "EvalScanners | None") -> list[str] | None:
    """Tags carried on `EvalScannerConfig`, written into the scan spec."""
    if isinstance(scanner, EvalScannerConfig):
        return scanner.tags
    return None


def _normalize_scan_name(scanner: "EvalScanners | None") -> str:
    """Scan-name override from `EvalScannerConfig`, else "eval_set"."""
    if isinstance(scanner, EvalScannerConfig):
        return scanner.name or "eval_set"
    return "eval_set"


def _normalize_metadata(scanner: "EvalScanners | None") -> "dict[str, Any] | None":
    """Metadata carried on `EvalScannerConfig`, written into the scan spec."""
    if isinstance(scanner, EvalScannerConfig):
        return scanner.metadata
    return None


def _install_scan_model_context(scanner: "EvalScanners | None") -> None:
    """Install scout's scan-time model context for this sample, if set.

    When `EvalScannerConfig` carries `model` (or related
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
    from inspect_scout._scan import init_scan_model_context

    if not isinstance(scanner, EvalScannerConfig):
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


def _verify_scanner_config_unchanged(
    *,
    prior: "ScanSpec",
    requested: "EvalScanners | None",
    requested_scanners_dict: "dict[str, Scanner[Any]]",
) -> None:
    """Raise `PrerequisiteError` if the scanner config differs from `prior`.

    Three checks, ordered cheapest first:

    1. Scanner names match. Adding or removing a scanner means the new
       run wants different output than the scan dir holds.
    2. Each scanner's `ScannerSpec` matches (params, version, file,
       package_version). Same name + different code/params produces
       different output for the same transcript.
    3. Eval-set-level config hash matches (filter / model /
       model_args / generate_config / model_roles / model_base_url).
       These aren't in scout's `ScannerSpec`; a change to them affects
       which transcripts get scanned or how, but would otherwise
       silently reuse prior parquet rows.

    Each check raises with a message naming the change and pointing
    at the resolution (`log_dir` / `scan_id` swap).
    """
    from inspect_scout._scancontext import _spec_scanners

    from inspect_ai._util.error import PrerequisiteError

    existing_names = set(prior.scanners.keys())
    requested_names = set(requested_scanners_dict.keys())
    if existing_names != requested_names:
        raise PrerequisiteError(
            "Scanner set has changed from the prior run on this "
            "log_dir.\n"
            f"  Prior:     {sorted(existing_names)}\n"
            f"  Requested: {sorted(requested_names)}\n"
            "Either match the prior scanner set or use a different "
            "log_dir / scan_id."
        )

    new_scanners = _spec_scanners(requested_scanners_dict)
    for name in sorted(requested_names):
        if prior.scanners[name] != new_scanners[name]:
            raise PrerequisiteError(
                f"Scanner '{name}' config has changed from the prior "
                "run on this log_dir.\n"
                f"  Prior:     {prior.scanners[name].model_dump(exclude_none=True)}\n"
                f"  Requested: {new_scanners[name].model_dump(exclude_none=True)}\n"
                "Use a different log_dir / scan_id to start fresh, or "
                "revert the change."
            )

    prior_hash = (prior.metadata or {}).get(_INSPECT_CONFIG_HASH_KEY)
    new_hash = _scan_config_hash(requested)
    if prior_hash != new_hash:
        raise PrerequisiteError(
            "Eval-set-level scanner config (filter, model, "
            "model_args, generate_config, model_roles, "
            "model_base_url) has changed from the prior run on "
            "this log_dir.\n"
            "Use a different log_dir / scan_id to start fresh, or "
            "revert the change."
        )


def _scan_config_hash(scanner: "EvalScanners | None") -> str:
    """Hash inspect_ai-side scanner config that isn't in `ScannerSpec`.

    Scout's `ScannerSpec` already captures per-scanner identity
    (name, version, file, package_version, params); equality on those
    is checked separately. This function covers the eval_set-level
    fields that affect what gets scanned and how — filter, model,
    model_args, generate_config, model_roles, model_base_url —
    none of which round-trip through scout's spec.

    Stable across runs of the same config so a no-op reattach doesn't
    invalidate the prior scan. Excludes labels (`name`, `tags`,
    `metadata`, `scans`) — changing those shouldn't force a rescan.

    Non-EvalScannerConfig inputs (raw scanner list/dict) hash to a
    canonical "no eval-side config" value, identical to passing an
    EvalScannerConfig with all defaults.

    `Model` instances passed for `model` / `model_roles[*]` are
    coerced via `str()` first because `to_json_safe`'s fallback drops
    non-serializable objects to None — losing the discriminator we
    want to detect. `str(model)` produces "<api>/<name>", stable
    across runs of the same model.
    """
    config = scanner if isinstance(scanner, EvalScannerConfig) else None
    payload = {
        "filter": _normalize_filters(scanner),
        "model": str(config.model) if (config and config.model is not None) else None,
        "model_base_url": config.model_base_url if config else None,
        "model_args": config.model_args if config else None,
        "generate_config": config.generate_config if config else None,
        "model_roles": (
            {k: str(v) for k, v in config.model_roles.items()}
            if (config and config.model_roles)
            else None
        ),
    }
    return hashlib.sha256(to_json_safe(payload, indent=None)).hexdigest()


def _normalize_filters(scanner: "EvalScanners | None") -> list[str]:
    """Extract SQL filter clauses from the scanner argument.

    `EvalScannerConfig.filter` is the user-facing surface — a string
    or list of SQL WHERE clauses applied to the transcripts to scan.
    Scout's direct scan path applies these via `Transcripts.where(...)`;
    we lift them out and apply per-sample in `scan_eval_sample`.
    """
    if not isinstance(scanner, EvalScannerConfig):
        return []
    raw = scanner.filter
    if isinstance(raw, list):
        return [f for f in raw if f]
    return [raw] if raw else []


def _sample_matches_filters(
    eval_sample: EvalSample,
    filters: list[str],
    *,
    eval_spec: EvalSpec | None = None,
) -> bool:
    """Return True if all SQL filter clauses match this sample.

    Filters are parsed and emitted as parameterized SQLite SQL via
    scout's `condition_from_sql` / `condition_as_sql` so filters valid
    against scout's direct scan path also evaluate correctly here.
    The row that backs the WHERE clause mirrors scout's
    `TranscriptColumns` schema — every column scout exposes is
    populated (eval-level fields from `eval_spec`, sample-level from
    `eval_sample`); JSON columns are stored as JSON strings so
    `json_extract`-based shorthand (e.g. `sample_metadata.group =
    'a'`) works.

    sqlite's "double-quoted string literal" compatibility mode is
    disabled so a typo'd column name surfaces as
    `OperationalError: no such column` rather than silently comparing
    a string literal — that quirk previously hid bugs like
    `model = 'x'` evaluating against a missing column and returning
    False rather than raising.
    """
    if not filters:
        return True

    import re
    import sqlite3
    from contextlib import closing

    from inspect_scout._query import condition_as_sql, condition_from_sql

    row = _filter_row(eval_sample, eval_spec)
    valid_columns = set(row.keys())

    # Column names get interpolated into `CREATE TABLE` (sqlite has no
    # parameter form for identifiers). They mostly come from scout's
    # static `TranscriptColumns`, but `score_*` expands with arbitrary
    # score names from the eval — a name containing `"` would close
    # the identifier and inject SQL. Escape per the SQL standard
    # ("" inside a quoted identifier is a literal quote).
    def _quote_ident(name: str) -> str:
        return '"' + name.replace('"', '""') + '"'

    with closing(sqlite3.connect(":memory:")) as conn:
        cols_def = ", ".join(_quote_ident(k) for k in row.keys())
        conn.execute(f"CREATE TABLE t ({cols_def})")
        placeholders = ", ".join(["?"] * len(row))
        conn.execute(f"INSERT INTO t VALUES ({placeholders})", list(row.values()))
        for clause in filters:
            where_sql, params = condition_as_sql(condition_from_sql(clause), "sqlite")
            # Pre-validate column references: scout's emitted SQL
            # double-quotes identifiers (`"col" = ?` or
            # `json_extract("col", '$.key')`). sqlite's DQS-compat
            # mode would silently turn `"unknown_col"` into the
            # string literal `'unknown_col'` and the comparison
            # always evaluates to False — masking typo'd or
            # unsupported column references. Single-quoted strings
            # inside JSON paths (e.g. `'$.group'`) are unaffected.
            for col in re.findall(r'"([^"]+)"', where_sql):
                if col not in valid_columns:
                    raise sqlite3.OperationalError(
                        f"no such column: {col} (filter: {clause!r})"
                    )
            cursor = conn.execute(f"SELECT 1 FROM t WHERE {where_sql}", params)
            if cursor.fetchone() is None:
                return False
    return True


def _filter_row(eval_sample: EvalSample, eval_spec: EvalSpec | None) -> dict[str, Any]:
    """Build the single sqlite row used to evaluate filter clauses.

    Iterates scout's `TranscriptColumns` and applies each column's
    extractor via inspect_ai's `import_record`. Two passes — eval-level
    columns get the synthesized `EvalLog` as the record (so paths like
    `eval.model` resolve and callable extractors like `_source_type`
    fire), sample-level columns get the `EvalSample`. The merged dict
    is the row we INSERT into our in-memory sqlite table; JSON columns
    are already JSON-encoded strings (handled by the column's `value`
    function), so `json_extract` shorthand like `sample_metadata.group
    = 'a'` works.

    Defining the row this way means new columns added to scout's
    `TranscriptColumns` automatically flow through with no change here.
    """
    from inspect_scout._transcript.eval_log import TranscriptColumns

    from inspect_ai.analysis._dataframe.evals.columns import EvalColumn
    from inspect_ai.analysis._dataframe.record import import_record
    from inspect_ai.analysis._dataframe.samples.columns import SampleColumn
    from inspect_ai.log._log import EvalLog

    log = (
        EvalLog(eval=eval_spec, status="started")
        if eval_spec is not None
        # `import_record`'s eval-level extractors require an EvalLog —
        # callers that omit `eval_spec` get an empty stand-in so
        # sample-level columns still extract; eval-level columns end
        # up as None.
        else EvalLog.model_construct(eval=None, status="started")  # type: ignore[arg-type]
    )

    eval_cols = [c for c in TranscriptColumns if isinstance(c, EvalColumn)]
    sample_cols = [c for c in TranscriptColumns if isinstance(c, SampleColumn)]

    eval_row, _ = import_record(log, log, eval_cols, strict=False)
    sample_row, _ = import_record(log, eval_sample, sample_cols, strict=False)

    return {**eval_row, **sample_row}


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
