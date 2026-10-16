"""Merge the shard logs of a sharded run into one eval log."""

import functools
import json
import logging
import tempfile
import zipfile
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from typing import Literal, NamedTuple, TypeVar

import anyio

from inspect_ai._util._async import run_coroutine, tg_collect
from inspect_ai._util.async_zip import AsyncZipReader, is_torn_read
from inspect_ai._util.asyncfiles import AsyncFilesystem, is_s3_filename
from inspect_ai._util.file import FileInfo, basename, local_path, to_uri
from inspect_ai._util.log_layout import (
    eval_log_for_shards_dir,
    eval_shards_dir,
    log_basename,
)
from inspect_ai.log._log import EvalLog, EvalSampleSummary, EvalShardEntry
from inspect_ai.log._recorders.chunked.format import classify_sample_shape
from inspect_ai.log._recorders.eval import (
    SUMMARIES_JSON,
    _parse_summaries,
    _read_all_summaries_async,
    _read_header_async,
    _sample_filename,
)
from inspect_ai.log._recorders.recorder import SampleRecordKey

from ._delete import remove_shards_dir
from ._errors import ShardSetError, ShardSetIncomplete
from ._plan import (
    AttemptRead,
    Selection,
    Status,
    build_header,
    check_attempt_order,
    check_headers,
    check_ledger_count,
    check_reads,
    check_selection_covers,
    check_vanished,
    given_selection,
    is_unchanged,
    ledger_entry,
    merged_records,
    plan_status,
    recorded_selection,
    selected_total,
)
from ._publish import is_local, merge_guard, merged_log_copy, publish
from ._walk import ShardDir, list_shard_set
from ._write import task_file_import, write_merged_zip

logger = logging.getLogger(__name__)

_MAX_RESTARTS = 3
_MAX_CONCURRENT_READS = 16

T = TypeVar("T")


@dataclass(frozen=True)
class ShardMergeResult:
    """Result of :func:`merge_eval_log_shards`."""

    log: EvalLog
    """Header of the merged log (samples not loaded); `log.location` is its path."""

    written: bool
    """False when nothing had changed since the last merge and nothing was written."""

    shards_deleted: bool
    """True when this call deleted the shard files, or found none left.

    Checkpoint directories are not shard files and are left in place, so the
    shards directory may remain holding only them. Whenever the call returns,
    this equals `delete_shards`.
    """


