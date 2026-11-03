"""Merge the shard logs of a sharded run into one eval log."""

import functools
import json
import tempfile
import zipfile
from collections.abc import Sequence
from contextvars import copy_context
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NamedTuple

import anyio

from inspect_ai._util._async import run_coroutine, tg_collect
from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.file import FileInfo, basename, to_uri
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

from ._errors import ShardSetError, ShardSetIncomplete
from ._owned import run_owned
from ._plan import (
    AttemptRead,
    Selection,
    Status,
    build_header,
    check_attempt_names,
    check_attempt_order,
    check_current_unambiguous,
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
    plan_status,
    recorded_selection,
    selected_total,
)
from ._publish import (
    merge_guard,
    merged_log_copy,
    publish,
    supported_location,
)
from ._walk import ShardDir, check_s3_location, list_shard_set
from ._write import check_task_matches, write_merged_zip

if TYPE_CHECKING:
    from inspect_ai._eval.task.task import Task

_MAX_CONCURRENT_READS = 16


@dataclass(frozen=True)
class ShardMergeResult:
    """Result of :func:`merge_eval_log_shards`."""

    log: EvalLog
    """Header of the merged log (samples not loaded); `log.location` is its path."""

    written: bool
    """False when nothing had changed since the last merge and nothing was written."""


def merge_eval_log_shards(
    log: str,
    task: "Task | str",
    *,
    sample_ids: Sequence[str | int] | None = None,
    sample_count: int | None = None,
    allow_incomplete: bool = False,
) -> ShardMergeResult:
    """Merge the shard logs of a sharded run into one eval log.

    The shards of the log `<dir>/<name>.eval` are the `.eval` files in
    `<dir>/<name>.shards/<k>/`, one directory per worker. The current attempt
    of each shard is the newest file in its directory. The merged log holds
    exactly the samples each current attempt holds, and records which
    attempts it holds (`eval.shards`), so a later call reads only the shards
    that changed and writes nothing when none did.

    Shards must be one task run: the same task, arguments, model, scorers,
    metrics, dataset size, epochs and log format, each started with its own
    `sample_id` or `limit` selection. Shard selections must not overlap and
    must not change between attempts in one shard directory.

    The merged log's results and epoch reductions are computed over all its
    samples with `task`: its scorers, metrics and epoch reducer, as a native
    run computes them. Pass the task the shards ran. The merge refuses a task
    whose name, scorer names, metric names, epochs or epoch reducer names
    differ from what the shards recorded, but does not compare options.

    The merge does not delete the shards. Once you have checked the merged
    log, delete `<dir>/<name>.shards/` yourself. Deleting one shard directory
    by hand makes later merges refuse until the rest of the shards directory
    is deleted or the files are restored; deleting the whole shards directory
    leaves the merged log as it is. Header edits to the merged log (tags,
    metadata) are kept by later merges.

    The merged log and its shards must be local or on S3. A local merged log
    is guarded by a lock file beside it and an S3 one by a conditional
    upload, so a merge that overlaps another is refused.

    A merge that runs while a worker is writing its shard can fail with a
    read error (for example a CRC or JSON error). Nothing is written; run
    the merge again, or merge after the workers have exited.

    Args:
        log: The merged log `<dir>/<name>.eval`, or its shards directory
            `<dir>/<name>.shards`, as a local path, `file://` URI or `s3://`
            URL. Other storage is refused, as is a `<name>-recovered.eval`
            path.
        task: The task the shards ran, or a task spec as `eval()` takes it
            (`file.py@name`, `file.py` or a registered name), which is loaded
            with the task arguments, model and model roles the shards
            recorded.
        sample_ids: Intended selection as sample ids. Replaces the selection
            recorded in the merged log; once the shards are deleted, it must
            equal the recorded one.
        sample_count: Intended selection as a number of samples (exclusive
            with `sample_ids`). Without either, the recorded selection is
            used, and on a first merge the set is complete when the shards
            hold the whole dataset.
        allow_incomplete: Write a `started` or `error` merged log when the
            set is incomplete, rather than raise `ShardSetIncomplete`.

    Returns:
        The merged log's header, and whether it was written.

    Raises:
        ShardSetError: The shards cannot be merged (`ShardSelectionError`
            when they hold samples outside the selection), or `task` is not
            the task they ran.
        ShardSetIncomplete: The set is incomplete and `allow_incomplete` is
            not set. Nothing is written.
        WriteConflictError: Another merge holds the lock or published first.
            Run the merge again later.
        FileNotFoundError: Neither the merged log nor any shard exists.
        ValueError: Invalid arguments: `log` is not a local path, `file://`
            URI or `s3://` URL, or the `task` spec does not name one task.
    """
    return run_coroutine(
        merge_eval_log_shards_async(
            log,
            task,
            sample_ids=sample_ids,
            sample_count=sample_count,
            allow_incomplete=allow_incomplete,
        )
    )


