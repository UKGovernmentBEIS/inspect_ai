"""``--log-dir``: read-only status from a log directory.

The mode state (the root stored by the ``--log-dir`` option's callback, see
``_group._log_dir_option``) and the CLI-side calls into the log-dir reader
(``inspect_ai._control.log_dir``). Only the commands carrying that option
serve the mode; every other command rejects ``--log-dir`` as a usage error.
See ``design/ctl/log-dir-mode.md``.
"""

from __future__ import annotations

import shlex
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, NoReturn, TypeVar

import click
from botocore.exceptions import BotoCoreError, ClientError

# Patch seam: tests monkeypatch functions on their defining module, so
# cross-module calls resolve through the module object at call time (see
# design/ctl/cli-refactor.md).
from . import _http
from ._failure import _CtlFailure, _exception_name, _fail
from ._render import _echo, _format_duration, _short_id

if TYPE_CHECKING:
    from inspect_ai._control.log_dir.snapshot import LogDirIndex, LogicalTask
    from inspect_ai._util.asyncfiles import AsyncFilesystem

_LOG_DIR_META_KEY = "inspect_ai.ctl.log_dir"
_INDEX_META_KEY = "inspect_ai.ctl.log_dir_index"
_BANNER_META_KEY = "inspect_ai.ctl.log_dir_banner"

# A running task whose current log has not changed for this long is flagged
# in the human table footer: a crashed worker leaves its log `started`, so a
# long-quiet log is the only sign one stopped.
_QUIET_SECONDS = 10 * 60

_T = TypeVar("_T")


def _log_dir_root() -> str | None:
    """The ``--log-dir`` root of the current invocation, or ``None`` (live mode)."""
    ctx = click.get_current_context(silent=True)
    if ctx is None:
        return None
    root = ctx.meta.get(_LOG_DIR_META_KEY)
    return root if isinstance(root, str) else None


def _set_log_dir_root(ctx: click.Context, log_dir: str) -> None:
    """Store the root for this invocation (``ctx.meta`` is shared with subcommands)."""
    if not log_dir.strip():
        raise click.BadParameter("must not be empty", param_hint="'--log-dir'")
    ctx.meta[_LOG_DIR_META_KEY] = log_dir.rstrip("/") or log_dir


def _announce_mode(as_json: bool) -> None:
    """Name the mode and its lag on stderr, once per invocation, for human output.

    Called by ``_envelope_failures`` before every runner; a no-op in live mode.
    """
    root = _log_dir_root()
    if root is None or as_json:
        return
    ctx = click.get_current_context()
    if ctx.meta.get(_BANNER_META_KEY):
        return
    ctx.meta[_BANNER_META_KEY] = True
    _echo(
        f"Reading logs in {root} (read-only, not live; completed samples "
        "normally reach the log within about 60 s; running samples are "
        "not shown).",
        err=True,
    )


def _refuse_active_since() -> NoReturn:
    _fail(
        "unsupported",
        "--active-since is not available with --log-dir: a sample that "
        "completes before one poll can reach the log only after the next, so "
        "a delta keyed on sample times would miss it. Poll the full listing "
        "instead.",
    )


# --- reads -------------------------------------------------------------------


def _run_reader(
    read: Callable[[AsyncFilesystem], Awaitable[_T]],
    *,
    walking: bool = False,
) -> _T:
    """Run one reader coroutine on a fresh filesystem, mapping its failures.

    ``walking`` marks a read that lists the root, where a missing object is
    the directory itself rather than a log removed during the read.
    """
    from inspect_ai._util.asyncfiles import AsyncFilesystem

    async def run() -> _T:
        async with AsyncFilesystem() as fs:
            return await read(fs)

    try:
        return _http._run_async(run)
    except _CtlFailure:
        raise
    except Exception as ex:
        _fail_from(ex, walking=walking)