def merge_eval_log_shards(
    log: str,
    *,
    sample_ids: Sequence[str | int] | None = None,
    sample_count: int | None = None,
    allow_incomplete: bool = False,
    delete_shards: bool = False,
) -> ShardMergeResult:
    """Merge the shard logs of a sharded run into one eval log.

    The shards of the log `<dir>/<name>.eval` are the `.eval` files in
    `<dir>/<name>.shards/<k>/`, one directory per worker. The current attempt
    of each shard is the newest file in its directory. The merged log holds
    exactly the samples each current attempt holds, with metrics recomputed
    over them, and records which attempts it holds (`eval.shards`), so a
    later call reads only the shards that changed and writes nothing when
    none did.

    Shards must be one task run: the same task, arguments, model, scorers,
    metrics, dataset size, epochs and log format, each started with its own
    `sample_id` or `limit` selection. Shard selections must not overlap and
    must not change between attempts in one shard directory.

    Deleting one shard directory by hand makes later merges refuse until the
    rest of the shards directory is deleted or the files are restored;
    deleting the whole shards directory leaves the merged log as it is.
    Header edits to the merged log (tags, metadata) are kept by later merges.
    Sample edits (for example `edit_score`) are kept until the shard holding
    the sample changes, so edit a merged log only once its shards are done.

    A local merged log is guarded by a lock file beside it and an S3 one by a
    conditional upload, so a merge that overlaps another is refused. Other
    storage backends have no guard: callers must not run two merges of one
    log at once. Metric recomputation may import the log's task file when a
    metric is not registered; a warning names the file.

    Args:
        log: The merged log `<dir>/<name>.eval`, or its shards directory
            `<dir>/<name>.shards`. A `<name>-recovered.eval` path is refused.
        sample_ids: Intended selection as sample ids. Replaces the selection
            recorded in the merged log; once the shards are deleted, it must
            equal the recorded one.
        sample_count: Intended selection as a number of samples (exclusive
            with `sample_ids`). Without either, the recorded selection is
            used, and on a first merge the set is complete when the shards
            hold the whole dataset.
        allow_incomplete: Write a `started` or `error` merged log when the
            set is incomplete, rather than raise `ShardSetIncomplete`.
        delete_shards: When the merged log is `success`, verify it and delete
            the shard files (every attempt and sample buffer), leaving
            checkpoint directories. Every worker must have exited, and
            nothing else may operate on this log or its shards while the call
            runs. If deletion is interrupted, run the call again or delete
            the shards directory by hand. Not allowed with `allow_incomplete`.

    Returns:
        The merged log's header, whether it was written, and whether the
        shards were deleted.

    Raises:
        ShardSetError: The shards cannot be merged (`ShardSelectionError`
            when they hold samples outside the selection).
        ShardSetIncomplete: The set is incomplete and `allow_incomplete` is
            not set. Nothing is written.
        WriteConflictError: Another merge holds the lock or published first.
            Run the merge again later.
        FileNotFoundError: Neither the merged log nor any shard exists.
        ValueError: Invalid arguments.
    """
    return run_coroutine(
        merge_eval_log_shards_async(
            log,
            sample_ids=sample_ids,
            sample_count=sample_count,
            allow_incomplete=allow_incomplete,
            delete_shards=delete_shards,
        )
    )


async def merge_eval_log_shards_async(
    log: str,
    *,
    sample_ids: Sequence[str | int] | None = None,
    sample_count: int | None = None,
    allow_incomplete: bool = False,
    delete_shards: bool = False,
) -> ShardMergeResult:
    """Merge the shard logs of a sharded run into one eval log.

    See :func:`merge_eval_log_shards`.
    """
    outcome = await merge_shards(
        log,
        sample_ids=sample_ids,
        sample_count=sample_count,
        allow_incomplete=allow_incomplete,
        delete_shards=delete_shards,
    )
    return outcome.result


class MergeOutcome(NamedTuple):
    """A merge's result, with what the CLI reports beyond it."""

    result: ShardMergeResult
    new_samples: int
    """Records the merged log did not hold before this call."""
    task_file_imported: str | None
    """Task file imported to resolve metrics, when the call wrote."""
    status: Status
    """The merged status, with the missing ids and running and failed shards."""


class _Merged(NamedTuple):
    """The existing merged log, as read at the start of a merge."""

    header: EvalLog
    records: set[SampleRecordKey]
    etag: str | None


class _Pass(NamedTuple):
    """What one pass decided."""

    header: EvalLog
    written: bool
    etag: str | None
    records: set[SampleRecordKey]
    new_samples: int
    task_file_imported: str | None
    status: Status


class _ShardChanged(Exception):
    """A shard read was torn: the shard changed after it was planned."""


