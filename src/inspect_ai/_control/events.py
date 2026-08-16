"""Per-sample transcript event pages for the control channel.

Backs ``GET /evals/<id>/sample/events`` (and ``inspect ctl sample events``): a
**cursored-pull** window over one sample's events, read from its live
``Transcript`` while running, and once terminal from the recorder's
sample, the realtime buffer (via the eval's events provider — the
streaming-completion path retains an event-less recorder sample), or the
on-disk log (see ``_logged_source``).

The cursor is an opaque token = ``(source nonce, absolute event offset)``.
The offset indexes the *unfiltered* event sequence; type / time filters are
applied to the page *after* slicing, and ``next`` advances past every event
*scanned* (not just matched) so a sparse filter never re-walks or skips. The
``tail`` seed is the one place that counts *matched* events: it scans the
trailing page-bounded window and keeps the last ``tail`` matches, so a recent
tail under the default high-signal filter surfaces a useful window rather
than the few matches hiding in the last N raw events (a live transcript is
dominated by structural state / store / span events). The
nonce identifies one *attempt* of a sample — the sample uuid (``EvalSample
.uuid`` == ``TaskState.uuid``) plus the attempt count (see :func:`_attempt_
nonce`). Both the running and terminal sources derive it the same way, so a
cursor issued mid-run stays valid once the sample is logged rather than looking
stale and restarting. A retry runs on a fresh transcript, so its nonce differs
(a fresh uuid for a task-level retry, an incremented attempt count for an
in-process ``retry_on_error``); a cursor carried across one no longer matches
and correctly restarts from the beginning instead of serving a stale position.

See ``design/ctl/control-channel.md`` (phase 2) for the full rationale.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Sequence
from logging import getLogger
from typing import TYPE_CHECKING, Any, NamedTuple

from inspect_ai._control.terminal_cache import (
    TerminalSourceCache,
    invalidate_terminal_sources,
)

if TYPE_CHECKING:
    from inspect_ai.event._event import Event
    from inspect_ai.log._transcript import TranscriptHistoryProvider

logger = getLogger(__name__)

# Page reader for one source: ``fetch(start, limit)`` returns up to ``limit``
# events from absolute offset ``start``. The running source reads through
# ``TranscriptHistory.events_from`` (resident fast path, history-provider
# materialization below the resident window); the terminal source either
# slices its in-memory list or pages the realtime buffer via the eval's
# events provider.
EventsFetch = Callable[[int, int], "Sequence[Event]"]


class EventsSource(NamedTuple):
    """One resolvable source of a sample's transcript events.

    Produced by ``_running_source`` (live transcript) and ``_logged_source``
    (recorder / buffer / on-disk log); consumed by ``sample_events``.
    """

    nonce: str
    """Cursor nonce identifying this source's sample attempt."""

    fetch: EventsFetch
    """Page reader over the source's unfiltered event sequence."""

    total: int
    """Total events in the source at resolution time."""

    done: bool
    """Whether the sample has terminated (no more events will come)."""


# Default event-type filter: the "high-signal" tier a monitor cares about,
# excluding the structural / high-volume tier (state / store / span / step / …)
# which would drown the stream. ``--type all`` (or the ``'*'`` synonym) opts
# back into everything.
HIGH_SIGNAL_EVENT_TYPES = frozenset(
    {
        "model",
        "tool",
        "error",
        "score",
        "approval",
        "input",
        "sandbox",
        "logger",
        "info",
        "sample_limit",
        "interrupt",
    }
)

# Max events scanned per page — bounds response size for a long backlog; the
# caller paginates via ``next``.
DEFAULT_PAGE_LIMIT = 500

# Compact-projection truncation width for free-text / serialized fields.
_TRUNCATE = 256

