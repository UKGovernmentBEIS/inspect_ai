"""Per-sample reads of log records: show, events, messages, store.

Each read locates the key through :func:`~.select.select_source` over the
current member's freshly read summaries (so it never answers from a stale key
set), reads the sample member with the field exclusions the live terminal
path uses, verified against the central directory's CRC-32, and builds the
same envelope through the shared projection code. See "Per-sample reads" in
``design/ctl/log-dir-mode.md``.
"""

from __future__ import annotations

import time
from collections.abc import Collection
from typing import Any, NamedTuple

from inspect_ai._control.events import (
    DEFAULT_PAGE_LIMIT,
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

from .consistency import read_consistently
from .select import MemberSnapshot, SampleKey, known_keys, select_source
from .snapshot import LogicalTask, read_snapshot, read_summaries


class SampleNotFoundError(Exception):
    """The sample has no log record in the task's current attempt."""


class SampleAmbiguousError(Exception):
    """More than one member log holds a record for the sample."""


class _Located(NamedTuple):
    member: MemberSnapshot
    summary: EvalSampleSummary


async def sample_detail(
    fs: AsyncFilesystem,
    task: LogicalTask,
    sample_id: str,
    epoch: int,
    *,
    content: bool = False,
) -> dict[str, Any]:
    """The ``sample show`` envelope, as the live terminal path builds it."""
    located = await _locate(fs, task, sample_id, epoch)
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
    """A ``sample events`` page over the logged sample's full event list."""
    located = await _locate(fs, task, sample_id, epoch)
    sample = (await _read_sample(fs, located, None)).sample
    return page_events(
        events_source_from_sample(sample, epoch),
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
    """The ``sample messages`` snapshot of the logged sample."""
    as_of = time.time()
    located = await _locate(fs, task, sample_id, epoch)
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
    """The ``sample store`` snapshot of the logged sample."""
    as_of = time.time()
    located = await _locate(fs, task, sample_id, epoch)
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
    """Find the key's current record after reading the current member's key set.

    Refuses to answer from an older attempt while a newer one is unreadable
    (re-raising that attempt's failure).
    """
    if task.newest_unreadable is not None:
        raise task.newest_unreadable.error
    member = await read_snapshot(fs, task.current)
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
    if choice.summary is None or choice.member is None:
        raise SampleNotFoundError(
            f"Sample '{sample_id}' (epoch {epoch}) is not in {location} yet — it "
            "has not started, or it is still running (running samples are not "
            "read with --log-dir)."
        )
    return _Located(choice.member, choice.summary)


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
