"""Per-sample reads: show, events, messages, store.

Each read locates the key through :func:`~.select.select_source` over the
current member's freshly read view (manifest, then log; so it never answers
from a stale key set). A log record is read from the sample member with the
field exclusions the live terminal path uses, verified against the central
directory's CRC-32, and built into the same envelope through the shared
projection code. A shared-buffer row (running, or completed but not yet
flushed) serves ``show`` from its manifest summary and ``events`` from its
segments; ``messages`` and ``store`` are not in the buffer. See "Per-sample
reads" in ``design/ctl/log-dir-mode.md``.
"""

from __future__ import annotations

import time
from collections.abc import Collection
from typing import Any, Literal, NamedTuple

from inspect_ai._control.events import (
    DEFAULT_PAGE_LIMIT,
    EventsSource,
    _attempt_nonce,
    events_source_from_sample,
    page_events,
)
from inspect_ai._control.messages import (
    LOGGED_MESSAGES_EXCLUDE_FIELDS,
    messages_source_from_sample,
    page_messages,
)
from inspect_ai._control.state import (
    SAMPLE_DETAIL_EXCLUDE_FIELDS,
    _summary_from_eval_sample_summary,
    terminal_sample_detail,
)
from inspect_ai._control.store import (
    LOGGED_STORE_EXCLUDE_FIELDS,
    page_store,
    store_source_from_sample,
)
from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.file import local_path
from inspect_ai.log._file import read_eval_log_sample_async
from inspect_ai.log._log import EvalSample, EvalSampleSummary

from .buffer import buffered_events, read_sample_data
from .consistency import MAX_REREADS, LogChangedError, read_consistently
from .select import MemberSnapshot, SampleKey, known_keys, select_source
from .snapshot import LogicalTask, read_member, read_summaries


class SampleNotFoundError(Exception):
    """The sample has no record in the task's current attempt."""


class SampleAmbiguousError(Exception):
    """More than one member log holds a record for the sample."""


class SampleUnsupportedError(Exception):
    """The read is not available for a sample whose record is a shared-buffer row."""

    def __init__(self, task_id: str, summary: EvalSampleSummary, *, read: str) -> None:
        state = (
            "has completed but is not yet in the log (retry after the next "
            "flush, up to about 60 s)"
            if summary.completed
            else "is still running"
        )
        super().__init__(
            f"Sample '{summary.id}' (epoch {summary.epoch}) {state}; its {read} "
            "is not in the shared buffer."
        )
        self.task_id = task_id
        self.sample_id = str(summary.id)
        self.epoch = summary.epoch


class _Located(NamedTuple):
    member: MemberSnapshot
    summary: EvalSampleSummary
    kind: Literal["log", "buffer"]


async def sample_detail(
    fs: AsyncFilesystem,
    task: LogicalTask,
    sample_id: str,
    epoch: int,
    *,
    content: bool = False,
) -> dict[str, Any]:
    """The ``sample show`` envelope, as the live terminal path builds it.

    A buffer row's envelope is its manifest summary: no ``error_retries``
    until the sample is flushed.
    """
    located = await _locate(fs, task, sample_id, epoch)
    if located.kind == "buffer":
        return _buffer_detail(located.summary, content=content)
    read = await _read_sample(fs, located, SAMPLE_DETAIL_EXCLUDE_FIELDS)
    return terminal_sample_detail(
        read.sample,
        _summary_from_eval_sample_summary(read.summary)
        if read.summary is not None
        else None,
        will_retry=False,
        content=content,
    )


