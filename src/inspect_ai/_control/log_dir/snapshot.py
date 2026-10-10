"""Logical tasks, task rows and sample listings from a log directory.

The walk's ``.eval`` files are grouped into logical tasks (every attempt of a
``task_id``, the newest current), whose rows carry every key of a live
``/tasks`` row plus the additive log-dir keys. A ``<name>.shards/`` shard set
is one attempt whose members are the current file of each shard; an ordinary
retry sharing its task id is current over it. A running member's shared
buffer (``--log-shared``) supplies its running and completed-but-unflushed
samples. See "Logical tasks", "Reading a member consistently", "Task rows"
and "Sample rows" in ``design/ctl/log-dir-mode.md``.
"""

from __future__ import annotations

import functools
import time
from dataclasses import dataclass, field, replace
from typing import Any, Literal, NamedTuple

import anyio
from botocore.exceptions import BotoCoreError, ClientError

from inspect_ai._control.state import (
    SAMPLE_STATUSES,
    _iso_to_timestamp,
    _pending_summary,
    _sorted_samples,
    _summary_from_eval_sample_summary,
)
from inspect_ai._util._async import tg_collect
from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.constants import get_deserializing_context
from inspect_ai._util.file import local_path
from inspect_ai.log._file import _try_parse_filename
from inspect_ai.log._log import EvalLog, EvalSampleSummary
from inspect_ai.log._recorders.eval import (
    HEADER_JSON,
    START_JSON,
    LogStart,
    _journal_path,
    _read_all_summaries_async,
    _read_member_json,
)
from inspect_ai.log._shards._walk import AttemptSortKey, StrayFile

from .buffer import read_manifest
from .consistency import (
    LogChangedError,
    LogUnparseableError,
    log_version,
    read_consistently,
    read_version,
)
from .select import (
    LogPlan,
    MemberSnapshot,
    SampleKey,
    authoritative_total,
    known_keys,
    member_candidate,
    select_source,
    totals,
)
from .walk import (
    LogDirListing,
    LogFile,
    ShardSetFiles,
    attempt_order,
    basename,
    walk_log_dir,
)

# Reads in flight at once, the CLI's fan-out cap.
_MAX_CONCURRENT_READS = 32

# Storage failures a list read reports per member rather than failing the
# whole read (a vanished object is a FileNotFoundError, an OSError).
READ_FAILURES = (
    LogChangedError,
    LogUnparseableError,
    OSError,
    ClientError,
    BotoCoreError,
)

_JSON_LOG_REASON = "the .json log format is not read in --log-dir mode"


class UnsupportedLogFormatError(Exception):
    """A ``.json`` log, which this mode does not read."""


class StrayLogError(Exception):
    """A log in a shard set that is not a shard attempt, which this mode does not read."""


@dataclass(frozen=True)
class Unreadable:
    """A log a read could not use, and why."""

    location: str
    reason: str
    error: BaseException = field(compare=False, repr=False)
    """The failure, re-raised by a single-target read of this log."""

    def as_dict(self) -> dict[str, str]:
        return {"log_location": local_path(self.location), "reason": self.reason}


@dataclass(frozen=True)
class Member:
    """A current member log of a logical task: its plan, or why it is unreadable."""

    file: LogFile
    plan: LogPlan | None
    """``None`` when the plan could not be read (``failure`` says why)."""

    failure: Unreadable | None = None

    attempts: int = 1
    """The attempt files in its shard directory (1 for an unsharded log)."""


@dataclass
class ShardSet:
    """A ``<name>.shards/`` companion: one attempt of a logical task.

    Its members are the current (newest) file of each ``<k>/``; older files
    are superseded and only counted. The merged log beside the companion
    gives the row its ``eval_id`` and ``log_location``; sample state comes
    from the shards.
    """

    location: str
    """The companion directory."""

    path: str
    """The companion's path relative to the root."""

    shards: list[Member]
    """One member per shard directory, in shard order."""

    merged_file: LogFile | None = None
    """The newest merged log (``<name>.eval`` or ``<name>-recovered.eval``)."""

    merged: LogPlan | None = None
    """The merged log's plan, when it could be read."""

    unreadable: list[Unreadable] = field(default_factory=list)
    """The merged log's failure and the companion's stray logs."""

    @property
    def log_target(self) -> str:
        return f"shards:{self.path}"

    @property
    def identity(self) -> LogPlan | None:
        """The plan the row's identity comes from: the first readable shard's."""
        return next((m.plan for m in self.shards if m.plan is not None), None)


