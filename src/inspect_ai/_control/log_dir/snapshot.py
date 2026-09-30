"""Logical tasks, task rows and sample listings from a log directory.

The walk's ``.eval`` files are grouped into logical tasks (every attempt of a
``task_id``, the newest current), whose rows carry every key of a live
``/tasks`` row plus the additive log-dir keys. See "Logical tasks", "Task
rows" and "Sample rows" in ``design/ctl/log-dir-mode.md``.
"""

from __future__ import annotations

import functools
import time
from dataclasses import dataclass, field
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
from inspect_ai.log._file import _timestamp_prefix_re, _try_parse_filename
from inspect_ai.log._log import EvalLog, EvalSampleSummary
from inspect_ai.log._recorders.eval import (
    HEADER_JSON,
    START_JSON,
    LogStart,
    _journal_path,
    _read_all_summaries_async,
    _read_member_json,
)

from .consistency import LogChangedError, LogUnparseableError, read_consistently
from .select import (
    LogPlan,
    MemberSnapshot,
    SampleKey,
    authoritative_total,
    known_keys,
    select_source,
    totals,
)
from .walk import LogDirListing, LogFile, basename, walk_log_dir

# Reads in flight at once, the CLI's fan-out cap.
_MAX_CONCURRENT_READS = 32

_RECOVERED_SUFFIX = "-recovered"

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


@dataclass(frozen=True)
class Unreadable:
    """A log a read could not use, and why."""

    location: str
    reason: str
    error: BaseException = field(compare=False, repr=False)
    """The failure, re-raised by a single-target read of this log."""

    def as_dict(self) -> dict[str, str]:
        return {"log_location": local_path(self.location), "reason": self.reason}


