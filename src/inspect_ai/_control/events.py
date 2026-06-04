"""Per-sample transcript event pages for the control channel.

Backs ``GET /evals/<id>/sample/events`` (and ``inspect ctl events``): a
**cursored-pull** window over one sample's events, read from its live
``Transcript`` while running and from the on-disk log once terminal.

The cursor is an opaque token = ``(source nonce, absolute event offset)``.
The offset indexes the *unfiltered* event sequence; type / time filters are
applied to the page *after* slicing, and ``next`` advances past every event
*scanned* (not just matched) so a sparse filter never re-walks or skips. The
nonce identifies the specific source (a sample attempt's ``ActiveSample`` while
running, the log sample's uuid once terminal); a token whose nonce no longer
matches — e.g. carried across a retry that minted a fresh transcript — restarts
from the beginning rather than silently serving a stale position.

See ``design/control-channel.md`` (phase 2) for the full rationale.
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from inspect_ai.event._event import Event

# Default event-type filter: the "high-signal" tier a monitor cares about,
# excluding the structural / high-volume tier (state / store / span / step / …)
# which would drown the stream. ``--type '*'`` opts back into everything.
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
    full: bool = False,
    since_time: float | None = None,
    until: float | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> dict[str, Any] | None:
    """A page of one sample's transcript events.

    Returns an envelope ``{events, next, done, missed}`` (see module docstring),
    or ``None`` when the eval/sample isn't found in this process — the endpoint
    turns that into a 404.

    Args:
        eval_id: The eval's id.
        sample_id: The sample's id (string; matched against running + logged).
        epoch: The sample epoch.
        since: Cursor token from a prior page (resume after it). Exclusive.
        tail: When ``since`` is absent, start ``tail`` events from the end.
        types: Event-type filter; ``None`` = the high-signal tier, an empty-vs-
            ``{"*"}`` set means "all". Applied after the cursor slice.
        full: Raw serialized events instead of the compact projection.
        since_time: Optional lower bound (unix ts) — a wall-clock filter applied
            after the cursor slice, never a cursor.
        until: Optional upper bound (unix ts).
        limit: Max events scanned per page.
    """
    source = _running_source(eval_id, sample_id, epoch)
    if source is None:
        source = await _logged_source(eval_id, sample_id, epoch)
    if source is None:
        return None

    nonce, resident, first_resident, total, done = source

    # Resolve the start offset: resume from the cursor (reset to 0 if the nonce
    # is from a different source), else a tail window, else the beginning.
    cursor_nonce, cursor_offset = decode_cursor(since)
    if since is not None and cursor_nonce == nonce:
        offset = cursor_offset
    elif since is not None:
        offset = 0  # stale/foreign cursor → restart
    elif tail is not None:
        offset = max(0, total - tail)
    else:
        offset = 0

    # Events below the resident window were evicted (bounded transcripts):
    # report the gap and start from the oldest resident event.
    missed = max(0, first_resident - offset)
    start = max(offset, first_resident)
    rel = start - first_resident
    scanned = list(resident[rel : rel + limit])
    next_offset = start + len(scanned)

    matched = _filter(scanned, types, since_time, until)
    return {
        "events": [_project(e, full) for e in matched],
        "next": encode_cursor(nonce, next_offset),
        "done": done and next_offset >= total,
        "missed": missed,
    }


# --- sources ---------------------------------------------------------------


def _running_source(
    eval_id: str, sample_id: str, epoch: int
) -> tuple[str, list["Event"], int, int, bool] | None:
    """The live source for a sample, or ``None`` if it isn't running here.

    Returns ``(nonce, resident_events, first_resident_index, total, done)``.
    """
    from inspect_ai.log._samples import active_samples

    for s in active_samples():
        if s.eval_id == eval_id and str(s.sample.id) == sample_id and s.epoch == epoch:
            history = s.transcript.history
            total = history.event_count
            resident = list(history.resident_events)
            return (
                s.id,  # nonce: ActiveSample id — fresh per attempt
                resident,
                total - len(resident),
                total,
                s.completed is not None,
            )
    return None


async def _logged_source(
    eval_id: str, sample_id: str, epoch: int
) -> tuple[str, list["Event"], int, int, bool] | None:
    """The terminal source for a sample (recorder buffer, then on-disk log).

    Returns ``(nonce, events, 0, total, True)``; ``None`` when the eval/sample
    isn't available here (not in this process, or not yet readable). Reads via
    :func:`inspect_ai._control.state._full_sample` so a just-completed (or
    reused-on-retry) sample's events are visible the moment the samples listing
    shows it — the same gap-free recorder source, not just the on-disk log.

    The streaming completion path retains only an *event-less* sample in the
    recorder (its events live in the buffer database, not on the sample), so
    when the resolved sample carries no events we read them from the buffer —
    keeping the page gap-free for that window too.
    """
    from inspect_ai._control.state import _full_sample

    sid: str | int = int(sample_id) if sample_id.lstrip("-").isdigit() else sample_id
    sample = await _full_sample(eval_id, sid, epoch)
    if sample is None:
        return None

    events = list(sample.events)
    if not events:
        buffered = _buffer_events(eval_id, sid, epoch)
        if buffered is not None:
            events = buffered

    nonce = sample.uuid or f"{sample_id}:{epoch}"
    return nonce, events, 0, len(events), True


def _buffer_events(
    eval_id: str, sample_id: str | int, epoch: int
) -> list["Event"] | None:
    """The sample's events from the buffer database, or ``None``.

    The gap-free events source for a streaming-path sample whose recorder copy
    is event-less and which hasn't yet been flushed to disk (the same buffer
    the view server reads in-progress samples from). ``None`` when there's no
    buffer (eval finished / no streaming) or it doesn't hold the sample, so the
    caller keeps whatever the recorder/on-disk sample provided.
    """
    from inspect_ai._control.eval_state import get_eval_state

    state = get_eval_state(eval_id)
    if state is None or not state.log_location:
        return None

    from inspect_ai.log._recorders.buffer import sample_buffer

    data = sample_buffer(state.log_location).get_sample_data(sample_id, epoch)
    if data is None:
        return None

    from inspect_ai.event._validate import validate_events

    return validate_events([event_data.event for event_data in data.events])


# --- filtering + projection ------------------------------------------------


def _filter(
    events: list["Event"],
    types: frozenset[str] | None,
    since_time: float | None,
    until: float | None,
) -> list["Event"]:
    """Apply the type filter (default = high-signal) and time window."""
    allow_all = types is not None and "*" in types
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


def _project(event: "Event", full: bool) -> dict[str, Any]:
    """Raw serialized event (``full``) or a compact, context-cheap summary.

    The compact form always carries the common header (type, ids, time); a few
    high-signal types add a small, truncated summary. Everything else is
    header-only — ``--full`` is there when the detail is needed.
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
            out["completion"] = _truncate(getattr(output, "completion", "") or "")
        out["error"] = getattr(event, "error", None)
    elif et == "tool":
        out["function"] = getattr(event, "function", None)
        out["arguments"] = _truncate(_to_text(getattr(event, "arguments", None)))
        out["result"] = _truncate(_to_text(getattr(event, "result", None)))
        tool_error = getattr(event, "error", None)
        out["error"] = getattr(tool_error, "message", None) if tool_error else None
    elif et == "error":
        err = getattr(event, "error", None)
        out["error"] = getattr(err, "message", None) if err else None
    elif et == "info":
        out["source"] = getattr(event, "source", None)
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