@dataclass
class LogicalTask:
    """Every attempt of one task in the directory; the newest is current.

    An unsharded attempt is current over a shard set with the same task id
    (an ``eval_set()`` retry seeded from the merged log), whatever the
    mtimes.
    """

    key: str
    """The task id (the eval id for a log that records none)."""

    attempts: list[LogPlan]
    """Readable unsharded attempts in attempt order, oldest first."""

    shard_sets: list[ShardSet] = field(default_factory=list)
    """Shard sets with this task id, oldest first (almost always one)."""

    unreadable: list[Unreadable] = field(default_factory=list)
    """Unsharded attempts (by file name) whose plan could not be read."""

    newest_unreadable: Unreadable | None = None
    """The newest unreadable unsharded attempt when it would be current, so
    the current attempt may not be the task's newest."""

    @property
    def current(self) -> LogPlan:
        """The current unsharded attempt (only when ``attempts`` is non-empty)."""
        return self.attempts[-1]

    @property
    def shard_set(self) -> ShardSet | None:
        """The newest shard set: current when there is no unsharded attempt."""
        return self.shard_sets[-1] if self.shard_sets else None

    @property
    def sharded(self) -> bool:
        """Whether the current attempt is a shard set."""
        return not self.attempts

    @property
    def members(self) -> list[Member]:
        """The current attempt's member logs."""
        if self.attempts:
            return [Member(self.current.file, self.current)]
        assert self.shard_set is not None
        return self.shard_set.shards

    @property
    def identity(self) -> LogPlan | None:
        """The plan the row's identity fields come from."""
        if self.attempts:
            return self.current
        assert self.shard_set is not None
        return self.shard_set.identity or self.shard_set.merged

    @property
    def location(self) -> str:
        """Where the current attempt is: its log, or the shard set's merged log or companion."""
        if self.attempts:
            return self.current.file.location
        assert self.shard_set is not None
        if self.shard_set.merged_file is not None:
            return self.shard_set.merged_file.location
        return self.shard_set.location

    @property
    def log_target(self) -> str:
        """The task's identifier within the root, which sample reads route by."""
        if self.shard_set is not None:
            return self.shard_set.log_target
        return f"log:{self.key}"


@dataclass
class LogDirIndex:
    """One invocation's walk and plans (identity only; no summaries)."""

    root: str
    as_of: float
    """Stamped before the walk, so a later poll catches anything missed."""

    tasks: list[LogicalTask]
    unattributed: list[Unreadable]
    """Unreadable logs that no readable task's file names claim."""

    unreadable_tasks: list[UnreadableTask] = field(default_factory=list)
    """Tasks known only from the file names of unreadable logs."""

    def task(self, log_target: str) -> LogicalTask | None:
        return next((t for t in self.tasks if t.log_target == log_target), None)

    def unreadable_task(self, log_target: str) -> UnreadableTask | None:
        return next(
            (t for t in self.unreadable_tasks if t.log_target == log_target), None
        )

    @property
    def unidentified(self) -> list[Unreadable]:
        """Unattributed unreadable logs whose file names name no task."""
        named = {id(u) for t in self.unreadable_tasks for u in t.failures}
        return [u for u in self.unattributed if id(u) not in named]


@dataclass
class UnreadableTask:
    """A task whose every log is unreadable, identified by its file names.

    Kept selectable so a read targeting it reports the failure rather than
    ``not_found``.
    """

    task_id: str
    task: str
    failures: list[Unreadable]
    """Its logs, in file-name order (the timestamp prefix leads)."""

    @property
    def log_target(self) -> str:
        return f"unreadable:{self.task_id}"

    @property
    def newest(self) -> Unreadable:
        return self.failures[-1]


async def index_log_dir(fs: AsyncFilesystem, root: str) -> LogDirIndex:
    """Walk ``root`` and read every current log's plan, folding attempts."""
    as_of = time.time()
    listing = await walk_log_dir(fs, root)
    return await _index_listing(fs, root, as_of, listing)