async def merge_shards(
    log: str,
    *,
    sample_ids: Sequence[str | int] | None = None,
    sample_count: int | None = None,
    allow_incomplete: bool = False,
    delete_shards: bool = False,
    warn_task_file: bool = True,
) -> MergeOutcome:
    """Implement :func:`merge_eval_log_shards`, reporting what the CLI shows.

    `warn_task_file` logs a warning when metric recomputation imports the
    task file; the CLI turns it off and prints its own notice.
    """
    given = given_selection(sample_ids, sample_count)
    if delete_shards and allow_incomplete:
        raise ValueError("delete_shards cannot be combined with allow_incomplete.")
    location, merged_path, shards_dir = merge_paths(log)

    async with AsyncFilesystem() as fs:
        with merge_guard(merged_path):
            existing = await _read_merged(fs, merged_path)
            last: BaseException | None = None
            for _ in range(_MAX_RESTARTS + 1):
                try:
                    merge_pass = await _merge_pass(
                        fs,
                        merged_path,
                        shards_dir,
                        existing,
                        given,
                        allow_incomplete=allow_incomplete,
                        delete_shards=delete_shards,
                        warn_task_file=warn_task_file,
                    )
                    break
                except _ShardChanged as ex:
                    last = ex.__cause__
            else:
                assert last is not None
                raise last

            if delete_shards:
                await _verify(fs, merged_path, merge_pass)
                await remove_shards_dir(merged_path, fs=fs)

    header = merge_pass.header
    header.location = location
    return MergeOutcome(
        result=ShardMergeResult(
            log=header, written=merge_pass.written, shards_deleted=delete_shards
        ),
        new_samples=merge_pass.new_samples,
        task_file_imported=merge_pass.task_file_imported,
        status=merge_pass.status,
    )


class MergePaths(NamedTuple):
    """The paths of a merge (see :func:`merge_paths`)."""

    location: str
    """The merged log, in the form the argument was given in."""

    merged: str
    """The merged log as read and written."""

    shards_dir: str
    """Its shards directory, as read."""


def merge_paths(log: str) -> MergePaths:
    """The merged log and its shards directory, from either.

    A local ``file://`` URI is decoded to its path before anything is derived
    or checked from it, so an encoded name cannot pass a check its decoded
    form fails; the zip reader and the walk also need the decoded path.
    """
    target = local_path(log) if is_local(log) else log
    merged, shards_dir = _derive_paths(target)
    location = to_uri(merged) if log.startswith("file://") else merged
    return MergePaths(location, merged, shards_dir)


def _derive_paths(log: str) -> tuple[str, str]:
    location = log.rstrip("/\\")
    name = basename(location)
    if name.endswith(".shards") and name != ".shards":
        merged = eval_log_for_shards_dir(location)
        if eval_shards_dir(merged) != location:
            raise ValueError(
                f"{log} is named after a recovered log, which a merge does not "
                f"write: the shards directory of {merged} is "
                f"{eval_shards_dir(merged)}. Rename the directory to drop "
                "'-recovered'."
            )
        return merged, location
    if name.endswith(".eval"):
        shards_dir = eval_shards_dir(location)
        merged = eval_log_for_shards_dir(shards_dir)
        if f"{log_basename(location)}.eval" != name:
            raise ValueError(
                f"{log} is a recovered log name, which a merge does not write. "
                f"Merge into {merged} or pass {shards_dir}."
            )
        return location, shards_dir
    raise ValueError(
        f"Expected a merged log (<name>.eval) or its shards directory "
        f"(<name>.shards): {log}"
    )


async def _read_merged(fs: AsyncFilesystem, merged_path: str) -> _Merged | None:
    reader = AsyncZipReader(fs, merged_path)
    try:
        cd = await reader.entries()
    except FileNotFoundError:
        return None
    header = await _read_header_async(
        reader, {e.filename for e in cd.entries}, merged_path
    )
    if header.eval.shards is None:
        raise ShardSetError(
            f"{merged_path} is an ordinary log, not a merged log; refusing to "
            "overwrite it. Move or rename it, or the shards directory."
        )
    return _Merged(header, merged_records(cd, merged_path), reader.etag)


