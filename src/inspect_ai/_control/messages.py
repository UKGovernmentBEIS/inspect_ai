"""One sample's current conversation for the control channel.

Backs ``GET /evals/<id>/sample/messages`` (and ``inspect ctl sample
messages``): a **snapshot** of one sample's ``TaskState.messages`` — the
top-level conversation as it looks right now — read from the live
``TaskState`` while the sample is running, and once terminal from the
recorder's sample (buffer, then on-disk log).

Unlike ``sample events``, this is deliberately *not* cursored. The message
list is rewritable — compaction replaces a prefix with a summary, and solver /
agent code can edit or wholesale-reassign ``state.messages`` — so an index
cursor over it could not deliver the exactly-once resume the event cursor
promises. Each call returns the whole conversation (or a recent tail),
enveloped with ``as_of`` / the sample ``status`` / the total ``count``; a
watcher polls (the moving ``count`` is the cheap staleness signal) or follows
``sample events`` for incremental, event-grain watching.

See ``design/control-channel.md`` ("Sample messages read") for the full
rationale.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, NamedTuple

# The compact message projection shares its truncation helpers with the events
# projection so the two renderings of the same underlying objects can't drift.
from inspect_ai._control.events import _to_text, _truncate

if TYPE_CHECKING:
    from inspect_ai.model._chat_message import ChatMessage


class MessagesSource(NamedTuple):
    """One resolvable source of a sample's conversation.

    Produced by :func:`_running_source` (live ``TaskState``) and
    :func:`_logged_source` (recorder / on-disk log); consumed by
    :func:`sample_messages`.
    """

    messages: list["ChatMessage"]
    """The sample's current conversation (a snapshot copy)."""

    status: str
    """``running`` / ``completed`` / ``error``."""


async def sample_messages(
    eval_id: str,
    sample_id: str,
    epoch: int,
    *,
    tail: int | None = None,
    full: bool = False,
) -> dict[str, Any] | None:
    """A snapshot of one sample's current conversation.

    Returns an ``{as_of, status, count, messages}`` envelope (see the module
    docstring), or ``None`` when the eval/sample isn't found in this process —
    the endpoint turns that into a 404.

    Args:
        eval_id: The eval's id.
        sample_id: The sample's id (string; matched against running + logged).
        epoch: The sample epoch.
        tail: Only the last ``tail`` messages (``None`` = the whole list).
        full: Raw serialized ``ChatMessage`` objects instead of the compact
            projection.
    """
    # `as_of` is stamped before the read so a client comparing successive
    # `count`s can't miss a change that lands mid-read.
    as_of = time.time()

    source = _running_source(eval_id, sample_id, epoch)
    if source is None:
        source = await _logged_source(eval_id, sample_id, epoch)
    if source is None:
        return None

    messages, status = source
    count = len(messages)

    # `tail` selects a recent window; the projection still reports each
    # message's absolute index so a tailed view lines up with the full one.
    start = max(0, count - tail) if tail is not None else 0
    projected = [
        _project(message, index, full)
        for index, message in enumerate(messages[start:], start=start)
    ]

    return {
        "as_of": as_of,
        "status": status,
        "count": count,
        "messages": projected,
    }


# --- sources ---------------------------------------------------------------


def _running_source(eval_id: str, sample_id: str, epoch: int) -> MessagesSource | None:
    """The live source for a sample, or ``None`` if it isn't running here.

    Reads the sample's live ``TaskState.messages`` off ``ActiveSample
    .live_state`` — an in-memory snapshot, no log involved, which is why a
    sample that exists only in the process buffer still has a conversation to
    serve. The control server shares the eval's event loop, so copying the
    list here can never observe a half-applied append or rewrite.
    """
    from inspect_ai._control.state import find_active_sample

    s = find_active_sample(eval_id, sample_id, epoch)
    if s is None or s.live_state is None:
        return None
    return MessagesSource(
        messages=list(s.live_state.messages),
        status="completed" if s.completed is not None else "running",
    )


async def _logged_source(
    eval_id: str, sample_id: str, epoch: int
) -> MessagesSource | None:
    """The terminal source for a sample (recorder buffer, then on-disk log).

    ``None`` when the eval/sample isn't available here. Reads the full
    ``EvalSample`` via :func:`inspect_ai._control.state._full_sample` — the
    same gap-free recorder-then-log source the error-detail and events reads
    use — and resolves its content attachments so image/large-text refs render
    as real content rather than ``attachment://`` placeholders.
    """
    from inspect_ai._control.state import _full_sample

    sample = await _full_sample(eval_id, sample_id, epoch)
    if sample is None:
        return None

    from inspect_ai.log._condense import resolve_sample_attachments

    sample = resolve_sample_attachments(sample, "full")
    return MessagesSource(
        messages=list(sample.messages or []),
        status="error" if sample.error is not None else "completed",
    )


# --- projection ------------------------------------------------------------


def _project(message: "ChatMessage", index: int, full: bool) -> dict[str, Any]:
    """Raw serialized message (``full``) or a compact, context-cheap summary.

    The compact form carries the message's index / id / role plus a truncated
    text rendering (non-text content items summarized as ``[image]`` /
    ``[audio]`` / …); assistant messages add their tool-call function names and
    truncated arguments, tool messages their truncated output and any error.
    """
    if full:
        out = message.model_dump(mode="json")
        out["index"] = index
        return out

    projected: dict[str, Any] = {
        "index": index,
        "id": message.id,
        "role": message.role,
        "content": _content_summary(message),
    }
    if message.role == "assistant":
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            projected["tool_calls"] = [
                {
                    "id": call.id,
                    "function": call.function,
                    "arguments": _truncate(_to_text(call.arguments)),
                }
                for call in tool_calls
            ]
    elif message.role == "tool":
        projected["function"] = getattr(message, "function", None)
        tool_error = getattr(message, "error", None)
        projected["error"] = (
            getattr(tool_error, "message", None) if tool_error else None
        )
    return projected


def _content_summary(message: "ChatMessage") -> str:
    """Truncated text of a message, with non-text content items summarized.

    A string content renders (truncated) directly; a list of content items
    renders each text/reasoning item's text and each non-text item as a
    ``[kind]`` placeholder, so an image-bearing message reads as
    ``… [image] …`` rather than a wall of base64.
    """
    content = message.content
    if isinstance(content, str):
        return _truncate(content)

    parts: list[str] = []
    for item in content:
        item_type = getattr(item, "type", None)
        if item_type in ("text", "reasoning"):
            parts.append(getattr(item, item_type, "") or "")
        else:
            parts.append(f"[{item_type or 'content'}]")
    return _truncate(" ".join(p for p in parts if p))