async def _index_listing(
    fs: AsyncFilesystem, root: str, as_of: float, listing: LogDirListing
) -> LogDirIndex:
    limiter = anyio.CapacityLimiter(_MAX_CONCURRENT_READS)

    async def plan_or_failure(file: LogFile) -> LogPlan | Unreadable:
        try:
            async with limiter:
                return await read_plan(fs, file)
        except READ_FAILURES as ex:
            return Unreadable(file.location, _reason(ex), ex)

    # a superseded shard attempt is only counted, so only current files are read
    files = [
        *listing.eval_files,
        *(shard.attempts[-1] for s in listing.shard_sets for shard in s.shards),
        *(s.merged[-1] for s in listing.shard_sets if s.merged),
    ]
    results = dict(
        zip(
            (f.location for f in files),
            await tg_collect([functools.partial(plan_or_failure, f) for f in files]),
        )
    )

    by_key: dict[str, list[LogPlan]] = {}
    failures: list[tuple[LogFile | None, Unreadable]] = [
        (
            None,
            Unreadable(
                path,
                _JSON_LOG_REASON,
                UnsupportedLogFormatError(f"{local_path(path)}: {_JSON_LOG_REASON}"),
            ),
        )
        for path in listing.json_logs
    ]
    for file in listing.eval_files:
        result = results[file.location]
        if isinstance(result, Unreadable):
            failures.append((file, result))
        else:
            spec = result.header.eval
            by_key.setdefault(spec.task_id or spec.eval_id, []).append(result)

    tasks = {
        key: LogicalTask(key=key, attempts=sorted(plans, key=_plan_order))
        for key, plans in by_key.items()
    }
    shard_sets = sorted(
        (_shard_set(files, results) for files in listing.shard_sets),
        key=lambda s: (attempt_order(_dir_file(s.location)), s.location),
    )
    for shard_set in shard_sets:
        key = _set_key(shard_set.location)
        tasks.setdefault(key, LogicalTask(key=key, attempts=[])).shard_sets.append(
            shard_set
        )

    unattributed: list[Unreadable] = [_stray(s) for s in listing.stray]
    newest: dict[str, tuple[AttemptSortKey, Unreadable]] = {}
    unreadable_tasks: dict[str, UnreadableTask] = {}
    for failed_file, failure in failures:
        name, task_id = _file_identity(failure.location)
        task = tasks.get(task_id or "")
        if task is None:
            unattributed.append(failure)
            if task_id:
                unreadable_tasks.setdefault(
                    task_id, UnreadableTask(task_id, name or "", [])
                ).failures.append(failure)
            continue
        task.unreadable.append(failure)
        if failed_file is None:
            continue
        order = attempt_order(failed_file)
        # an unsharded attempt is current over a shard set whatever its order
        newer = not task.attempts or order > _plan_order(task.current)
        if newer and (task.key not in newest or order > newest[task.key][0]):
            newest[task.key] = (order, failure)
    for key, (_, failure) in newest.items():
        tasks[key].newest_unreadable = failure
    ordered = sorted(tasks.values(), key=lambda t: (_created(t), t.key))
    for unreadable_task in unreadable_tasks.values():
        unreadable_task.failures.sort(key=lambda u: basename(u.location))
    return LogDirIndex(
        root=root,
        as_of=as_of,
        tasks=ordered,
        unattributed=unattributed,
        unreadable_tasks=sorted(unreadable_tasks.values(), key=lambda t: t.task_id),
    )


def _shard_set(
    files: ShardSetFiles, results: dict[str, LogPlan | Unreadable]
) -> ShardSet:
    """A shard set from its walk and the plans of its current files."""
    shards: list[Member] = []
    for shard in files.shards:
        current = shard.attempts[-1]
        result = results[current.location]
        shards.append(
            Member(current, None, result, len(shard.attempts))
            if isinstance(result, Unreadable)
            else Member(current, result, None, len(shard.attempts))
        )
    shard_set = ShardSet(
        location=files.location,
        path=files.path,
        shards=shards,
        unreadable=[_stray(s) for s in files.stray],
    )
    if files.merged:
        shard_set.merged_file = files.merged[-1]
        merged = results[shard_set.merged_file.location]
        if isinstance(merged, Unreadable):
            shard_set.unreadable.insert(0, merged)
        else:
            shard_set.merged = merged
    return shard_set


def _stray(stray: StrayFile) -> Unreadable:
    """A stray log in a shard set, reported as unreadable with the walk's reason."""
    return Unreadable(
        stray.path,
        stray.reason,
        StrayLogError(f"{local_path(stray.path)} is not read: {stray.reason}"),
    )