async def _merge_pass(
    fs: AsyncFilesystem,
    merged_path: str,
    shards_dir: str,
    existing: _Merged | None,
    given: Selection | None,
    *,
    allow_incomplete: bool,
    delete_shards: bool,
    warn_task_file: bool,
) -> _Pass:
    listing = await list_shard_set(fs, shards_dir)
    if listing.stray:
        raise ShardSetError(
            f"{shards_dir} holds log files that are not shard attempts: "
            + "; ".join(f"{s.path} ({s.reason})" for s in listing.stray)
        )
    shards = [s for s in listing.shards if s.current is not None]
    if not shards:
        if existing is None:
            raise FileNotFoundError(
                f"Neither {merged_path} nor any shard in {shards_dir} exists."
            )
        return _recorded_pass(existing, given, allow_incomplete, shards_gone=True)

    ledger = (
        {e.shard: e for e in _ledger(existing.header)} if existing is not None else {}
    )
    changed = [s for s in shards if not is_unchanged(ledger.get(s.name), _current(s))]
    for shard in changed:
        if shard.name in ledger:
            check_attempt_order(shard, ledger[shard.name])
    present = {s.name for s in shards}
    vanished = [name for name in ledger if name not in present]
    if vanished:
        assert existing is not None
        if delete_shards and existing.header.status == "success" and not changed:
            check_ledger_count(existing.records, ledger.values(), merged_path)
            return _recorded_pass(existing, given, allow_incomplete, shards_gone=False)
        check_vanished(vanished, merged_path, shards_dir)

    reads, readers = await _read_attempts(fs, changed)
    by_shard = {read.shard: read for read in reads}
    template = shards[0]
    headers = [(read.file.name, read.header) for read in reads]
    if template.name in by_shard:
        base = by_shard[template.name].header
    else:
        assert existing is not None
        if _ledger(existing.header)[0].shard == template.name:
            base = existing.header
        else:
            base = await _shard_read(_read_attempt_header(fs, template))
            headers.append((_current(template).name, base))
    if existing is not None and len(changed) < len(shards):
        headers.append((merged_path, existing.header))
    check_headers(headers)

    records = existing.records if existing is not None else set()
    if existing is not None:
        check_ledger_count(records, ledger.values(), merged_path)
    check_reads(reads, ledger, records, merged_path)

    read_ids: set[str] = set()
    for read in reads:
        read_ids |= read.selection or frozenset()
    carried = {key for key in records if key.sample_id not in read_ids}
    taken = {key: read for read in reads for key in read.summaries}
    keys = sorted(carried | taken.keys())
    entries = [
        ledger_entry(by_shard[s.name]) if s.name in by_shard else ledger[s.name]
        for s in shards
    ]
    recorded = (
        recorded_selection(existing.header)
        if existing is not None
        else Selection("none")
    )
    selection = given if given is not None else recorded
    held_ids = {key.sample_id for key in keys}
    check_selection_covers(selection, held_ids, [s.name for s in shards])
    epochs = base.eval.config.epochs or 1
    status = plan_status(entries, keys, selection, epochs, base.eval.dataset.samples)
    if status.status != "success" and not allow_incomplete:
        raise _incomplete(merged_path, status)

    if existing is not None and not changed and selection.same_as(recorded):
        return _Pass(existing.header, False, existing.etag, records, 0, None, status)

    with tempfile.TemporaryDirectory() as temp_dir:
        carried_zip: zipfile.ZipFile | None = None
        try:
            carried_summaries: dict[SampleRecordKey, EvalSampleSummary] = {}
            if carried:
                assert existing is not None
                copy = await merged_log_copy(fs, merged_path, existing.etag, temp_dir)
                carried_zip = zipfile.ZipFile(copy)
                carried_summaries = await anyio.to_thread.run_sync(
                    _read_carried_summaries, carried_zip, merged_path
                )
            summaries = []
            for key in keys:
                if key in taken:
                    summaries.append(taken[key].summaries[key])
                elif key in carried_summaries:
                    summaries.append(carried_summaries[key])
                else:
                    raise ShardSetError(
                        f"{merged_path} has no summary for sample {key.sample_id!r}, epoch "
                        f"{key.epoch}: it was changed outside the merge. Delete "
                        f"{merged_path} so the next merge rebuilds it from the shards."
                    )

            async def read_member(key: SampleRecordKey) -> bytes:
                read = taken.get(key)
                if read is not None:
                    reader = readers[read.shard]
                    return await _shard_read(
                        reader.read_member_fully(read.members[key])
                    )
                assert carried_zip is not None
                return await anyio.to_thread.run_sync(
                    carried_zip.read, _sample_filename(key.sample_id, key.epoch)
                )

            name = log_basename(merged_path)
            total = selected_total(selection, held_ids) * epochs
            # decided before recomputation imports the file and registers
            # its metrics
            imported = task_file_import(base)
            if imported is not None and warn_task_file:
                logger.warning(
                    f"Importing {imported} to resolve the metrics of the merged log."
                )
            with tempfile.TemporaryFile(dir=temp_dir) as out:
                header = await write_merged_zip(
                    out,
                    keys=keys,
                    read_member=read_member,
                    summaries=summaries,
                    template=base,
                    total_samples=total,
                    make_header=lambda results: build_header(
                        base=base,
                        merged=existing.header if existing is not None else None,
                        name=name,
                        status=status,
                        ledger=entries,
                        selection=selection,
                        summaries=summaries,
                        results=results,
                    ),
                )
                if carried_zip is not None:
                    carried_zip.close()
                    carried_zip = None
                etag = await publish(
                    fs,
                    merged_path,
                    out,
                    etag=existing.etag if existing is not None else None,
                    exists=existing is not None,
                )
        finally:
            if carried_zip is not None:
                carried_zip.close()

    return _Pass(
        header=header,
        written=True,
        etag=etag,
        records=set(keys),
        new_samples=len(set(keys) - records),
        task_file_imported=imported,
        status=status,
    )


