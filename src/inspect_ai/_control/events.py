"""Per-sample transcript event pages for the control channel.

Backs ``GET /evals/<id>/sample/events`` (and ``inspect ctl events``): a
**cursored-pull** window over one sample's events, read from its live
``Transcript`` while running and from the on-disk log once terminal.

The cursor is an opaque token = ``(source nonce, absolute event offset)``.
The offset indexes the *unfiltered* event sequence; type / time filters are
applied to the page *after* slicing, and ``next`` advances past every event
*scanned* (not just matched) so a sparse filter never re-walks or skips. The
nonce identifies one *attempt* of a sample — the sample uuid (``EvalSample
.uuid`` == ``TaskState.uuid``) plus the attempt count (see :func:`_attempt_
nonce`). Both the running and terminal sources derive it the same way, so a
cursor issued mid-run stays valid once the sample is logged rather than looking
stale and restarting. A retry runs on a fresh transcript, so its nonce differs
(a fresh uuid for a task-level retry, an incremented attempt count for an
in-process ``retry_on_error``); a cursor carried across one no longer matches
and correctly restarts from the beginning instead of serving a stale position.

See ``design/control-channel.md`` (phase 2) for the full rationale.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Sequence
from logging import getLogger
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from inspect_ai.event._event import Event
    from inspect_ai.log._transcript import TranscriptHistoryProvider

logger = getLogger(__name__)

# Page reader for one source: ``fetch(start, limit)`` returns up to ``limit``
# events from absolute offset ``start``. The running source reads through
# ``TranscriptHistory.events_from`` (resident fast path, history-provider
# materialization below the resident window); the terminal source slices its
# in-memory list.
EventsFetch = Callable[[int, int], "Sequence[Event]"]

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

    Returns an envelope ``{events, next, done}`` (see module docstring), or
    ``None`` when the eval/sample isn't found in this process — the endpoint
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

    nonce, fetch, total, done = source

    # Resolve the start offset: resume from the cursor (reset to 0 if the nonce
    # is from a different source), else a tail window, else the beginning.
    cursor_nonce, cursor_offset = decode_cursor(since)
    if since is not None and cursor_nonce == nonce:
        offset = max(0, cursor_offset)
    elif since is not None:
        offset = 0  # stale/foreign cursor → restart
    elif tail is not None:
        offset = max(0, total - tail)
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
    scanned = list(fetch(offset, limit))
    next_offset = offset + len(scanned)

    matched = _filter(scanned, types, since_time, until)
    return {
        "events": [_project(e, full) for e in matched],
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


def _running_source(
    eval_id: str, sample_id: str, epoch: int
) -> tuple[str, EventsFetch, int, bool] | None:
    """The live source for a sample, or ``None`` if it isn't running here.

    Returns ``(nonce, fetch, total, done)``. The fetch reads through
    ``TranscriptHistory.events_from``, which serves resident events from
    memory and materializes evicted ones from the history provider (the
    realtime sample buffer) — so a cursor below the resident window of a
    bounded transcript still pages gap-free, page-sized reads only (the
    ``limit`` rides down to the buffer query). It raises ``RuntimeError``
    when the requested range was evicted with no provider to recover it (a
    bounded transcript without realtime logging — not a production
    configuration).
    """
    from inspect_ai.log._samples import active_samples

    for s in active_samples():
        if s.eval_id == eval_id and str(s.sample.id) == sample_id and s.epoch == epoch:
            history = s.transcript.history
            return (
                _attempt_nonce(s.sample_uuid, s.sample.id, epoch, len(s.error_retries)),
                history.events_from,
                history.event_count,
                s.completed is not None,
            )
    return None


async def _logged_source(
    eval_id: str, sample_id: str, epoch: int
) -> tuple[str, EventsFetch, int, bool] | None:
    """The terminal source for a sample (recorder buffer, then on-disk log).

    Returns ``(nonce, fetch, total, True)``; ``None`` when the eval/sample
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
                return nonce, provider.events_from, total, True

    def fetch(start: int, limit: int) -> list["Event"]:
        return events[start : start + limit]

    return nonce, fetch, len(events), True


def _events_provider(
    eval_id: str, sample_id: str | int, epoch: int
) -> "TranscriptHistoryProvider | None":
    """The eval's buffer-backed history provider for one sample, or ``None``.

    Resolved through ``EvalState.events_provider`` — the gap-free events
    source for a streaming-path sample whose recorder copy is event-less
    (its events live in the realtime buffer, the same one the view server
    reads in-progress samples from). The TaskLogger registers a factory over
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
    if state is None or state.events_provider is None:
        return None
    return state.events_provider(sample_id, epoch)


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