def _fail_from(ex: BaseException, *, walking: bool) -> NoReturn:
    """Raise the envelope failure for a reader exception, or re-raise it."""
    from inspect_ai._control.log_dir.consistency import (
        LogChangedError,
        LogUnparseableError,
    )
    from inspect_ai._control.log_dir.samples import (
        SampleAmbiguousError,
        SampleNotFoundError,
    )
    from inspect_ai._control.log_dir.snapshot import UnsupportedLogFormatError

    root = _log_dir_root()
    kind: Literal[
        "not_found", "ambiguous", "unsupported", "storage_error", "invalid_response"
    ]
    status: int | None = None
    if isinstance(ex, SampleNotFoundError):
        kind, message = "not_found", str(ex)
    elif isinstance(ex, IndexError):
        kind, message = "not_found", f"{ex} (the log changed during the read)."
    elif isinstance(ex, SampleAmbiguousError):
        kind, message = "ambiguous", str(ex)
    elif isinstance(ex, UnsupportedLogFormatError):
        kind, message = "unsupported", str(ex)
    elif isinstance(ex, LogUnparseableError):
        kind, message = "invalid_response", f"{ex}."
    elif isinstance(ex, LogChangedError):
        kind, message = "storage_error", f"{ex}."
    elif isinstance(ex, (FileNotFoundError, NotADirectoryError)) and walking:
        kind, message = "not_found", f"Log directory {root} not found."
    elif isinstance(ex, FileNotFoundError):
        kind = "not_found"
        message = f"{ex.filename or 'A log'} was removed during the read."
    elif isinstance(ex, ClientError):
        code = str(ex.response.get("Error", {}).get("Code", ""))
        status = ex.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code == "NoSuchBucket":
            kind, message = "not_found", f"Log directory {root} not found ({code})."
        else:
            kind, message = "storage_error", f"Reading {root} failed: {ex}."
    elif isinstance(ex, (OSError, BotoCoreError)):
        kind, message = "storage_error", f"Reading {root} failed: {ex}."
    else:
        raise ex
    _echo(message, err=True)
    raise _CtlFailure(
        kind, message, exception=_exception_name(ex), status=status
    ) from ex


def _index() -> LogDirIndex:
    """The invocation's walk and plans, read once and shared by its later reads."""
    from inspect_ai._control.log_dir.snapshot import index_log_dir

    ctx = click.get_current_context()
    index = ctx.meta.get(_INDEX_META_KEY)
    if index is None:
        root = _log_dir_root()
        assert root is not None
        index = _run_reader(lambda fs: index_log_dir(fs, root), walking=True)
        ctx.meta[_INDEX_META_KEY] = index
        _warn_unreadable([u.as_dict() for u in index.unattributed])
    return index


def _identity_rows() -> list[dict[str, Any]]:
    """Task rows with identity fields only, for selector resolution.

    Reads the walk and each log's central directory and header — no sample
    summaries — like the live ``/tasks`` read the sample commands start with.
    Tasks known only from the file names of unreadable logs get a row too, so
    selecting one reports its failure rather than ``not_found``.
    """
    from inspect_ai._control.log_dir.snapshot import (
        identity_row,
        unreadable_identity_row,
    )

    index = _index()
    return [identity_row(task) for task in index.tasks] + [
        unreadable_identity_row(task) for task in index.unreadable_tasks
    ]


def _fail_if_only_unreadable() -> None:
    """Fail a single-target read when the directory has logs but none is readable.

    Live mode prints an empty result when nothing is running; here an
    empty-looking directory whose logs failed to read must say so, since the
    target may be in one of them. A no-op in live mode.
    """
    if _log_dir_root() is None:
        return
    unreadable = _index().unattributed
    if unreadable:
        _fail_from(unreadable[0].error, walking=False)


