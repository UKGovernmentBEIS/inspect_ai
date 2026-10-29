"""Merge the shard logs of a sharded run into one eval log."""

import functools
import json
import tempfile
import zipfile
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple

import anyio

from inspect_ai._util._async import run_coroutine, tg_collect
from inspect_ai._util.async_zip import AsyncZipReader, CentralDirectory
from inspect_ai._util.asyncfiles import AsyncFilesystem, is_s3_filename
from inspect_ai._util.constants import get_deserializing_context
from inspect_ai._util.file import FileInfo, basename, local_path, to_uri
from inspect_ai._util.log_layout import (
    eval_log_for_shards_dir,
    eval_shards_dir,
    log_basename,
)
from inspect_ai.log._log import (
    EvalLog,
    EvalSampleReductions,
    EvalSampleScore,
    EvalSampleSummary,
    EvalShardEntry,
)
from inspect_ai.log._recorders.chunked.format import classify_sample_shape
from inspect_ai.log._recorders.eval import (
    REDUCTIONS_JSON,
    SUMMARIES_JSON,
    _parse_summaries,
    _read_all_summaries_async,
    _read_header_async,
    _read_member_json,
    _sample_filename,
)
from inspect_ai.log._recorders.recorder import SampleRecordKey

from ._delete import check_deletable, remove_shards_dir
from ._errors import ShardSetError, ShardSetIncomplete
from ._plan import (
    AttemptRead,
    Selection,
    Status,
    attempt_regressed,
    build_header,
    check_attempt_order,
    check_headers,
    check_ledger_count,
    check_reads,
    check_resolved,
    check_selection_covers,
    check_vanished,
    given_selection,
    is_unchanged,
    ledger_entry,
    merged_records,
    parse_sample_member,
    plan_status,
    recorded_selection,
    selected_total,
)
from ._publish import is_local, merge_guard, merged_log_copy, publish
from ._walk import ShardDir, check_s3_location, is_recovered_attempt, list_shard_set
from ._write import (
    HeldReductions,
    check_retained_reductions,
    check_scoring_resolvable,
    edited_score_message,
    write_merged_zip,
)

_MAX_CONCURRENT_READS = 16