def _set_key(companion: str) -> str:
    """A shard set's task id: ``{id}`` parsed from ``<name>``, else ``<name>``."""
    _, task_id = _file_identity(companion)
    return task_id or basename(companion).rsplit(".", 1)[0]


def _dir_file(location: str) -> LogFile:
    """A directory as a :class:`LogFile`, to order it by its name's timestamp."""
    return LogFile(
        location=location, name=basename(location), size=0, mtime=None, etag=None
    )


def _created(task: LogicalTask) -> str:
    plan = task.identity
    return plan.header.eval.created if plan is not None else ""


async def read_plan(fs: AsyncFilesystem, file: LogFile) -> LogPlan:
    """Read one log's central directory and header (or journal start record)."""

    async def read(reader: AsyncZipReader, fresh: bool) -> LogPlan:
        return await _plan_from(fs, reader, file)

    return await read_consistently(fs, file.location, read)


async def _plan_from(
    fs: AsyncFilesystem,
    reader: AsyncZipReader,
    file: LogFile,
    prior: LogPlan | None = None,
) -> LogPlan:
    """Read the plan through ``reader``'s (fresh) central directory.

    A ``prior`` plan of the same log that is still running supplies the
    header while the log has no ``header.json``: ``_journal/start.json`` is
    written once, at the start, so it is not read again.
    """
    cd, version = await read_version(fs, file.location, reader.entries)
    if cd.entry(HEADER_JSON) is None and prior is not None and not prior.finished:
        return replace(prior, central_directory=cd, version=version)
    if cd.entry(HEADER_JSON) is not None:
        header = EvalLog.model_validate(
            await _read_member_json(reader, HEADER_JSON),
            context=get_deserializing_context(),
        )
        finished = True
    elif cd.entry(_journal_path(START_JSON)) is not None:
        start = LogStart.model_validate(
            await _read_member_json(reader, _journal_path(START_JSON)),
            context=get_deserializing_context(),
        )
        header = EvalLog(version=start.version, eval=start.eval, plan=start.plan)
        finished = False
    else:
        raise LogUnparseableError(
            file.location,
            f"it has neither {HEADER_JSON} nor {_journal_path(START_JSON)}",
        )
    header.location = file.location
    return LogPlan(
        file=file,
        central_directory=cd,
        header=header,
        finished=finished,
        version=version,
    )


async def read_snapshot(
    fs: AsyncFilesystem, plan: LogPlan, *, fresh: bool = False
) -> MemberSnapshot:
    """Read a member's sample summaries through the central directory its plan used.

    With ``fresh``, or on a re-read after a torn read, the central directory
    is read again, and so is ``header.json`` when the log now has one: it may
    have finished in between.
    """

    async def read(reader: AsyncZipReader, fresh: bool) -> MemberSnapshot:
        current = await _plan_from(fs, reader, plan.file, plan) if fresh else plan
        return MemberSnapshot(
            plan=current, summaries=await read_summaries(reader, plan.file)
        )

    return await read_consistently(
        fs,
        plan.file.location,
        read,
        central_directory=None if fresh else plan.central_directory,
    )


async def read_member(fs: AsyncFilesystem, plan: LogPlan) -> MemberSnapshot:
    """Read a member's view: its manifest (when it may have one), then its log.

    The worker writes a sample to the log before dropping it from the
    manifest, so a log observed after the manifest holds every key the
    manifest no longer lists. For a running member with a shared buffer the
    manifest is read first, then the log's current version is checked with
    one metadata request: the plan's central directory is reused only when
    it came from that version, and is re-read otherwise. A key the worker had
    admitted when the manifest was read is therefore reported from the
    manifest, the log, or both, never as pending or missing.

    Members that cannot have a shared buffer have no second object to order
    against and are read through the plan's central directory as before.
    """
    if not plan.shared_buffer:
        return await read_snapshot(fs, plan)
    buffer = await read_manifest(fs, plan.file)
    version = await log_version(fs, plan.file.location)
    fresh = version is None or version != plan.version
    return replace(await read_snapshot(fs, plan, fresh=fresh), buffer=buffer)


async def read_summaries(
    reader: AsyncZipReader, file: LogFile
) -> dict[SampleKey, EvalSampleSummary]:
    """A log's sample summaries by key (last row wins), through ``reader``.

    Raises :class:`LogUnparseableError` for a log whose journal is missing a
    summary member (``2.json`` without ``1.json``): journal members are
    append-only, so a central directory without one is malformed, not torn.
    """
    try:
        summaries, _ = await _read_all_summaries_async(reader)
    except KeyError as ex:
        raise LogUnparseableError(
            file.location, f"its journal is missing member {ex}"
        ) from ex
    return {SampleKey(str(s.id), s.epoch): s for s in summaries}