async def merge_eval_log_shards_async(
    log: str,
    task: "Task | str",
    *,
    sample_ids: Sequence[str | int] | None = None,
    sample_count: int | None = None,
    allow_incomplete: bool = False,
) -> ShardMergeResult:
    """Merge the shard logs of a sharded run into one eval log.

    See :func:`merge_eval_log_shards`.
    """
    outcome = await merge_shards(
        log,
        task,
        sample_ids=sample_ids,
        sample_count=sample_count,
        allow_incomplete=allow_incomplete,
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
    new_samples: int
    status: Status


async def merge_shards(
    log: str,
    task: "Task | str",
    *,
    sample_ids: Sequence[str | int] | None = None,
    sample_count: int | None = None,
    allow_incomplete: bool = False,
) -> MergeOutcome:
    """Implement :func:`merge_eval_log_shards`, reporting what the CLI shows."""
    location, merged_path, shards_dir = merge_paths(log)
    given = given_selection(sample_ids, sample_count)
    check_s3_location(merged_path)
    check_s3_location(shards_dir)

    async with AsyncFilesystem() as fs:
        with merge_guard(merged_path):
            existing = await _read_merged(fs, merged_path)
            merge_pass = await _merge_pass(
                fs,
                merged_path,
                shards_dir,
                existing,
                given,
                task,
                allow_incomplete=allow_incomplete,
            )

    header = merge_pass.header
    header.location = location
    return MergeOutcome(
        result=ShardMergeResult(log=header, written=merge_pass.written),
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

    The location is checked and a ``file://`` URI decoded once by
    :func:`supported_location`; everything is derived and checked from that
    path, so an encoded name cannot pass a check its decoded form fails.

    Raises:
        ValueError: `log` is not in a supported form, or is named after a
            recovered log.
    """
    target = supported_location(log)
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
    shard_names = [entry.shard for entry in header.eval.shards.ledger]
    if len(set(shard_names)) != len(shard_names):
        raise ShardSetError(
            f"{merged_path} records a shard more than once in its ledger: it was "
            f"changed outside the merge. Delete {merged_path} so the next merge "
            "rebuilds it from the shards."
        )
    for entry in header.eval.shards.ledger:
        if "\\" in entry.log:
            raise ShardSetError(
                f"{merged_path} records the attempt {entry.log} for shard "
                f"{entry.shard}, a name with a backslash, which the merge never "
                f"records: it was changed outside the merge. Delete {merged_path} "
                "so the next merge rebuilds it from the shards."
            )
    return _Merged(header, merged_records(cd, merged_path), reader.etag)


async def _merge_pass(
    fs: AsyncFilesystem,
    merged_path: str,
    shards_dir: str,
    existing: _Merged | None,
    given: Selection | None,
    task: "Task | str",
    *,
    allow_incomplete: bool,
) -> _Pass:
    listing = await list_shard_set(fs, shards_dir, numeric_shards=True)
    check_attempt_names(listing.shards)
    check_current_unambiguous(listing.shards)
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
        _check_task(task, existing.header, merged_path)
        return _recorded_pass(existing, given, allow_incomplete)

    ledger = (
        {e.shard: e for e in _ledger(existing.header)} if existing is not None else {}
    )
    changed = [s for s in shards if not is_unchanged(ledger.get(s.name), _current(s))]
    for shard in changed:
        if shard.name in ledger:
            check_attempt_order(shard, ledger[shard.name])
    present = {s.name for s in shards}
    check_vanished(
        [name for name in ledger if name not in present], merged_path, shards_dir
    )

    reads, readers = await _read_attempts(fs, changed)
    by_shard = {read.shard: read for read in reads}
    template = shards[0]
    headers = [(read.file.name, read.header) for read in reads]
    if template.name in by_shard:
        base, base_source = (
            by_shard[template.name].header,
            by_shard[template.name].file.name,
        )
    else:
        assert existing is not None
        if _ledger(existing.header)[0].shard == template.name:
            base, base_source = existing.header, merged_path
        else:
            base = await _read_attempt_header(fs, template)
            base_source = _current(template).name
            headers.append((base_source, base))
    if existing is not None and len(changed) < len(shards):
        headers.append((merged_path, existing.header))
    check_headers(headers)
    resolved = _check_task(task, base, base_source)

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
        return _Pass(existing.header, False, 0, status)

    with tempfile.TemporaryDirectory() as temp_dir:
        carried_zip: zipfile.ZipFile | None = None
        try:
            carried_summaries: dict[SampleRecordKey, EvalSampleSummary] = {}
            if carried:
                assert existing is not None
                copy = await merged_log_copy(fs, merged_path, existing.etag, temp_dir)
                carried_zip = zipfile.ZipFile(copy)
                carried_summaries = await run_owned(
                    functools.partial(_read_carried_summaries, carried_zip, merged_path)
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
                return await run_owned(
                    functools.partial(
                        carried_zip.read, _sample_filename(key.sample_id, key.epoch)
                    )
                )

            name = log_basename(merged_path)
            total = selected_total(selection, held_ids) * epochs
            with tempfile.TemporaryFile(dir=temp_dir) as out:
                header = await write_merged_zip(
                    out,
                    keys=keys,
                    read_member=read_member,
                    summaries=summaries,
                    task=resolved,
                    total_samples=total,
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
                await publish(
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
        new_samples=len(set(keys) - records),
        status=status,
    )


def _check_task(task: "Task | str", header: EvalLog, source: str) -> "Task":
    """The task to compute results with, checked against what `source` recorded.

    A task spec is loaded as `eval()` loads it (see :func:`_load_task`); a
    `Task` is used as given.

    Raises:
        ShardSetError: The task differs from the one the shards ran.
        ValueError: The spec does not name exactly one task.
    """
    if isinstance(task, str):
        loaded = copy_context().run(_load_task, task, header)
        if len(loaded) != 1:
            raise ValueError(
                f"The task spec {task} names {len(loaded)} tasks; name one "
                "(for example file.py@name)."
            )
        task = loaded[0]
    check_task_matches(task, header, source)
    return task


def _load_task(spec: str, header: EvalLog) -> list["Task"]:
    """Load `spec` in the model context the shards ran with, as `eval()` does.

    The active model is built from the recorded model, generate config, base
    URL and model arguments, and the recorded model roles are installed, as
    offline scoring rebuilds them, so a task factory that calls `get_model()`
    builds the task the shards ran. Runs in a copy of the caller's context,
    which keeps its own active model and roles.
    """
    from inspect_ai._eval.loader import load_task_spec
    from inspect_ai.model import get_model
    from inspect_ai.model._model import init_active_model, init_model_roles
    from inspect_ai.model._model_config import model_roles_config_to_model_roles

    config = header.plan.config.merge(header.eval.model_generate_config)
    model = get_model(
        model=header.eval.model,
        config=config,
        base_url=header.eval.model_base_url,
        **header.eval.model_args,
    )
    init_model_roles(model_roles_config_to_model_roles(header.eval.model_roles) or {})
    init_active_model(model, config)
    return load_task_spec(spec, header.eval.task_args_passed)


def _recorded_pass(
    existing: _Merged, given: Selection | None, allow_incomplete: bool
) -> _Pass:
    """A pass that keeps the merged log as recorded (its shards deleted)."""
    header = existing.header
    recorded = recorded_selection(header)
    if given is not None and not given.same_as(recorded):
        raise ShardSetError(
            f"The shards of {header.location} were deleted; its selection can no "
            "longer change."
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
    return _Pass(header, False, 0, status)


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
    check_resolved(
        info.name, shard.name, header, len(held), (s.error for s in held.values())
    )
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