def _target_task(target: dict[str, Any]) -> LogicalTask:
    """The resolved row's logical task; a task with only unreadable logs fails.

    The failure is the task's newest log's own (``invalid_response`` for one
    that does not parse, ``storage_error`` for a storage failure).
    """
    index = _index()
    log_target = str(target.get("log_target"))
    unreadable = index.unreadable_task(log_target)
    if unreadable is not None:
        _fail_from(unreadable.newest.error, walking=False)
    task = index.task(log_target)
    if task is None:
        _fail(
            "not_found",
            f"Task '{target.get('task_id')}' is no longer in the log directory.",
        )
    return task


class _TaskRows(NamedTuple):
    """Result of :func:`_task_rows`."""

    rows: list[dict[str, Any]]
    unreadable: list[dict[str, str]]
    """Every log the rows do not cover (row-level entries included)."""


def _task_rows() -> _TaskRows:
    """Full task rows, one per logical task, for ``task list``."""
    from inspect_ai._control.log_dir.snapshot import read_task_views, task_row

    index = _index()
    views = _run_reader(lambda fs: read_task_views(fs, index.tasks))
    rows = [task_row(view) for view in views]
    unreadable = _merge_unreadable(
        [u.as_dict() for u in index.unattributed],
        *(row["unreadable"] for row in rows),
    )
    _warn_unreadable([u for row in rows for u in row["unreadable"]])
    return _TaskRows(rows=rows, unreadable=unreadable)


class _SamplesRead(NamedTuple):
    """One target's samples listing (see :func:`_read_samples`)."""

    target: dict[str, Any]
    """The target's full task row (the resolution row carried identity only)."""

    samples: list[dict[str, Any]]
    counts: dict[str, int]
    truncated: bool
    conflicted: int


class _SamplesReads(NamedTuple):
    as_of: float
    reads: list[_SamplesRead]
    unreadable: list[dict[str, str]]


def _read_samples(
    targets: list[dict[str, Any]],
    *,
    scoped: bool,
    sample_filter: Literal["errors"] | None,
    statuses: frozenset[str] | None,
    limit: int | None,
    content: bool,
) -> _SamplesReads:
    """Each target's samples listing, routed by its ``log_target``.

    Members that cannot be read contribute no rows and are reported in
    ``unreadable``, as does a target known only from unreadable logs. An
    unscoped read also reports every other unreadable log in the directory; a
    scoped one, those whose file names name no task (the target may be in
    one of them).
    """
    from inspect_ai._control.log_dir.snapshot import (
        read_task_views,
        sample_listing,
        task_row,
    )
    from inspect_ai._control.state import SAMPLE_STATUSES

    index = _index()
    readable = [t for t in targets if index.unreadable_task(t["log_target"]) is None]
    tasks = [_target_task(target) for target in readable]
    views = iter(_run_reader(lambda fs: read_task_views(fs, tasks)))
    reads: list[_SamplesRead] = []
    warn: list[dict[str, str]] = []
    for target in targets:
        if index.unreadable_task(target["log_target"]) is not None:
            reads.append(
                _SamplesRead(
                    target=target,
                    samples=[],
                    counts=dict.fromkeys(SAMPLE_STATUSES, 0),
                    truncated=False,
                    conflicted=0,
                )
            )
            continue
        view = next(views)
        row = task_row(view)
        warn.extend(row["unreadable"])
        listing = sample_listing(
            view,
            statuses=statuses,
            limit=limit,
            sample_filter=sample_filter,
            content=content,
        )
        reads.append(
            _SamplesRead(
                target=row,
                samples=listing.samples,
                counts=listing.counts,
                truncated=listing.truncated,
                conflicted=listing.conflicted,
            )
        )
    _warn_unreadable(warn)
    directory = index.unidentified if scoped else index.unattributed
    unreadable = _merge_unreadable(
        [u.as_dict() for u in directory],
        *(read.target["unreadable"] for read in reads),
    )
    return _SamplesReads(as_of=index.as_of, reads=reads, unreadable=unreadable)