class MemberRead(NamedTuple):
    """One member's view, or why it could not be read."""

    member: Member
    snapshot: MemberSnapshot | None
    failure: Unreadable | None

    @property
    def plan(self) -> LogPlan | None:
        """The member's latest plan: from its view, else from the index."""
        return self.snapshot.plan if self.snapshot is not None else self.member.plan


class TaskView(NamedTuple):
    """A logical task with its current members read (see :func:`read_task_views`)."""

    task: LogicalTask
    reads: list[MemberRead]
    """The current members' reads, in member order."""

    shard_reads: list[MemberRead] | None = None
    """With ``shards``, the reads of the newest shard set's shards (the
    current members' reads when it is current)."""

    @property
    def members(self) -> list[MemberSnapshot]:
        """The current members that could be read."""
        return [r.snapshot for r in self.reads if r.snapshot is not None]

    @property
    def unreadable(self) -> list[Unreadable]:
        """Every log of the task not read, the current members' failures included."""
        task = self.task
        failures = [
            *task.unreadable,
            *(u for s in task.shard_sets for u in s.unreadable),
            *(m.failure for s in task.shard_sets for m in s.shards if m.failure),
            *(r.failure for r in self.reads if r.failure),
        ]
        unique: dict[str, Unreadable] = {}
        for failure in failures:
            unique.setdefault(failure.location, failure)
        return list(unique.values())


async def read_members(
    fs: AsyncFilesystem,
    members: list[Member],
    limiter: anyio.CapacityLimiter | None = None,
) -> list[MemberRead]:
    """Read each member's view, recording a failure rather than raising."""
    limiter = limiter or anyio.CapacityLimiter(_MAX_CONCURRENT_READS)

    async def read(member: Member) -> MemberRead:
        if member.plan is None:
            return MemberRead(member, None, member.failure)
        try:
            async with limiter:
                return MemberRead(member, await read_member(fs, member.plan), None)
        except READ_FAILURES as ex:
            failure = Unreadable(member.file.location, _reason(ex), ex)
            return MemberRead(member, None, failure)

    return await tg_collect([functools.partial(read, m) for m in members])


async def read_task_views(
    fs: AsyncFilesystem, tasks: list[LogicalTask], *, shards: bool = False
) -> list[TaskView]:
    """Read each task's current members, and with ``shards`` its shard set's.

    A shard set that is a prior attempt (an ordinary retry is current) is
    read only with ``shards``: its samples are not the task's.
    """
    limiter = anyio.CapacityLimiter(_MAX_CONCURRENT_READS)

    async def view(task: LogicalTask) -> TaskView:
        reads = await read_members(fs, task.members, limiter)
        shard_reads: list[MemberRead] | None = None
        if shards and task.shard_set is not None:
            shard_reads = (
                reads
                if task.sharded
                else await read_members(fs, task.shard_set.shards, limiter)
            )
        return TaskView(task, reads, shard_reads)

    return await tg_collect([functools.partial(view, t) for t in tasks])


async def read_current_members(
    fs: AsyncFilesystem, task: LogicalTask
) -> list[MemberSnapshot]:
    """Read every current member's view, raising the first member's failure.

    A per-sample read uses this: a key cannot be located, or reported
    missing, while any member that may hold it is unread.
    """
    reads = await read_members(fs, task.members)
    failure = next((r.failure for r in reads if r.failure is not None), None)
    if failure is not None:
        raise failure.error
    return [r.snapshot for r in reads if r.snapshot is not None]