def _recorded_pass(
    existing: _Merged,
    given: Selection | None,
    allow_incomplete: bool,
    *,
    shards_gone: bool,
) -> _Pass:
    """A pass that keeps the merged log as recorded (its shards deleted)."""
    header = existing.header
    recorded = recorded_selection(header)
    if given is not None and not given.same_as(recorded):
        raise ShardSetError(
            f"The shards of {header.location} were deleted; its selection can no "
            "longer change."
            if shards_gone
            else f"The shards of {header.location} are being deleted; its selection "
            "can no longer change."
        )
    status = plan_status(
        _ledger(header),
        existing.records,
        recorded,
        header.eval.config.epochs or 1,
        header.eval.dataset.samples,
    )
    if header.status != "success" and not allow_incomplete:
        raise _incomplete(header.location, status)
    return _Pass(header, False, existing.etag, existing.records, 0, None, status)


def _incomplete(location: str, status: Status) -> ShardSetIncomplete:
    merged_status: Literal["started", "error"] = (
        "error" if status.status == "error" else "started"
    )
    parts = []
    if status.missing:
        parts.append(f"{len(status.missing)} selected samples not held")
    if status.running:
        parts.append(f"running shards: {', '.join(status.running)}")
    if status.failed:
        parts.append(f"failed shards: {', '.join(status.failed)}")
    detail = f" ({'; '.join(parts)})" if parts else ""
    return ShardSetIncomplete(
        f"The shards of {location} are incomplete{detail}. Pass allow_incomplete "
        "to write an incomplete merged log.",
        status=merged_status,
        missing=status.missing,
        running=status.running,
        failed=status.failed,
    )


def _ledger(header: EvalLog) -> list[EvalShardEntry]:
    assert header.eval.shards is not None
    return header.eval.shards.ledger


def _current(shard: ShardDir) -> FileInfo:
    current = shard.current
    assert current is not None
    return current


async def _shard_read(read: Awaitable[T]) -> T:
    """Await a shard read, turning a torn read into :class:`_ShardChanged`."""
    try:
        return await read
    except Exception as ex:
        if is_torn_read(ex):
            raise _ShardChanged() from ex
        raise


