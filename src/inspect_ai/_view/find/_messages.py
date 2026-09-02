"""The find-messages endpoint: request/response models and the search over one sample."""

import json
import re
import time
from collections import OrderedDict
from dataclasses import replace
from typing import NamedTuple

import anyio
from pydantic import BaseModel

from inspect_ai._util.textsearch import FoldedText, compile_query
from inspect_ai.event._pool import materialize_pooled_events
from inspect_ai.event._validate import validate_chat_messages
from inspect_ai.log._condense import resolve_events_attachments
from inspect_ai.log._file import read_eval_log_sample_async
from inspect_ai.log._recorders.buffer import sample_buffer
from inspect_ai.model._chat_message import ChatMessage

from ._projection import DisplayMode, ProjectionOptions, ToolCallStyle, project_row
from ._rows import MessageRow, message_rows, messages_from_events, row_anchors

MAX_ROWS = 1000  # a guess: bounds the rows the client splices in per page
# Stop a page once we have at least one match and this much time has passed
# so the first hits can paint while the rest of the scan continues. 50ms is an
# uncalibrated guess for "first paint feels instant".
_SCAN_BUDGET_S = 0.05


class FindMessagesProjection(BaseModel):
    """How the viewer currently shows the rows; a host sends only what it changed."""

    unlabeled_roles: list[str] = []
    tool_call_style: ToolCallStyle = "complete"
    display_mode: DisplayMode = "rendered"
    """`raw` shows markdown source (link URLs included), so nothing is stripped."""


class FindMessagesRequest(BaseModel):
    sample_id: str | int
    epoch: int
    text: str
    after: str | None = None
    """Resume strictly after the row with this anchor; None or an unknown anchor starts at the top."""
    projection: FindMessagesProjection | None = None
    """Omitted (or None) means the viewer defaults."""


class FindMessagesRow(BaseModel):
    anchor: str
    index: int
    """0-based position of the row in the sample's row list."""
    count: int
    """Non-overlapping matches in the row's projection; the client corrects it against the DOM."""
    texts: list[str]
    """The distinct source substrings matched, in first-appearance order."""


class FindMessagesResponse(BaseModel):
    rows: list[FindMessagesRow]
    """Matching rows in order; rows[0] is the first match after `after`."""
    at_end: bool
    """This page reached the last row the sample has right now; else page on
    with `after` = the last anchor."""
    complete: bool
    """Whether the sample is sealed; a running sample is never complete."""


class _SampleIndex:
    """A sample's rows, folded once per projection options."""

    def __init__(self, messages: list[ChatMessage], complete: bool) -> None:
        self.complete = complete
        self.rows: list[MessageRow] = message_rows(messages)
        self.anchors: list[str] = row_anchors(self.rows)
        self.anchor_index = {anchor: i for i, anchor in enumerate(self.anchors)}
        self.roles = frozenset(row.message.role for row in self.rows)
        self._folded: OrderedDict[ProjectionOptions, list[FoldedText | None]] = (
            OrderedDict()
        )

    async def folded_row(self, i: int, options: ProjectionOptions) -> FoldedText:
        # roles absent from the sample cannot change the projection, so they
        # do not get their own cache entry
        options = replace(options, unlabeled_roles=options.unlabeled_roles & self.roles)
        folded = self._folded.get(options)
        if folded is None:
            folded = [None] * len(self.rows)
            self._folded[options] = folded
            while len(self._folded) > _MAX_FOLDED_VARIANTS:
                self._folded.popitem(last=False)
        else:
            self._folded.move_to_end(options)
        at = folded[i]
        if at is None:
            text = "\n".join(project_row(self.rows[i], options))
            if len(text) > _FOLD_IN_THREAD_CHARS:
                at = await anyio.to_thread.run_sync(FoldedText, text)
            else:
                at = FoldedText(text)
            folded[i] = at
        return at


_MAX_FOLDED_VARIANTS = 4  # a guess: one viewer option set, a host toggling a few
# Folding non-ASCII runs is Python-level (~0.5 us/char); a row past this size is
# folded in a thread so the view-server loop keeps serving. An uncalibrated
# guess for "long enough that the fold is a visible stall".
_FOLD_IN_THREAD_CHARS = 100_000
_MAX_CACHED_SAMPLES = 8  # a guess: a few open tabs; completed samples are immutable

# keyed by path only: a log rewritten at the same path serves stale rows until
# eviction; stat-ing remote logs on every keystroke is not worth that rare case
_cache: OrderedDict[tuple[str, str, str, int], _SampleIndex] = OrderedDict()