def identity_row(task: LogicalTask) -> dict[str, Any]:
    """The identity fields of a task row, from its plans alone.

    What selector resolution (``_resolve_target_eval``) and the ambiguity
    table read, without the summaries a full row needs. A shard set's
    ``task``, ``model``, ``solver`` and ``epochs`` come from its first
    readable shard, its ``eval_id`` and ``run_id`` from the merged log (null
    without one), and its ``log_location`` is the merged log or, without
    one, the companion.
    """
    plans = [m.plan for m in task.members]
    if task.sharded:
        shard_set = task.shard_set
        assert shard_set is not None
        merged = shard_set.merged.header.eval if shard_set.merged else None
        identity = _plan_identity(task.identity, shard_set.location)
        identity.update(
            run_id=merged.run_id if merged else None,
            eval_id=merged.eval_id if merged else None,
            task_id=task.key,
        )
    else:
        identity = _plan_identity(task.current, task.current.file.location)
    return {
        **identity,
        "log_location": local_path(task.location),
        "status": "running" if _running(plans) else "completed",
        "attempts": len(task.attempts) + len(task.unreadable) + len(task.shard_sets),
        "pid": None,
        "socket_path": None,
        "source": "log_dir",
        "log_target": task.log_target,
        "current_attempt": "shards" if task.sharded else "log",
        "shard": None,
    }


def unreadable_identity_row(task: UnreadableTask) -> dict[str, Any]:
    """The resolution row for a task known only from unreadable file names.

    Carries only the fields its file names give; a read that selects it fails
    with the newest log's failure.
    """
    return {
        "run_id": None,
        "eval_id": None,
        "task": task.task,
        "task_id": task.task_id,
        "model": None,
        "solver": "",
        "log_location": local_path(task.newest.location),
        "status": None,
        "attempts": len(task.failures),
        "epochs": None,
        "pid": None,
        "socket_path": None,
        "source": "log_dir",
        "log_target": task.log_target,
        "current_attempt": "log",
        "shard": None,
        "incomplete": True,
        "unreadable": [u.as_dict() for u in task.failures],
    }


def task_row(view: TaskView) -> dict[str, Any]:
    """A full log-dir task row: every live row key plus the additive keys."""
    task = view.task
    progress = _progress(view.reads, authoritative=_authoritative(view))
    shards = None
    if task.shard_set is not None:
        shards = _shards_block(
            task.shard_set,
            view.reads if task.sharded else None,
            overlapping=progress.overlapping if task.sharded else None,
        )
    return {
        **identity_row(task),
        **progress.fields,
        "shards": shards,
        "incomplete": bool(view.unreadable),
        "unreadable": [u.as_dict() for u in view.unreadable],
    }


def shard_rows(view: TaskView) -> list[dict[str, Any]]:
    """One row per shard of the task's newest shard set (``task list --shards``).

    Each describes its shard's current file as an eval of its own, with the
    shard's own ``task_id``, ``shard`` naming its directory and ``attempts``
    the files in it. Shards are not separately selectable: ``log_target`` is
    the logical task's.
    """
    rows: list[dict[str, Any]] = []
    for read in view.shard_reads or []:
        member = read.member
        plan = read.snapshot.plan if read.snapshot is not None else None
        progress = _progress(
            [read], authoritative=authoritative_total(plan) if plan else None
        )
        rows.append(
            {
                **_plan_identity(read.plan, member.file.location),
                "log_location": local_path(member.file.location),
                "attempts": member.attempts,
                "pid": None,
                "socket_path": None,
                "source": "log_dir",
                "log_target": view.task.log_target,
                "current_attempt": "log",
                "shard": member.file.shard,
                **progress.fields,
                "shards": None,
                "incomplete": read.failure is not None,
                "unreadable": [read.failure.as_dict()] if read.failure else [],
            }
        )
    return rows


def _plan_identity(plan: LogPlan | None, location: str) -> dict[str, Any]:
    """Identity fields from a plan, or from the file name when there is none."""
    if plan is None:
        name, task_id = _file_identity(location)
        return {
            "run_id": None,
            "eval_id": None,
            "task": name,
            "task_id": task_id,
            "model": None,
            "solver": "",
            "epochs": None,
        }
    spec = plan.header.eval
    return {
        "run_id": spec.run_id,
        "eval_id": spec.eval_id,
        "task": spec.task,
        "task_id": spec.task_id,
        "model": spec.model,
        "solver": spec.solver or "",
        "epochs": spec.config.epochs or 1,
    }


def _authoritative(view: TaskView) -> int | None:
    """The task's authoritative sample total: a finished unsharded current log's.

    A shard set has none until the merged log records its intended
    selection.
    """
    if view.task.sharded or not view.members:
        return None
    return authoritative_total(view.members[0].plan)


class _Progress(NamedTuple):
    fields: dict[str, Any]
    """The row's status, timing, sample and usage fields."""

    overlapping: int
    """Members holding a key another member also holds."""