async def sample_events(
    fs: AsyncFilesystem,
    task: LogicalTask,
    sample_id: str,
    epoch: int,
    *,
    since: str | None = None,
    tail: int | None = None,
    types: frozenset[str] | None = None,
    content: bool = False,
    full: bool = False,
    since_time: float | None = None,
    until: float | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> dict[str, Any]:
    """A ``sample events`` page over the sample's full event list.

    A log record's events are the sample member's. A buffer row's are
    reconstructed from every segment the manifest lists for it, up to the
    last sync, under a ``buffer:`` cursor nonce that also names the attempt's
    start, so a cursor carried over to the flushed record or to another
    attempt restarts at 0 (duplicates, never gaps). The page is ``done`` only
    for a completed row.
    """
    return page_events(
        await _events_source(fs, task, sample_id, epoch),
        since=since,
        tail=tail,
        types=types,
        content=content,
        full=full,
        since_time=since_time,
        until=until,
        limit=limit,
    )


async def sample_messages(
    fs: AsyncFilesystem,
    task: LogicalTask,
    sample_id: str,
    epoch: int,
    *,
    tail: int | None = None,
    content: bool = False,
    full: bool = False,
) -> dict[str, Any]:
    """The ``sample messages`` snapshot of the logged sample.

    Raises :class:`SampleUnsupportedError` for a buffer row: the buffer has
    no message list.
    """
    as_of = time.time()
    located = await _locate(fs, task, sample_id, epoch)
    if located.kind == "buffer":
        raise SampleUnsupportedError(task.key, located.summary, read="message list")
    sample = (await _read_sample(fs, located, LOGGED_MESSAGES_EXCLUDE_FIELDS)).sample
    return page_messages(
        messages_source_from_sample(sample),
        tail=tail,
        content=content,
        full=full,
        as_of=as_of,
    )


async def sample_store(
    fs: AsyncFilesystem,
    task: LogicalTask,
    sample_id: str,
    epoch: int,
    *,
    keys: list[str] | None = None,
    content: bool = False,
    full: bool = False,
) -> dict[str, Any]:
    """The ``sample store`` snapshot of the logged sample.

    Raises :class:`SampleUnsupportedError` for a buffer row: the buffer has
    no store snapshot.
    """
    as_of = time.time()
    located = await _locate(fs, task, sample_id, epoch)
    if located.kind == "buffer":
        raise SampleUnsupportedError(task.key, located.summary, read="store")
    sample = (await _read_sample(fs, located, LOGGED_STORE_EXCLUDE_FIELDS)).sample
    return page_store(
        store_source_from_sample(sample),
        keys=keys,
        content=content,
        full=full,
        as_of=as_of,
    )


async def _locate(
    fs: AsyncFilesystem, task: LogicalTask, sample_id: str, epoch: int
) -> _Located:
    """Find the key's current record after making the member's key set current.

    Reads the member's manifest (when it may have one) and then its log, as a
    list read does. Refuses to answer from an older attempt while a newer one
    is unreadable (re-raising that attempt's failure).
    """
    if task.newest_unreadable is not None:
        raise task.newest_unreadable.error
    member = await read_member(fs, task.current)
    location = local_path(member.plan.file.location)
    key = SampleKey(sample_id, epoch)
    known = next((k for k in known_keys([member]) if k.key == key), None)
    if known is None:
        raise SampleNotFoundError(
            f"Sample '{sample_id}' (epoch {epoch}) not found in {location}."
        )
    choice = select_source([member], known)
    if choice.kind == "conflict":
        logs = ", ".join(local_path(m.plan.file.location) for m in choice.holders)
        raise SampleAmbiguousError(
            f"Sample '{sample_id}' (epoch {epoch}) has records in several logs: "
            f"{logs} — read them with `inspect log` commands."
        )
    if choice.summary is None or choice.member is None or choice.kind == "pending":
        why = (
            "it has not started, or it is running without a shared buffer (run "
            "the eval with --log-shared to see running samples)"
            if member.live_samples is False
            else "it has not started"
        )
        raise SampleNotFoundError(
            f"Sample '{sample_id}' (epoch {epoch}) is not in {location} yet — {why}."
        )
    return _Located(choice.member, choice.summary, choice.kind)


async def _events_source(
    fs: AsyncFilesystem, task: LogicalTask, sample_id: str, epoch: int
) -> EventsSource:
    """The located record's events, re-selecting when buffer objects disappear.

    A finishing worker deletes its buffer after the final flush, so a segment
    that is gone mid-read sends the read back to source selection (manifest,
    then log), up to :data:`~.consistency.MAX_REREADS` times; a sample flushed
    in between is then served from the log.

    Raises:
        LogChangedError: segments kept disappearing after the re-reads.
    """
    missing: FileNotFoundError | None = None
    for _ in range(MAX_REREADS + 1):
        located = await _locate(fs, task, sample_id, epoch)
        if located.kind == "log":
            sample = (await _read_sample(fs, located, None)).sample
            return events_source_from_sample(sample, epoch)
        try:
            return await _buffer_events_source(fs, located)
        except FileNotFoundError as ex:
            missing = ex
    assert missing is not None
    raise LogChangedError(
        str(missing.filename or "the shared buffer"),
        "a segment its manifest lists was removed",
    ) from missing


async def _buffer_events_source(fs: AsyncFilesystem, located: _Located) -> EventsSource:
    buffer = located.member.buffer
    assert buffer is not None
    summary = located.summary
    row = buffer.samples[SampleKey(str(summary.id), summary.epoch)]
    events = buffered_events(await read_sample_data(fs, buffer, row), buffer, row)

    def fetch(start: int, limit: int) -> list[Any]:
        return events[start : start + limit]

    # a `retry_on_error` attempt keeps the uuid and its running summary
    # records no retry count, so the attempt's start time tells it apart
    nonce = _attempt_nonce(
        summary.uuid, summary.id, summary.epoch, summary.retries or 0
    )
    return EventsSource(
        nonce=f"buffer:{nonce}:{summary.started_at}",
        fetch=fetch,
        total=len(events),
        done=bool(summary.completed),
    )


def _buffer_detail(summary: EvalSampleSummary, *, content: bool) -> dict[str, Any]:
    """The ``sample show`` envelope of a buffer row, from its manifest summary.

    ``content`` gates the error message and limit reason, as for a logged
    sample; the summary records no traceback.
    """
    row = _summary_from_eval_sample_summary(summary)
    error = row["error"]
    return {
        **row,
        "error": (
            None
            if error is None
            else {"message": error, "traceback": None, "traceback_ansi": None}
            if content
            else {}
        ),
        "error_retries": [],
        "limit_reason": row["limit_reason"] if content else None,
    }


class _SampleRead(NamedTuple):
    sample: EvalSample
    summary: EvalSampleSummary | None
    """The sample's summary from the same log version as ``sample`` (``None``
    when that version has no summary row for it)."""


async def _read_sample(
    fs: AsyncFilesystem,
    located: _Located,
    exclude_fields: Collection[str] | None,
) -> _SampleRead:
    """Read the located sample member, re-reading on a torn read.

    A re-read goes through a fresh central directory, so the log may have
    been replaced since the summaries were read: the summary is then re-read
    from that version too, so the two never describe different records.
    """
    location = located.member.plan.file.location
    key = SampleKey(str(located.summary.id), located.summary.epoch)

    async def read(reader: AsyncZipReader, fresh: bool) -> _SampleRead:
        summary: EvalSampleSummary | None = located.summary
        if fresh:
            summary = (await read_summaries(reader, located.member.plan.file)).get(key)
        sample = await read_eval_log_sample_async(
            location,
            located.summary.id,
            located.summary.epoch,
            exclude_fields=set(exclude_fields) if exclude_fields else None,
            reader=reader,
        )
        return _SampleRead(sample, summary)

    return await read_consistently(
        fs,
        location,
        read,
        central_directory=located.member.plan.central_directory,
    )