# Short-TTL cache of resolved terminal sources. A flushed sample's transcript
# is immutable, but resolving it re-reads and re-validates the entire sample
# per page request (see _resolve_logged_source) — O(N²/limit) aggregate work
# for a client paginating an N-event transcript, and a full parse per poll
# even when no new events can ever arrive. See terminal_cache for the
# staleness bounds (insertion-time TTL, running-attempt invalidation,
# cleared with the eval-state registry).
_terminal_sources: TerminalSourceCache[EventsSource] = TerminalSourceCache()


def encode_cursor(nonce: str, offset: int) -> str:
    """Opaque cursor token for ``(source nonce, absolute offset)``."""
    raw = json.dumps({"n": nonce, "i": offset}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(token: str | None) -> tuple[str | None, int]:
    """Decode a cursor token into ``(nonce, offset)``.

    A missing or malformed token decodes to ``(None, 0)`` — "start from the
    beginning", the safe default (a confused client just re-reads).
    """
    if not token:
        return None, 0
    try:
        data = json.loads(base64.urlsafe_b64decode(token.encode("ascii")))
        return str(data["n"]), int(data["i"])
    except (ValueError, KeyError, TypeError):
        return None, 0


async def sample_events(
    eval_id: str,
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
) -> dict[str, Any] | None:
    """A page of one sample's transcript events.

    Returns an envelope ``{events, next, done}`` (see module docstring), or
    ``None`` when the eval/sample isn't found in this process — the endpoint
    turns that into a 404.

    Args:
        eval_id: The eval's id.
        sample_id: The sample's id (string; matched against running + logged).
        epoch: The sample epoch.
        since: Cursor token from a prior page (resume after it). Exclusive.
        tail: When ``since`` is absent, show the last ``tail`` events that
            match the type/time filters: the trailing ``limit``-bounded
            window is scanned and the filtered page keeps its last ``tail``
            entries.
        types: Event-type filter; ``None`` = the high-signal tier; a set
            containing ``"all"`` or ``"*"`` means everything (safe magic
            values — no event type carries either name). Applied after the
            cursor slice.
        content: Include (truncated) free-text content — completions, tool
            arguments/results, error messages — in the compact projection.
            The default is metadata only (see :func:`_project`).
        full: Raw serialized events instead of the compact projection.
        since_time: Optional lower bound (unix ts) — a wall-clock filter applied
            after the cursor slice, never a cursor.
        until: Optional upper bound (unix ts).
        limit: Max events scanned per page.
    """
    source = _running_source(eval_id, sample_id, epoch)
    if source is not None:
        # a running attempt (a retry) supersedes any cached terminal source
        # for this sample — drop it (from every projection's cache, not just
        # this endpoint's) so the attempt's own terminal source is resolved
        # fresh once it finishes (see terminal_cache)
        invalidate_terminal_sources((eval_id, sample_id, epoch))
    else:
        source = await _logged_source(eval_id, sample_id, epoch)
    if source is None:
        return None

    nonce, fetch, total, done = source

    # Resolve the start offset: resume from the cursor (reset to 0 if the nonce
    # is from a different source), else a tail window, else the beginning.
    cursor_nonce, cursor_offset = decode_cursor(since)
    # When set, slice the filtered page down to its last `tail_count` events.
    tail_count: int | None = None
    if since is not None and cursor_nonce == nonce:
        offset = max(0, cursor_offset)
    elif since is not None:
        offset = 0  # stale/foreign cursor → restart
    elif tail is not None:
        # A tail read means "the last `tail` events the caller will see" —
        # counted after the type/time filters, not over the raw sequence.
        # Slicing the raw sequence under-delivered badly with the default
        # high-signal filter: a live transcript is dominated by structural
        # state/store/span events, so the last N raw events could contain a
        # single match. Seed at one page bound from the end and keep the
        # last `tail` matches after filtering (below).
        offset = max(0, total - limit)
        tail_count = max(0, tail)
    else:
        offset = 0

    # The page is always contiguous from `offset`: a bounded transcript's
    # evicted events are re-materialized from its history provider (the
    # realtime sample buffer). The fetch raises if `offset` falls below the
    # resident window with no provider to recover it — not a production
    # configuration (bounded mode is only enabled together with the buffer,
    # which is the provider), and a hard error beats serving a silently-gapped
    # stream. `next` advances by what was actually served, so a fetch that
    # returns short (eg. a buffer that lags the in-memory tail) never skips
    # events — the next poll picks them up.
    from inspect_ai.log._transcript import TranscriptHistoryUnavailableError

    try:
        scanned = list(fetch(offset, limit))
    except TranscriptHistoryUnavailableError:
        if tail_count is None:
            raise
        # The matched-tail scan window reached below a bounded transcript's
        # resident window with no provider to recover it (not a production
        # configuration). Degrade to the raw-event tail seed — the resident
        # window stays readable — rather than failing the default read.
        offset = max(0, total - tail_count) if tail_count > 0 else total
        tail_count = None
        scanned = list(fetch(offset, limit))
    next_offset = offset + len(scanned)

    matched = _filter(scanned, types, since_time, until)
    if tail_count is not None:
        # Keep the most recent matches; earlier matches inside the scanned
        # window are intentionally dropped (the read is seeded "near the
        # end") while `next` still advances past everything scanned.
        matched = matched[-tail_count:] if tail_count > 0 else []
    return {
        "events": [_project(e, content=content, full=full) for e in matched],
        "next": encode_cursor(nonce, next_offset),
        "done": done and next_offset >= total,
    }


# --- sources ---------------------------------------------------------------


def _attempt_nonce(
    sample_uuid: str | None, sample_id: str | int | None, epoch: int, attempts: int
) -> str:
    """Cursor nonce identifying one *attempt* of a sample's transcript.

    The sample uuid alone isn't enough: ``retry_on_error`` re-runs a sample with
    a fresh transcript but reuses ``state.uuid`` (so the logged sample keeps a
    stable identity across attempts). Keying the cursor on the uuid alone would
    let an earlier attempt's cursor resume against the retry's unrelated
    transcript, skipping events. Folding in the attempt count — the number of
    prior failed attempts, which both sources read off ``error_retries`` and
    which the final logged sample preserves — gives each attempt a distinct
    nonce while still aligning the running and terminal views of the *same*
    attempt.

    The ``id:epoch`` fallback only applies to the terminal source: a running
    sample always carries its ``sample_uuid`` (``ActiveSample.sample_uuid`` is a
    required ``str`` from ``state.uuid``), but a terminal ``EvalSample.uuid`` is
    ``Optional`` and reads back ``None`` for a sample logged by an inspect
    version predating the uuid field (reachable only via a reused log).
    """
    base = sample_uuid or f"{sample_id}:{epoch}"
    return f"{base}:{attempts}"


def _running_source(eval_id: str, sample_id: str, epoch: int) -> EventsSource | None:
    """The live source for a sample, or ``None`` if it isn't running here.

    The fetch reads through ``TranscriptHistory.events_from``, which serves
    resident events from memory and materializes evicted ones from the
    history provider (the realtime sample buffer) — so a cursor below the
    resident window of a bounded transcript still pages gap-free, page-sized
    reads only (the ``limit`` rides down to the buffer query). It raises
    ``TranscriptHistoryUnavailableError`` when the requested range was
    evicted with no provider to recover it (a bounded transcript without
    realtime logging — not a production configuration).
    """
    from inspect_ai._control.state import find_active_sample

    s = find_active_sample(eval_id, sample_id, epoch)
    if s is None:
        return None
    history = s.transcript.history
    return EventsSource(
        nonce=_attempt_nonce(s.sample_uuid, s.sample.id, epoch, len(s.error_retries)),
        fetch=history.events_from,
        total=history.event_count,
        done=s.completed is not None,
    )


async def _logged_source(
    eval_id: str, sample_id: str, epoch: int
) -> EventsSource | None:
    """The terminal source for a sample, resolved through the short-TTL cache.

    A terminal attempt's transcript is immutable, so the resolved source is
    reused across the paginating / polling requests that dominate this
    endpoint's traffic instead of re-paying the full-sample parse per request
    (see ``_terminal_sources`` and ``TerminalSourceCache.get_or_resolve``).
    """
    return await _terminal_sources.get_or_resolve(
        (eval_id, sample_id, epoch),
        lambda: _resolve_logged_source(eval_id, sample_id, epoch),
    )


async def _resolve_logged_source(
    eval_id: str, sample_id: str, epoch: int
) -> EventsSource | None:
    """The terminal source for a sample (recorder buffer, then on-disk log).

    Always ``done`` (no more events will come); ``None`` when the eval/sample
    isn't available here (not in this process, or not yet readable). Reads via
    :func:`inspect_ai._control.state._full_sample` so a just-completed (or
    reused-on-retry) sample's events are visible the moment the samples listing
    shows it — the same gap-free recorder source, not just the on-disk log.

    The streaming completion path retains only an *event-less* sample in the
    recorder (its events live in the buffer database, not on the sample), so
    when the resolved sample carries no events we page them through the
    eval's registered events provider — keeping the page gap-free for that
    window too.
    """
    from inspect_ai._control.state import _full_sample

    sample = await _full_sample(eval_id, sample_id, epoch)
    if sample is None:
        return None

    nonce = _attempt_nonce(
        sample.uuid, sample.id, epoch, len(sample.error_retries or [])
    )

    events = list(sample.events)
    if not events:
        # Streaming completion path: page through the eval's own buffer
        # instance via the registered events provider — the same
        # materialization as live bounded-transcript reads, with the page
        # limit riding down to the buffer query rather than materializing
        # the full history per request. Use the resolved sample's stored id
        # (not the request string) so the buffer lookup matches exactly —
        # `_full_sample` already reconciled a digit-looking id (e.g. "001")
        # to however it's actually stored.
        from inspect_ai.log._transcript import TranscriptHistoryUnavailableError

        provider = _events_provider(eval_id, sample.id, epoch)
        if provider is not None:
            try:
                total = int(provider.event_count)
            except TranscriptHistoryUnavailableError as ex:
                # the history store was torn down between provider resolution
                # and this first read — degrade to the recorder's (event-less)
                # sample rather than failing the request. Logged because
                # outside that race this can also indicate a genuinely
                # corrupt store.
                logger.warning(
                    "Buffer events read failed for eval %s (sample %s, epoch %d): %s",
                    eval_id,
                    sample.id,
                    epoch,
                    ex,
                )
                total = 0
            if total > 0:
                # bind the narrowed provider for the closure (mypy doesn't
                # carry the not-None narrowing into nested functions)
                resolved_provider = provider

                # the page fetch gets the same degrade contract as the
                # event_count read above: a teardown landing between the two
                # serves a short (empty) page instead of failing the request.
                # `next` advances only by what was served, so no events are
                # skipped — the client's retry re-resolves the source
                # (recorder / on-disk log) once the cached entry expires
                # (see _terminal_sources).
                def fetch_buffered(start: int, limit: int) -> Sequence["Event"]:
                    try:
                        return resolved_provider.events_from(start, limit)
                    except TranscriptHistoryUnavailableError as ex:
                        logger.warning(
                            "Buffer events read failed for eval %s "
                            "(sample %s, epoch %d): %s",
                            eval_id,
                            sample.id,
                            epoch,
                            ex,
                        )
                        return []

                return EventsSource(
                    nonce=nonce, fetch=fetch_buffered, total=total, done=True
                )

    def fetch(start: int, limit: int) -> list["Event"]:
        return events[start : start + limit]

    return EventsSource(nonce=nonce, fetch=fetch, total=len(events), done=True)


def _events_provider(
    eval_id: str, sample_id: str | int, epoch: int
) -> "TranscriptHistoryProvider | None":
    """The eval's buffer-backed history provider for one sample, or ``None``.

    Resolved through ``EvalState.live.sample_events_provider`` — the gap-free
    events source for a streaming-path sample whose recorder copy is event-less
    (its events live in the realtime buffer, the same one the view server
    reads in-progress samples from). The TaskLogger builds the provider over
    its *own* buffer instance (see ``TaskLogger.sample_events_provider``), so
    this layer never knows where or what the buffer is, reads share the
    writer's connections, and the buffer's read leases apply. The provider
    materializes the same way live bounded-transcript reads do — pooled
    message/call refs re-expanded, attachments resolved, superseded
    pending-event versions collapsed. ``None`` for reused/synthetic evals or
    once the buffer is torn down, so the caller keeps whatever the
    recorder/on-disk sample provided.
    """
    from inspect_ai._control.eval_state import get_eval_state

    state = get_eval_state(eval_id)
    if state is None or state.live is None:
        return None
    return state.live.sample_events_provider(sample_id, epoch)


# --- filtering + projection ------------------------------------------------


def _filter(
    events: list["Event"],
    types: frozenset[str] | None,
    since_time: float | None,
    until: float | None,
) -> list["Event"]:
    """Apply the type filter (default = high-signal) and time window."""
    allow_all = types is not None and bool(types & {"all", "*"})
    type_set = HIGH_SIGNAL_EVENT_TYPES if types is None else types

    out: list["Event"] = []
    for e in events:
        if not allow_all and e.event not in type_set:
            continue
        ts = e.timestamp.timestamp()
        if since_time is not None and ts < since_time:
            continue
        if until is not None and ts > until:
            continue
        out.append(e)
    return out


def _project(event: "Event", *, content: bool, full: bool) -> dict[str, Any]:
    """Raw serialized event (``full``) or a compact, context-cheap summary.

    The compact form always carries the common header (type, ids, time); a few
    high-signal types add a small summary. That summary is tiered: by default
    it is **metadata only** — structural fields (model name, token counts,
    stop reason, tool function names, error *presence*) with none of the
    free-text content the evaluated agent controls (completions, tool
    arguments/results, error messages). ``content`` opts into the truncated
    free-text fields; ``full`` returns the raw event. The metadata default
    exists so a monitor that never reads agent-controlled text — and so can't
    be prompt-injected by it — is the effortless default consumer (see
    "Trust boundary for readers" in design/ctl/control-channel.md).
    """
    if full:
        return event.model_dump(mode="json")

    out: dict[str, Any] = {
        "event": event.event,
        "uuid": event.uuid,
        "span_id": event.span_id,
        "timestamp": event.timestamp.timestamp(),
        "pending": event.pending,
    }
    et = event.event
    if et == "model":
        out["model"] = getattr(event, "model", None)
        output = getattr(event, "output", None)
        if output is not None:
            usage = getattr(output, "usage", None)
            out["tokens"] = getattr(usage, "total_tokens", None) if usage else None
            out["stop_reason"] = getattr(output, "stop_reason", None)
            if content:
                out["completion"] = _truncate(getattr(output, "completion", "") or "")
        error = getattr(event, "error", None)
        out["has_error"] = error is not None
        if content:
            out["error"] = error
    elif et == "tool":
        out["function"] = getattr(event, "function", None)
        tool_error = getattr(event, "error", None)
        out["has_error"] = tool_error is not None
        if content:
            out["arguments"] = _truncate(_to_text(getattr(event, "arguments", None)))
            out["result"] = _truncate(_to_text(getattr(event, "result", None)))
            out["error"] = getattr(tool_error, "message", None) if tool_error else None
    elif et == "error":
        # the event type itself is the metadata-tier signal; only the
        # message is content
        if content:
            err = getattr(event, "error", None)
            out["error"] = getattr(err, "message", None) if err else None
    elif et == "info":
        out["source"] = getattr(event, "source", None)
        if content:
            out["data"] = _truncate(_to_text(getattr(event, "data", None)))
    return out


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)


def _truncate(text: str, width: int = _TRUNCATE) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"