def _progress(reads: list[MemberRead], *, authoritative: int | None) -> _Progress:
    """Status, timing, sample counts and usage over the members' selected records."""
    members = [r.snapshot for r in reads if r.snapshot is not None]
    plans = [r.plan for r in reads]
    known = [p for p in plans if p is not None]
    keys = known_keys(members)
    counts = {"completed": 0, "error": 0, "cancelled": 0, "running": 0}
    conflicted = 0
    overlapping: set[str] = set()
    total_tokens = 0
    total_messages = 0
    sample_starts: list[float] = []
    for key in keys:
        choice = select_source(members, key)
        if choice.kind == "conflict":
            conflicted += 1
            overlapping.update(m.plan.file.location for m in choice.holders)
            continue
        if choice.summary is None:
            continue
        summary = choice.summary
        status = _summary_from_eval_sample_summary(summary)["status"]
        if status in counts:
            counts[status] += 1
        total_tokens += sum(u.total_tokens for u in summary.model_usage.values())
        total_messages += summary.message_count or 0
        started = _iso_to_timestamp(summary.started_at)
        if started is not None:
            sample_starts.append(started)
    sample_totals = totals(authoritative, len(keys))
    running = _running(plans)
    live = [m.live_samples for m in members if m.live_samples is not None]
    # a member that could not be read and may be running has unknown running samples
    live.extend(
        False
        for r in reads
        if r.snapshot is None and (r.plan is None or r.plan.running)
    )
    started_at = min(sample_starts, default=None)
    if started_at is None:
        started_at = min(
            (
                t
                for t in (_iso_to_timestamp(p.header.eval.created) for p in known)
                if t is not None
            ),
            default=None,
        )
    completed_at = (
        None
        if running
        else max(
            (
                t
                for t in (
                    _iso_to_timestamp(p.header.stats.completed_at or None)
                    for p in known
                )
                if t is not None
            ),
            default=None,
        )
    )
    elapsed = (completed_at or time.time()) - (started_at or 0.0)
    tokens_per_second = (
        round(total_tokens / elapsed, 1)
        if started_at is not None and elapsed > 0
        else None
    )
    terminal = counts["completed"] + counts["error"] + counts["cancelled"]
    fields: dict[str, Any] = {
        "status": "running" if running else "completed",
        "started_at": started_at,
        "completed_at": completed_at,
        "paused": None,
        "paused_now": None,
        "quiesced": None,
        "held": None,
        "resolving": None,
        "samples": {
            "total": sample_totals.total,
            "completed": counts["completed"],
            "errored": counts["error"],
            "cancelled": counts["cancelled"],
            # running samples are visible only in shared sample buffers
            "in_flight": counts["running"] if all(live) else None,
            "queued": None,
            "conflicted": conflicted,
            "unfinished": sample_totals.total - terminal - conflicted,
            "total_final": sample_totals.total_final,
            "pending_unlisted": sample_totals.pending_unlisted,
        },
        "total_tokens": total_tokens,
        "tokens_per_second": tokens_per_second,
        "total_messages": total_messages,
        "refusals": None,
        "http_retries": None,
        "keep_alive": None,
        "process_paused": None,
        "process_paused_now": None,
        "paused_models": [],
        "api_version": None,
        "updated_at": _updated_at([r.member.file for r in reads], members),
        "live_samples": _live_samples(live),
    }
    return _Progress(fields=fields, overlapping=len(overlapping))


def _shards_block(
    shard_set: ShardSet, reads: list[MemberRead] | None, *, overlapping: int | None
) -> dict[str, Any]:
    """The ``shards`` block: shard counts by log status, overlaps and mismatches.

    ``reads`` are the shards' reads when the shard set is current; a prior
    shard set is described from its plans, and its ``overlapping`` is null
    (its samples are not read). A shard whose task, model or epochs differ
    from the first readable shard's is counted in ``mismatched``.
    """
    plans = (
        [r.plan for r in reads]
        if reads is not None
        else [m.plan for m in shard_set.shards]
    )
    known = [p for p in plans if p is not None]
    statuses = [p.header.status for p in known]
    identities = [
        (p.header.eval.task, p.header.eval.model, p.header.eval.config.epochs or 1)
        for p in known
    ]
    return {
        "total": len(shard_set.shards),
        "running": statuses.count("started"),
        "success": statuses.count("success"),
        "error": statuses.count("error"),
        "cancelled": statuses.count("cancelled"),
        "overlapping": overlapping,
        "mismatched": sum(1 for i in identities[1:] if i != identities[0]),
    }