def _index_key(
    location: str, sample_id: str | int, epoch: int
) -> tuple[str, str, str, int]:
    return location, type(sample_id).__name__, str(sample_id), epoch


async def find_messages(
    location: str, request: FindMessagesRequest
) -> FindMessagesResponse | None:
    """Search one sample's Messages rows; None when the sample is not found."""
    index = await _sample_index(location, request.sample_id, request.epoch)
    if index is None:
        return None
    projection = request.projection or FindMessagesProjection()
    options = ProjectionOptions(
        frozenset(projection.unlabeled_roles),
        projection.tool_call_style,
        projection.display_mode,
    )
    return await _page(index, options, request)


class _RowMatches(NamedTuple):
    occurrences: int
    texts: list[str]


async def _page(
    index: _SampleIndex, options: ProjectionOptions, request: FindMessagesRequest
) -> FindMessagesResponse:
    query = compile_query(request.text)
    if query is None:
        return FindMessagesResponse(rows=[], at_end=True, complete=index.complete)
    n = len(index.rows)
    # "" is a legal anchor (a message with an empty id), so test for None
    after = index.anchor_index.get(request.after) if request.after is not None else None
    i = 0 if after is None else after + 1
    page: list[FindMessagesRow] = []
    deadline: float | None = None
    while i < n and len(page) < MAX_ROWS:
        if deadline is not None and time.perf_counter() >= deadline:
            break
        matches = _row_matches(await index.folded_row(i, options), query)
        if matches.occurrences:
            page.append(
                FindMessagesRow(
                    anchor=index.anchors[i],
                    index=i,
                    count=matches.occurrences,
                    texts=matches.texts,
                )
            )
            if deadline is None:
                deadline = time.perf_counter() + _SCAN_BUDGET_S
        i += 1
        # the budget starts after the first hit; a miss still has to scan to
        # the end for at_end, so yield so the view-server loop is not pinned
        if i % 32 == 0:
            await anyio.lowlevel.checkpoint()
    return FindMessagesResponse(rows=page, at_end=i == n, complete=index.complete)


def _row_matches(row: FoldedText, query: re.Pattern[str] | None) -> _RowMatches:
    texts: dict[str, None] = {}
    count = 0
    for start, end in row.find_all(query):
        texts.setdefault(row.text[start:end])
        count += 1
    return _RowMatches(count, list(texts))


async def _sample_index(
    location: str, sample_id: str | int, epoch: int
) -> _SampleIndex | None:
    key = _index_key(location, sample_id, epoch)
    cached = _cache.get(key)
    if cached is not None:
        _cache.move_to_end(key)
        return cached
    messages = await _logged_messages(location, sample_id, epoch)
    if messages is not None:
        index = _SampleIndex(messages, complete=True)
        _cache[key] = index
        while len(_cache) > _MAX_CACHED_SAMPLES:
            _cache.popitem(last=False)
        return index
    # a running sample is still changing, so it is never cached
    messages = _running_messages(location, sample_id, epoch)
    if messages is not None:
        return _SampleIndex(messages, complete=False)
    # the sample may have been sealed into the log between the two probes
    messages = await _logged_messages(location, sample_id, epoch)
    return _SampleIndex(messages, complete=True) if messages is not None else None


async def _logged_messages(
    location: str, sample_id: str | int, epoch: int
) -> list[ChatMessage] | None:
    try:
        sample = await read_eval_log_sample_async(
            location,
            sample_id,
            epoch,
            resolve_attachments="core",
            exclude_fields={"events", "store"},
        )
    except IndexError:
        return None
    return sample.messages


def _running_messages(
    location: str, sample_id: str | int, epoch: int
) -> list[ChatMessage] | None:
    """Messages of a sample still in the recorder's buffer, as the live Messages tab shows them.

    Sync on the event loop like `/pending-sample-data`: the buffer can be
    filestore-backed (fsspec) and must not be wrapped in `to_thread`.
    """
    try:
        buffer = sample_buffer(location)
    except FileNotFoundError:
        return None
    data = buffer.get_sample_data(id=str(sample_id), epoch=epoch)
    if data is None:
        return None
    message_pool = validate_chat_messages(
        [json.loads(entry.data) for entry in data.message_pool],
        context={"deserializing": True},
    )
    call_pool = [json.loads(entry.data) for entry in data.call_pool]
    events = materialize_pooled_events(
        [entry.event for entry in data.events], message_pool, call_pool
    )
    attachments = {entry.hash: entry.content for entry in data.attachments}
    return messages_from_events(resolve_events_attachments(events, attachments))