def _sample_detail(
    target: dict[str, Any], sample_id: str, epoch: int, *, content: bool
) -> dict[str, Any]:
    from inspect_ai._control.log_dir.samples import sample_detail

    task = _target_task(target)
    return _run_reader(
        lambda fs: sample_detail(fs, task, sample_id, epoch, content=content)
    )


def _sample_events(
    target: dict[str, Any],
    sample_id: str,
    epoch: int,
    *,
    cursor: str | None,
    tail: int | None,
    limit: int | None,
    types: str | None,
    content: bool,
    full: bool,
    since_time: float | None,
    until: float | None,
) -> dict[str, Any]:
    from inspect_ai._control.events import DEFAULT_PAGE_LIMIT
    from inspect_ai._control.log_dir.samples import sample_events

    task = _target_task(target)
    # the same member parsing the events route applies to its `type` param
    type_set = (
        frozenset(t for t in (p.strip() for p in types.split(",")) if t)
        if types is not None
        else None
    )
    return _run_reader(
        lambda fs: sample_events(
            fs,
            task,
            sample_id,
            epoch,
            since=cursor,
            tail=tail,
            types=type_set,
            content=content,
            full=full,
            since_time=since_time,
            until=until,
            limit=limit if limit is not None else DEFAULT_PAGE_LIMIT,
        )
    )


def _sample_messages(
    target: dict[str, Any],
    sample_id: str,
    epoch: int,
    *,
    tail: int | None,
    content: bool,
    full: bool,
) -> dict[str, Any]:
    from inspect_ai._control.log_dir.samples import sample_messages

    task = _target_task(target)
    return _run_reader(
        lambda fs: sample_messages(
            fs, task, sample_id, epoch, tail=tail, content=content, full=full
        )
    )


def _sample_store(
    target: dict[str, Any],
    sample_id: str,
    epoch: int,
    *,
    keys: tuple[str, ...],
    content: bool,
    full: bool,
) -> dict[str, Any]:
    from inspect_ai._control.log_dir.samples import sample_store

    task = _target_task(target)
    return _run_reader(
        lambda fs: sample_store(
            fs,
            task,
            sample_id,
            epoch,
            keys=list(keys) or None,
            content=content,
            full=full,
        )
    )


# --- rendering ---------------------------------------------------------------


def _merge_unreadable(*lists: list[dict[str, str]]) -> list[dict[str, str]]:
    """Concatenate unreadable entries, keeping the first per log."""
    merged: dict[str, dict[str, str]] = {}
    for entries in lists:
        for entry in entries:
            merged.setdefault(entry["log_location"], entry)
    return list(merged.values())


def _warn_unreadable(entries: list[dict[str, str]]) -> None:
    for entry in entries:
        _echo(f"warning: skipped {entry['log_location']}: {entry['reason']}", err=True)


def _errors_command() -> str:
    """The ``sample errors`` command for this mode's directory, shell-quoted."""
    return f"inspect ctl sample errors --log-dir {shlex.quote(_log_dir_root() or '')}"


def _print_quiet_footer(rows: list[dict[str, Any]]) -> None:
    """Flag running tasks whose log has not changed for :data:`_QUIET_SECONDS`.

    Human output only: the JSON rows carry ``updated_at`` and leave the
    judgement to the caller.
    """
    now = datetime.now(timezone.utc).timestamp()
    quiet = [
        (row, now - float(row["updated_at"]))
        for row in rows
        if row.get("status") == "running"
        and row.get("updated_at") is not None
        and now - float(row["updated_at"]) >= _QUIET_SECONDS
    ]
    if not quiet:
        return
    _echo()
    for row, idle in quiet:
        _echo(
            f"{_short_id(str(row.get('task_id') or ''))}: running, but its log has "
            f"not changed for {_format_duration(idle)} — its eval process may have "
            "stopped."
        )