async def _read_attempts(
    fs: AsyncFilesystem, shards: list[ShardDir]
) -> tuple[list[AttemptRead], dict[str, AsyncZipReader]]:
    limiter = anyio.CapacityLimiter(_MAX_CONCURRENT_READS)

    async def read(shard: ShardDir) -> tuple[AttemptRead, AsyncZipReader]:
        async with limiter:
            return await _shard_read(_read_attempt(fs, shard))

    results = await tg_collect([functools.partial(read, s) for s in shards])
    return [r for r, _ in results], {r.shard: reader for r, reader in results}


async def _read_attempt(
    fs: AsyncFilesystem, shard: ShardDir
) -> tuple[AttemptRead, AsyncZipReader]:
    info = _current(shard)
    reader = AsyncZipReader(fs, info.name, verify_crc=True)
    cd = await reader.entries()
    names = {e.filename for e in cd.entries}
    header = await _read_header_async(reader, names, info.name)
    summaries, _ = await _read_all_summaries_async(reader)
    held: dict[SampleRecordKey, EvalSampleSummary] = {}
    members = {}
    for summary in summaries:
        shape = classify_sample_shape(names, summary.id, summary.epoch)
        if shape == "chunked":
            raise ShardSetError(
                f"{info.name} stores sample {summary.id!r} (epoch {summary.epoch}) "
                "in the chunked shape, which the merge does not support."
            )
        if shape == "monolith":
            key = SampleRecordKey(str(summary.id), summary.epoch)
            entry = cd.entry(_sample_filename(summary.id, summary.epoch))
            assert entry is not None
            held[key] = summary
            members[key] = entry
    read = AttemptRead(
        shard=shard.name,
        file=info,
        header=header,
        summaries=held,
        members=members,
        etag=reader.etag,
    )
    return read, reader


async def _read_attempt_header(fs: AsyncFilesystem, shard: ShardDir) -> EvalLog:
    info = _current(shard)
    reader = AsyncZipReader(fs, info.name, verify_crc=True)
    cd = await reader.entries()
    return await _read_header_async(reader, {e.filename for e in cd.entries}, info.name)


def _read_carried_summaries(
    carried_zip: zipfile.ZipFile, location: str
) -> dict[SampleRecordKey, EvalSampleSummary]:
    if SUMMARIES_JSON not in carried_zip.namelist():
        return {}
    summaries = _parse_summaries(
        json.loads(carried_zip.read(SUMMARIES_JSON)), f"{location}/{SUMMARIES_JSON}"
    )
    return {SampleRecordKey(str(s.id), s.epoch): s for s in summaries}


async def _verify(fs: AsyncFilesystem, merged_path: str, merge_pass: _Pass) -> None:
    """Check the published merged log before its shards are deleted.

    Raises:
        ShardSetError: The merged log is not the one this call planned.
    """
    reader = AsyncZipReader(fs, merged_path)
    cd = await reader.entries()
    if is_s3_filename(merged_path) and reader.etag != merge_pass.etag:
        raise ShardSetError(
            f"{merged_path} changed after it was merged; its shards were not deleted."
        )
    header = await _read_header_async(
        reader, {e.filename for e in cd.entries}, merged_path
    )
    planned = merge_pass.header
    records = merged_records(cd, merged_path)
    epochs = planned.eval.config.epochs or 1
    expected = {
        SampleRecordKey(str(id), epoch)
        for id in planned.eval.dataset.sample_ids or []
        for epoch in range(1, epochs + 1)
    }
    if (
        header.status != "success"
        or header.eval.shards is None
        or planned.eval.shards is None
        or header.eval.shards.model_dump() != planned.eval.shards.model_dump()
        or records != expected
        or records != merge_pass.records
        or len(records) != sum(e.samples for e in planned.eval.shards.ledger)
    ):
        raise ShardSetError(
            f"{merged_path} does not hold what the merge planned; its shards were "
            "not deleted."
        )