def _running(plans: list[LogPlan | None]) -> bool:
    """Whether any member is running; one whose plan is unknown may be."""
    return any(p is None or p.running for p in plans)


class SampleListing(NamedTuple):
    """One task's samples listing (the live envelope plus the log-dir keys)."""

    counts: dict[str, int]
    samples: list[dict[str, Any]]
    truncated: bool
    conflicted: int


def sample_listing(
    view: TaskView,
    *,
    statuses: frozenset[str] | None = None,
    limit: int | None = None,
    sample_filter: Literal["errors"] | None = None,
    content: bool = False,
) -> SampleListing:
    """One row per key from its selected source, with the live filters and cap.

    As live: ``counts`` covers every sample (restricted by ``sample_filter``,
    which also skips pending rows), before the status filter and cap;
    ``content`` gates the error and limit reason. Pending samples an
    authoritative total counts but no record names add to ``counts.pending``
    without rows. A conflicted key yields one row per member holding it, and
    is left out of ``counts``.
    """
    members = view.members
    keys = known_keys(members)
    rows: list[dict[str, Any]] = []
    conflicted = 0
    for key in keys:
        choice = select_source(members, key)
        if choice.kind == "conflict":
            conflicted += 1
            for holder in choice.holders:
                candidate = member_candidate(holder, key.key)
                assert candidate is not None
                rows.append(_sample_row(candidate.summary, holder, conflict=True))
        elif choice.kind in ("log", "buffer"):
            assert choice.summary is not None and choice.member is not None
            rows.append(_sample_row(choice.summary, choice.member))
        elif sample_filter != "errors":
            rows.append(
                {
                    **_pending_summary(key.sample_id, key.key.epoch),
                    "shard": None,
                    "log_location": None,
                    "conflict": False,
                }
            )
    if sample_filter == "errors":
        rows = [r for r in rows if r["error"] is not None or (r["retries"] or 0) > 0]

    counts = dict.fromkeys(SAMPLE_STATUSES, 0)
    for row in rows:
        if not row["conflict"]:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
    if sample_filter != "errors":
        pending_unlisted = totals(_authoritative(view), len(keys)).pending_unlisted
        counts["pending"] += pending_unlisted or 0

    rows = _sorted_samples(rows)
    if statuses is not None:
        rows = [r for r in rows if r["status"] in statuses]
    if not content:
        rows = [
            {**r, "error": None, "limit_reason": None}
            if r.get("error") is not None or r.get("limit_reason") is not None
            else r
            for r in rows
        ]
    truncated = limit is not None and len(rows) > limit
    if truncated:
        rows = rows[:limit]
    return SampleListing(
        counts=counts, samples=rows, truncated=truncated, conflicted=conflicted
    )


def _updated_at(files: list[LogFile], members: list[MemberSnapshot]) -> float | None:
    """The latest of the members' listed log mtimes and their manifests' Last-Modified.

    Every member's listing counts, readable or not: a log just written that
    does not parse is still a sign its worker is alive.
    """
    times = [f.mtime for f in files] + [
        m.buffer.mtime for m in members if m.buffer is not None
    ]
    return max((t for t in times if t is not None), default=None)


def _live_samples(live: list[bool]) -> Literal["buffer", "none", "partial"]:
    """Whether running samples are visible: every, no or some running member has a manifest.

    ``buffer`` when no member is running: there are no running samples to
    miss, and ``in_flight`` is 0.
    """
    if all(live):
        return "buffer"
    return "none" if not any(live) else "partial"


def _sample_row(
    summary: Any, member: MemberSnapshot, *, conflict: bool = False
) -> dict[str, Any]:
    return {
        **_summary_from_eval_sample_summary(summary),
        "shard": member.plan.file.shard,
        "log_location": local_path(member.plan.file.location),
        "conflict": conflict,
    }


def _plan_order(plan: LogPlan) -> AttemptSortKey:
    return attempt_order(plan.file)


def _file_identity(location: str) -> tuple[str | None, str | None]:
    """The task name and id in a log's file name (``{created}_{task}_{id}``)."""
    stem = basename(location).rsplit(".", 1)[0]
    task, task_id, _ = _try_parse_filename(stem.split("_"))
    return task, task_id or None


def _reason(ex: BaseException) -> str:
    if isinstance(ex, FileNotFoundError):
        return "the log was removed during the read"
    return str(ex) or type(ex).__name__
