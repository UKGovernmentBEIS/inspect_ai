"""Channel item types.

The channel carries an open/extensible union of typed items. Today the only
implementations are :class:`UserMessage` (data plane) and :class:`Cancel`
(control plane). Future items (``Announce`` for subagent completion,
``Steer`` for orchestrator-to-child messaging) slot in by adding new
dataclasses and extending the union — the channel core does not need to
change.

Items intentionally carry minimal data; consumers interpret them. For
``UserMessage`` that's "append this :class:`ChatMessageUser` to the
conversation at the next boundary." For ``Cancel`` it's "the bound scope
was cancelled with this reason; recover and continue."
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence, Union

from inspect_ai._util.content import Content, ContentText
from inspect_ai.model._chat_message import ChatMessageUser

CancelReason = Literal["user_cancel", "limit", "system"]
"""Provenance discriminator for a :class:`Cancel`.

- ``user_cancel`` — operator-driven (e.g. ACP wire ``session/cancel``, TUI Esc).
- ``limit`` — sample-level limit hit (token / time / cost / messages).
- ``system`` — eval-shutdown paths.

Producers stamp the reason so per-event provenance stays consistent
across the cancellation surface (transcript ``InterruptEvent.source``,
per-event sentinels on cancelled in-flight events, etc.).
"""


@dataclass(frozen=True)
class UserMessage:
    """Operator-injected user turn (data plane).

    Appended to the consuming agent's conversation as a user message at
    the next drain boundary. Producers post these to redirect the agent
    cooperatively, without preempting in-flight work.
    """

    message: ChatMessageUser


@dataclass(frozen=True)
class Cancel:
    """Cancellation marker (control plane).

    Posted alongside the cancelling of the bound scope, so when the
    consumer's :exc:`AgentInterrupted` handler drains, it sees both
    the cancel marker (with reason) and any redirect ``UserMessage``
    a producer posted in the same gesture.
    """

    reason: CancelReason = "user_cancel"


ChannelItem = Union[UserMessage, Cancel]
"""Open union of channel item types.

Designed for extension: future items (``Announce``, ``Steer``) extend
the union without altering the channel core. Consumers narrow with
``isinstance`` and ignore items they don't recognize.
"""


_COALESCE_SEPARATOR = "\n\n"


def coalesce(
    items: Sequence[ChannelItem],
) -> list[ChatMessageUser]:
    r"""Extract :class:`UserMessage` items and coalesce consecutive operator sends.

    When an operator queues N sends while the agent is busy, the drained
    items would otherwise produce N consecutive :class:`ChatMessageUser`
    turns in ``state.messages``. The model then sees a degenerate
    conversation shape — multiple user turns before its next assistant
    turn — that providers handle inconsistently. Coalescing into one
    merged user message restores standard alternating user/assistant flow.

    Only operator-sourced consecutive messages are merged; any other
    source (or any non-operator message in the sequence) returns the
    sequence unchanged. Non-:class:`UserMessage` items in ``items`` are
    silently filtered out.

    Text-only fast path: join contents with ``\\n\\n``. Mixed-modal
    path: flatten into a single content list (string → leading
    :class:`ContentText` block; list contents contribute their items
    in arrival order).
    """
    msgs = [item.message for item in items if isinstance(item, UserMessage)]
    if len(msgs) <= 1:
        return msgs
    if not all(m.source == "operator" for m in msgs):
        return msgs
    if all(isinstance(m.content, str) for m in msgs):
        merged_text = _COALESCE_SEPARATOR.join(
            m.content for m in msgs if isinstance(m.content, str)
        )
        return [ChatMessageUser(content=merged_text, source="operator")]
    blocks: list[Content] = []
    for m in msgs:
        if isinstance(m.content, str):
            blocks.append(ContentText(text=m.content))
        else:
            blocks.extend(m.content)
    return [ChatMessageUser(content=blocks, source="operator")]