@dataclass
class LogicalTask:
    """Every attempt of one task in the directory; the newest is current."""

    key: str
    """The task id (the eval id for a log that records none)."""

    attempts: list[LogPlan]
    """Readable attempts in attempt order, oldest first."""

    unreadable: list[Unreadable] = field(default_factory=list)
    """Attempts (by file name) whose plan could not be read."""

    newest_unreadable: Unreadable | None = None
    """The newest unreadable attempt when it sorts after the current one, so
    the current attempt may not be the task's newest."""

    @property
    def current(self) -> LogPlan:
        return self.attempts[-1]

    @property
    def log_target(self) -> str:
        """The task's identifier within the root, which sample reads route by."""
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
    """Walk ``root`` and read every ``.eval`` file's plan, folding attempts."""
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

    results = await tg_collect(
        [functools.partial(plan_or_failure, f) for f in listing.eval_files]
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
    for file, result in zip(listing.eval_files, results):
        if isinstance(result, Unreadable):
            failures.append((file, result))
        else:
            spec = result.header.eval
            by_key.setdefault(spec.task_id or spec.eval_id, []).append(result)

    tasks = {
        key: LogicalTask(key=key, attempts=sorted(plans, key=_plan_order))
        for key, plans in by_key.items()
    }
    unattributed: list[Unreadable] = []
    newest: dict[str, tuple[tuple[str, int, float], Unreadable]] = {}
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
        order = _attempt_order(failed_file)
        if order > _plan_order(task.current) and (
            task.key not in newest or order > newest[task.key][0]
        ):
            newest[task.key] = (order, failure)
    for key, (_, failure) in newest.items():
        tasks[key].newest_unreadable = failure
    ordered = sorted(
        tasks.values(), key=lambda t: (t.current.header.eval.created, t.key)
    )
    for unreadable_task in unreadable_tasks.values():
        unreadable_task.failures.sort(key=lambda u: basename(u.location))
    return LogDirIndex(
        root=root,
        as_of=as_of,
        tasks=ordered,
        unattributed=unattributed,
        unreadable_tasks=sorted(unreadable_tasks.values(), key=lambda t: t.task_id),
    )


async def read_plan(fs: AsyncFilesystem, file: LogFile) -> LogPlan:
    """Read one log's central directory and header (or journal start record)."""

    async def read(reader: AsyncZipReader, fresh: bool) -> LogPlan:
        return await _plan_from(reader, file)

    return await read_consistently(fs, file.location, read)


async def _plan_from(reader: AsyncZipReader, file: LogFile) -> LogPlan:
    cd = await reader.entries()
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
    return LogPlan(file=file, central_directory=cd, header=header, finished=finished)


async def read_snapshot(fs: AsyncFilesystem, plan: LogPlan) -> MemberSnapshot:
    """Read a member's sample summaries through the central directory its plan used.

    A re-read (after a torn read) takes a fresh central directory and so also
    re-reads the header: the log may have finished in between.
    """

    async def read(reader: AsyncZipReader, fresh: bool) -> MemberSnapshot:
        current = await _plan_from(reader, plan.file) if fresh else plan
        return MemberSnapshot(
            plan=current, summaries=await read_summaries(reader, plan.file)
        )

    return await read_consistently(
        fs, plan.file.location, read, central_directory=plan.central_directory
    )


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


class TaskView(NamedTuple):
    """A logical task with its current member read (see :func:`read_task_view`)."""

    task: LogicalTask
    member: MemberSnapshot | None
    """``None`` when the member could not be read."""

    unreadable: list[Unreadable]
    """The task's unreadable attempts plus the member's own failure, if any."""


async def read_task_view(fs: AsyncFilesystem, task: LogicalTask) -> TaskView:
    """Read the current attempt's summaries, recording a failure rather than raising."""
    try:
        member = await read_snapshot(fs, task.current)
    except READ_FAILURES as ex:
        failure = Unreadable(task.current.file.location, _reason(ex), ex)
        return TaskView(task, None, [*task.unreadable, failure])
    return TaskView(task, member, list(task.unreadable))


async def read_task_views(
    fs: AsyncFilesystem, tasks: list[LogicalTask]
) -> list[TaskView]:
    limiter = anyio.CapacityLimiter(_MAX_CONCURRENT_READS)

    async def read(task: LogicalTask) -> TaskView:
        async with limiter:
            return await read_task_view(fs, task)

    return await tg_collect([functools.partial(read, t) for t in tasks])


def identity_row(task: LogicalTask) -> dict[str, Any]:
    """The identity fields of a task row, from its plan alone.

    What selector resolution (``_resolve_target_eval``) and the ambiguity
    table read, without the summaries a full row needs.
    """
    plan = task.current
    spec = plan.header.eval
    return {
        "run_id": spec.run_id,
        "eval_id": spec.eval_id,
        "task": spec.task,
        "task_id": spec.task_id,
        "model": spec.model,
        "solver": spec.solver or "",
        "log_location": local_path(plan.file.location),
        "status": _task_status(plan),
        "attempts": len(task.attempts) + len(task.unreadable),
        "epochs": spec.config.epochs or 1,
        "pid": None,
        "socket_path": None,
        "source": "log_dir",
        "log_target": task.log_target,
        "current_attempt": "log",
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
        "incomplete": True,
        "unreadable": [u.as_dict() for u in task.failures],
    }


def task_row(view: TaskView) -> dict[str, Any]:
    """A full log-dir task row: every live row key plus the additive keys."""
    task, member = view.task, view.member
    plan = member.plan if member is not None else task.current
    spec = plan.header.eval
    members = [member] if member is not None else []
    keys = known_keys(members)
    counts = {"completed": 0, "error": 0, "cancelled": 0}
    conflicted = 0
    total_tokens = 0
    total_messages = 0
    sample_starts: list[float] = []
    for key in keys:
        choice = select_source(members, key)
        if choice.kind == "conflict":
            conflicted += 1
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
    sample_totals = totals(
        authoritative_total(plan) if member is not None else None, len(keys)
    )
    running = _task_status(plan) == "running"
    started_at = min(sample_starts, default=None)
    if started_at is None:
        started_at = _iso_to_timestamp(spec.created)
    completed_at = (
        None if running else _iso_to_timestamp(plan.header.stats.completed_at or None)
    )
    elapsed = (completed_at or time.time()) - (started_at or 0.0)
    tokens_per_second = (
        round(total_tokens / elapsed, 1)
        if started_at is not None and elapsed > 0
        else None
    )
    terminal = counts["completed"] + counts["error"] + counts["cancelled"]
    return {
        **identity_row(task),
        "log_location": local_path(plan.file.location),
        "status": _task_status(plan),
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
            # running samples are visible only in shared sample buffers,
            # which this mode does not read yet
            "in_flight": None if running else 0,
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
        "updated_at": plan.file.mtime,
        "incomplete": bool(view.unreadable),
        "unreadable": [u.as_dict() for u in view.unreadable],
    }


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
    members = [view.member] if view.member is not None else []
    keys = known_keys(members)
    rows: list[dict[str, Any]] = []
    conflicted = 0
    for key in keys:
        choice = select_source(members, key)
        if choice.kind == "conflict":
            conflicted += 1
            for holder in choice.holders:
                rows.append(
                    _sample_row(holder.summaries[key.key], holder, conflict=True)
                )
        elif choice.kind == "log":
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
    if sample_filter != "errors" and members:
        plan = members[0].plan
        pending_unlisted = totals(authoritative_total(plan), len(keys)).pending_unlisted
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


def _sample_row(
    summary: Any, member: MemberSnapshot, *, conflict: bool = False
) -> dict[str, Any]:
    return {
        **_summary_from_eval_sample_summary(summary),
        "shard": None,
        "log_location": local_path(member.plan.file.location),
        "conflict": conflict,
    }


def _task_status(plan: LogPlan) -> str:
    """Live's two task statuses: ``running`` while the log is ``started``."""
    return "running" if plan.header.status == "started" else "completed"


def _attempt_order(file: LogFile) -> tuple[str, int, float]:
    """Attempt order: file-name timestamp, then ``-recovered`` after its original, then mtime.

    Recovery keeps the original's timestamp prefix and writes the original's
    records plus its buffer, so the recovered copy is the more complete. Names
    with no timestamp prefix sort by mtime alone (before timestamped ones):
    without the shared prefix, a ``-recovered`` name says nothing about which
    copy is newer.
    """
    match = _timestamp_prefix_re.match(file.name)
    if match is None:
        return ("", 0, file.mtime or 0.0)
    stem = file.name.rsplit(".", 1)[0]
    return (
        match.group(0),
        1 if stem.endswith(_RECOVERED_SUFFIX) else 0,
        file.mtime or 0.0,
    )


def _plan_order(plan: LogPlan) -> tuple[str, int, float]:
    return _attempt_order(plan.file)


def _file_identity(location: str) -> tuple[str | None, str | None]:
    """The task name and id in a log's file name (``{created}_{task}_{id}``)."""
    stem = basename(location).rsplit(".", 1)[0]
    task, task_id, _ = _try_parse_filename(stem.split("_"))
    return task, task_id or None


def _reason(ex: BaseException) -> str:
    if isinstance(ex, FileNotFoundError):
        return "the log was removed during the read"
    return str(ex) or type(ex).__name__