@dataclass(frozen=True)
class ShardMergeResult:
    """Result of :func:`merge_eval_log_shards`."""

    log: EvalLog
    """Header of the merged log (samples not loaded); `log.location` is its path."""

    written: bool
    """False when nothing had changed since the last merge and nothing was written."""

    shards_deleted: bool
    """True when this call deleted the shards directory, or found it gone.

    Whenever the call returns, this equals `delete_shards`.
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
    `edit_score()`, `recompute_metrics()` and `score()` refuse a merged log
    while its shards directory exists: merge with `delete_shards` first.

    A local merged log is guarded by a lock file beside it and an S3 one by a
    conditional upload, so a merge that overlaps another is refused. Other
    storage backends have no guard: callers must not run two merges of one
    log at once.

    Metrics are resolved from the registry only: built in, from installed
    packages, or imported by the caller. The merge never imports the log's
    task file; to merge a log whose task defines its own metric, import that
    module first and merge from Python. Epoch reducers are not recreated:
    with a reducer configured, each sample's reduced scores are taken from
    the shard that ran it, which records them when it finishes. While a
    shard holding samples is still running, an incomplete merged log has no
    results. A finished shard without recorded reductions, a recovered shard
    log (`-recovered.eval`), two reducers with the same name and a score
    edited in a shard or the merged log (`edit_score`) refuse the merge,
    since the reductions cannot be established. Do not recover a shard's
    log; re-run the shard. A shard log recovered with `overwrite` or to
    another output path cannot be told apart from a finished log, and with
    an epoch reducer that takes arguments or a value converter the merged
    metrics for its samples may be wrong (default reducers are not
    affected).

    A merge that runs while a worker is writing its shard can fail with a
    read error (for example a CRC or JSON error). Nothing is written; run
    the merge again, or merge after the workers have exited.

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
            the whole shards directory, including checkpoint directories and
            anything else in it. Every worker must have exited, and nothing
            else may operate on this log or its shards while the call runs.
            If deletion is interrupted, run the call again or delete the
            shards directory by hand. Not allowed with `allow_incomplete`.

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
        LookupError: A metric is not registered. Nothing is written.
        ValueError: Invalid arguments, or `delete_shards` for a remote log
            whose location holds a glob character (`*`, `?`, `[`), which the
            storage backend would expand to other paths.
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
    status: Status
    check_retained: bool
    """Whether deleting the shards must first check that the merged log keeps
    trusted reductions (no edited score, none missing): nothing was written
    and shard attempts remain."""


async def merge_shards(
    log: str,
    *,
    sample_ids: Sequence[str | int] | None = None,
    sample_count: int | None = None,
    allow_incomplete: bool = False,
    delete_shards: bool = False,
) -> MergeOutcome:
    """Implement :func:`merge_eval_log_shards`, reporting what the CLI shows."""
    given = given_selection(sample_ids, sample_count)
    if delete_shards and allow_incomplete:
        raise ValueError("delete_shards cannot be combined with allow_incomplete.")
    location, merged_path, shards_dir = merge_paths(log)
    check_s3_location(merged_path)
    check_s3_location(shards_dir)
    if delete_shards:
        check_deletable(merged_path)

    async with AsyncFilesystem() as fs:
        with merge_guard(merged_path):
            existing = await _read_merged(fs, merged_path)
            merge_pass = await _merge_pass(
                fs,
                merged_path,
                shards_dir,
                existing,
                given,
                allow_incomplete=allow_incomplete,
                delete_shards=delete_shards,
            )
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
    regressed = [
        s for s in changed if s.name in ledger and attempt_regressed(s, ledger[s.name])
    ]
    present = {s.name for s in shards}
    vanished = [name for name in ledger if name not in present]
    if (
        delete_shards
        and existing is not None
        and existing.header.status == "success"
        and (vanished or regressed)
        and len(regressed) == len(changed)
    ):
        # what an interrupted deletion leaves: shards that lost their merged
        # attempt, and none new or changed since the merge
        check_ledger_count(existing.records, ledger.values(), merged_path)
        await _check_merged_resolved(
            fs, [s for s in shards if s not in changed], ledger
        )
        return _recorded_pass(existing, given, allow_incomplete, shards_gone=False)
    for shard in regressed:
        check_attempt_order(shard, ledger[shard.name])
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
            base = await _read_attempt_header(fs, template)
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
        if delete_shards:
            await _check_merged_resolved(fs, shards, ledger)
        return _Pass(existing.header, False, existing.etag, records, 0, status, True)

    check_scoring_resolvable(base)
    with tempfile.TemporaryDirectory() as temp_dir:
        carried_zip: zipfile.ZipFile | None = None
        try:
            carried_summaries: dict[SampleRecordKey, EvalSampleSummary] = {}
            carried_reductions: list[EvalSampleReductions] = []
            if carried:
                assert existing is not None
                copy = await merged_log_copy(fs, merged_path, existing.etag, temp_dir)
                carried_zip = zipfile.ZipFile(copy)
                carried_summaries = await anyio.to_thread.run_sync(
                    _read_carried_summaries, carried_zip, merged_path
                )
                if base.eval.config.epochs_reducer:
                    carried_reductions = await anyio.to_thread.run_sync(
                        _read_carried_reductions, carried_zip
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
                    return await reader.read_member_fully(read.members[key])
                assert carried_zip is not None
                return await anyio.to_thread.run_sync(
                    carried_zip.read, _sample_filename(key.sample_id, key.epoch)
                )

            name = log_basename(merged_path)
            total = selected_total(selection, held_ids) * epochs
            with tempfile.TemporaryFile(dir=temp_dir) as out:
                header = await write_merged_zip(
                    out,
                    keys=keys,
                    read_member=read_member,
                    summaries=summaries,
                    template=base,
                    total_samples=total,
                    held_reductions=_held_reductions(
                        reads,
                        carried,
                        carried_reductions,
                        merged_path,
                        functools.partial(
                            _unfinished_ids, fs, shards, reads, ledger, carried
                        ),
                    ),
                    make_header=lambda scoring: build_header(
                        base=base,
                        merged=existing.header if existing is not None else None,
                        name=name,
                        status=status,
                        ledger=entries,
                        selection=selection,
                        summaries=summaries,
                        results=scoring.results,
                        invalidated=scoring.invalidated,
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
        status=status,
        check_retained=False,
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
    return _Pass(
        header, False, existing.etag, existing.records, 0, status, not shards_gone
    )


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


async def _read_attempts(
    fs: AsyncFilesystem, shards: list[ShardDir]
) -> tuple[list[AttemptRead], dict[str, AsyncZipReader]]:
    limiter = anyio.CapacityLimiter(_MAX_CONCURRENT_READS)

    async def read(shard: ShardDir) -> tuple[AttemptRead, AsyncZipReader]:
        async with limiter:
            return await _read_attempt(fs, shard)

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
    check_resolved(info.name, shard.name, header, len(held))
    reductions = None
    if (
        header.eval.config.epochs_reducer
        and header.status != "started"
        and not is_recovered_attempt(info)
        and REDUCTIONS_JSON in names
    ):
        reductions = _parse_reductions(await _read_member_json(reader, REDUCTIONS_JSON))
    read = AttemptRead(
        shard=shard.name,
        file=info,
        header=header,
        summaries=held,
        members=members,
        etag=reader.etag,
        reductions=reductions,
    )
    return read, reader


async def _check_merged_resolved(
    fs: AsyncFilesystem, shards: list[ShardDir], ledger: dict[str, EvalShardEntry]
) -> None:
    """Refuse deleting merged attempts that hold samples they did not resolve.

    `shards` are unchanged since the merge that recorded them in `ledger`.
    That merge read them and refused such an attempt (see `check_resolved`);
    a pass that deletes them without reading them checks their headers again.
    """
    limiter = anyio.CapacityLimiter(_MAX_CONCURRENT_READS)

    async def check(shard: ShardDir) -> None:
        async with limiter:
            header = await _read_attempt_header(fs, shard)
        check_resolved(
            _current(shard).name, shard.name, header, ledger[shard.name].samples
        )

    await tg_collect([functools.partial(check, s) for s in shards])


async def _read_attempt_header(fs: AsyncFilesystem, shard: ShardDir) -> EvalLog:
    info = _current(shard)
    reader = AsyncZipReader(fs, info.name, verify_crc=True)
    cd = await reader.entries()
    return await _read_header_async(reader, {e.filename for e in cd.entries}, info.name)


def _read_carried_reductions(
    carried_zip: zipfile.ZipFile,
) -> list[EvalSampleReductions]:
    if REDUCTIONS_JSON not in carried_zip.namelist():
        return []
    return _parse_reductions(json.loads(carried_zip.read(REDUCTIONS_JSON)))


def _parse_reductions(data: list[Any]) -> list[EvalSampleReductions]:
    return [
        EvalSampleReductions.model_validate(
            reduction, context=get_deserializing_context()
        )
        for reduction in data
    ]


def _held_reductions(
    reads: list[AttemptRead],
    carried: set[SampleRecordKey],
    carried_reductions: list[EvalSampleReductions],
    merged_path: str,
    unfinished: Callable[[], Awaitable[set[str]]],
) -> HeldReductions:
    """The recorded reductions of the held samples, each from its own log.

    A changed shard's samples take theirs from its current attempt, carried
    samples from the merged log, which holds what their (unchanged) shard
    recorded when it was merged.
    """
    sources = {key.sample_id: merged_path for key in carried}
    samples: dict[tuple[str, str | None], list[EvalSampleScore]] = {}

    def add(reductions: list[EvalSampleReductions], ids: set[str]) -> None:
        for reduction in reductions:
            samples.setdefault((reduction.scorer, reduction.reducer), []).extend(
                s for s in reduction.samples if str(s.sample_id) in ids
            )

    for read in reads:
        ids = {key.sample_id for key in read.summaries}
        source = read.file.name
        if is_recovered_attempt(read.file):
            source += (
                " (a recovered log, whose reductions recovery recomputes from "
                "the reducers' names)"
            )
        sources.update(dict.fromkeys(ids, source))
        add(read.reductions or [], ids)
    add(carried_reductions, {key.sample_id for key in carried})
    return HeldReductions(
        reductions=[
            EvalSampleReductions(scorer=scorer, reducer=reducer, samples=held)
            for (scorer, reducer), held in samples.items()
        ],
        sources=sources,
        unfinished=unfinished,
    )


async def _unfinished_ids(
    fs: AsyncFilesystem,
    shards: list[ShardDir],
    reads: list[AttemptRead],
    ledger: dict[str, EvalShardEntry],
    carried: set[SampleRecordKey],
) -> set[str]:
    """The held sample ids whose shard's current attempt is still running.

    A read attempt's status is in its header. An unchanged shard's is in its
    ledger entry; the sample ids it selects are read from its header only
    when that status is `started`.
    """
    ids = {
        key.sample_id
        for read in reads
        if read.header.status == "started"
        for key in read.summaries
    }
    read_shards = {read.shard for read in reads}
    running = [
        shard
        for shard in shards
        if shard.name not in read_shards and ledger[shard.name].status == "started"
    ]
    limiter = anyio.CapacityLimiter(_MAX_CONCURRENT_READS)

    async def selected(shard: ShardDir) -> set[str]:
        async with limiter:
            header = await _read_attempt_header(fs, shard)
        return {str(id) for id in header.eval.dataset.sample_ids or []}

    carried_ids = {key.sample_id for key in carried}
    for selection in await tg_collect(
        [functools.partial(selected, s) for s in running]
    ):
        ids |= selection & carried_ids
    return ids


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

    When this pass wrote nothing and shard attempts remain, a merged log
    with epoch reducers recorded is also checked for edited scores and
    missing reductions, which the writing passes refuse (see
    `_recompute_results` in `_write.py`).

    Raises:
        ShardSetError: The merged log is not the one this call planned, holds
            an edited score or lacks a required reduction.
        LookupError: A metric is not registered.
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
    if merge_pass.check_retained and header.eval.config.epochs_reducer:
        await _check_retained(reader, cd, header, merged_path)


async def _check_retained(
    reader: AsyncZipReader, cd: CentralDirectory, header: EvalLog, merged_path: str
) -> None:
    """Refuse deleting shards whose reductions the merged log does not keep.

    Refuses an edited score (see `edited_score_message`) and a missing
    required reduction (see `check_retained_reductions`). Summaries do not
    keep score edit histories, so every sample member is read.
    """
    score_ids: dict[str, set[str]] = {}
    for entry in cd.entries:
        key = parse_sample_member(entry.filename)
        if key is None:
            continue
        sample = json.loads(await reader.read_member_fully(entry))
        for name, score in sorted((sample.get("scores") or {}).items()):
            if score.get("history"):
                raise ShardSetError(
                    edited_score_message(name, key.sample_id, merged_path)
                    + " Its shards were not deleted."
                )
            score_ids.setdefault(name, set()).add(key.sample_id)
    names = {e.filename for e in cd.entries}
    reductions = (
        _parse_reductions(await _read_member_json(reader, REDUCTIONS_JSON))
        if REDUCTIONS_JSON in names
        else []
    )
    check_retained_reductions(header, score_ids, reductions, merged_path)
