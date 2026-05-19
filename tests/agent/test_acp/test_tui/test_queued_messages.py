"""Tests for the client-side queued-user-message ephemerals.

Covers the state-side mutations + single-bucket append-on-existing
semantics + the chip / body rendering on :class:`MessageWidget`. All
pure-function — no Pilot, no event loop. The send-path + transcript
interaction tests live in the Pilot suite.

The single-bucket design mirrors server-side
``_coalesce_operator_messages``: N queued sends drain as ONE merged
``ChatMessageUser``, so the visible row reflects exactly what the
model will see.
"""

from __future__ import annotations

from acp.schema import (
    AgentMessageChunk,
    SessionNotification,
    TextContentBlock,
    UserMessageChunk,
)

from inspect_ai.agent._acp.tui.state import (
    MessageGroup,
    SessionState,
)
from inspect_ai.agent._acp.tui.widgets.message import MessageWidget

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _operator_chunk(text: str, *, message_id: str = "srv-1") -> SessionNotification:
    """A server-echoed operator chunk.

    What the server emits when ``before_turn`` drains a queued
    ``submit_user_message`` (post-coalesce: at most one chunk per
    drained turn boundary).
    """
    chunk = UserMessageChunk(
        session_update="user_message_chunk",
        content=TextContentBlock(type="text", text=text),
        message_id=message_id,
        field_meta={"inspect.user_source": "operator"},
    )
    return SessionNotification(session_id="sid", update=chunk)


def _user_chunk(text: str, *, message_id: str = "srv-1") -> SessionNotification:
    """A non-operator user chunk (e.g. dataset input)."""
    chunk = UserMessageChunk(
        session_update="user_message_chunk",
        content=TextContentBlock(type="text", text=text),
        message_id=message_id,
        field_meta={"inspect.user_source": "input"},
    )
    return SessionNotification(session_id="sid", update=chunk)


def _queued(state: SessionState) -> list[MessageGroup]:
    return [
        item
        for item in state.items
        if isinstance(item, MessageGroup) and item.is_queued
    ]


def _pending_signal(message_id: str = "m1") -> SessionNotification:
    """Empty assistant chunk carrying the pending model-event meta flag."""
    chunk = AgentMessageChunk(
        session_update="agent_message_chunk",
        content=TextContentBlock(type="text", text=""),
        message_id=message_id,
        field_meta={
            "inspect.model": "phase2/model",
            "inspect.model_event_pending": True,
        },
    )
    return SessionNotification(session_id="sid", update=chunk)


def _agent_chunk(text: str, *, message_id: str = "m1") -> SessionNotification:
    chunk = AgentMessageChunk(
        session_update="agent_message_chunk",
        content=TextContentBlock(type="text", text=text),
        message_id=message_id,
        field_meta={"inspect.model": "phase2/model"},
    )
    return SessionNotification(session_id="sid", update=chunk)


# ---------------------------------------------------------------------------
# enqueue_queued_user_message — fresh creation
# ---------------------------------------------------------------------------


def test_enqueue_creates_fresh_queued_group_when_none_exists() -> None:
    state = SessionState()
    notified = 0

    def _cb() -> None:
        nonlocal notified
        notified += 1

    state.subscribe(_cb)

    handle = state.enqueue_queued_user_message("please check /var/log")

    assert handle.prior_text is None  # fresh creation marker
    group = handle.group
    assert group.is_queued is True
    assert group.role == "user"
    assert group.user_source == "operator"
    assert group.text == "please check /var/log"
    assert group.message_id.startswith("queued-")
    assert state.items[-1] is group
    assert notified == 1


# ---------------------------------------------------------------------------
# enqueue_queued_user_message — append-on-existing
# ---------------------------------------------------------------------------


def test_enqueue_appends_to_existing_with_paragraph_separator() -> None:
    r"""Subsequent sends-while-busy extend the existing ephemeral's text.

    Mirrors server-side ``_coalesce_operator_messages``: at most one
    queued group, joined with ``\n\n`` paragraph breaks. The visible
    row matches what the model will receive.
    """
    state = SessionState()
    state.enqueue_queued_user_message("first")
    state.enqueue_queued_user_message("second")
    state.enqueue_queued_user_message("third")

    queued = _queued(state)
    # Single bucket — only ONE queued group regardless of N enqueues.
    assert len(queued) == 1
    assert queued[0].text == "first\n\nsecond\n\nthird"
    assert queued[0].user_source == "operator"


def test_enqueue_returns_handle_with_prior_text_on_append() -> None:
    """The handle records the pre-append snapshot for precise undo."""
    state = SessionState()
    state.enqueue_queued_user_message("first")
    handle = state.enqueue_queued_user_message("second")

    assert handle.prior_text == "first"
    assert handle.group.text == "first\n\nsecond"


# ---------------------------------------------------------------------------
# undo_queued_enqueue
# ---------------------------------------------------------------------------


def test_undo_removes_group_entirely_on_fresh_creation_handle() -> None:
    """Undoing the FIRST enqueue removes the whole ephemeral."""
    state = SessionState()
    handle = state.enqueue_queued_user_message("doomed")
    assert handle.prior_text is None

    notified_after = 0

    def _cb() -> None:
        nonlocal notified_after
        notified_after += 1

    state.subscribe(_cb)
    state.undo_queued_enqueue(handle)

    assert _queued(state) == []
    assert notified_after == 1


def test_undo_restores_prior_text_on_append_handle() -> None:
    """Undoing a SUBSEQUENT enqueue restores the prior text in place.

    Earlier queued sends survive — the undo is precise to just the
    failed append. Critical for the rollback-on-send-failure path
    when the operator had queued multiple messages and one fails.
    """
    state = SessionState()
    first_handle = state.enqueue_queued_user_message("first")
    second_handle = state.enqueue_queued_user_message("second")

    state.undo_queued_enqueue(second_handle)

    queued = _queued(state)
    assert len(queued) == 1
    assert queued[0].text == "first"  # second's append rolled back
    assert queued[0] is first_handle.group  # same ephemeral, restored


def test_undo_is_idempotent_when_group_already_gone() -> None:
    """Replaying undo after the group is gone is a silent no-op.

    Lets send-failure rollback fire from a ``finally`` / except without
    branching on whether the chunk's pop has already cleared the group.
    """
    state = SessionState()
    handle = state.enqueue_queued_user_message("typo")
    state.undo_queued_enqueue(handle)

    notified = 0

    def _cb() -> None:
        nonlocal notified
        notified += 1

    state.subscribe(_cb)
    state.undo_queued_enqueue(handle)  # second call — already gone
    assert notified == 0


# ---------------------------------------------------------------------------
# Consumer pop on operator chunk arrival
# ---------------------------------------------------------------------------


def test_arriving_operator_chunk_pops_the_single_queued_ephemeral() -> None:
    """Server's drained chunk (coalesced into one) pops the single ephemeral."""
    state = SessionState()
    state.enqueue_queued_user_message("first")
    state.enqueue_queued_user_message("second")
    state.enqueue_queued_user_message("third")
    assert len(_queued(state)) == 1  # single-bucket invariant

    # Server drained all three into one ChatMessageUser, emits ONE chunk
    # (the merged text). The single queued ephemeral pops, the real
    # group renders in its place.
    state.consume(_operator_chunk("first\n\nsecond\n\nthird", message_id="srv-1"))

    assert _queued(state) == []
    server_groups = [
        item
        for item in state.items
        if isinstance(item, MessageGroup) and not item.is_queued
    ]
    assert len(server_groups) == 1
    assert server_groups[0].text == "first\n\nsecond\n\nthird"


def test_operator_chunk_with_no_queued_passes_through() -> None:
    """Operator chunk with no locally-queued ephemeral renders normally.

    Regression guard for the send-during-``idle`` path: no ephemeral
    was ever enqueued, the chunk arrives, and a regular user group
    appears with no side effects on the (empty) queued list.
    """
    state = SessionState()
    state.consume(_operator_chunk("hello"))
    assert _queued(state) == []
    server_groups = [item for item in state.items if isinstance(item, MessageGroup)]
    assert len(server_groups) == 1
    assert server_groups[0].is_queued is False
    assert server_groups[0].text == "hello"
    assert server_groups[0].user_source == "operator"


def test_non_operator_user_chunk_does_not_consume_queued() -> None:
    """Non-operator user chunks must not pop a queued ephemeral.

    Dataset-input user chunks are unrelated to a locally-queued
    operator draft, and a second connected client's chunk with a
    different source mustn't eat our display state either.
    """
    state = SessionState()
    handle = state.enqueue_queued_user_message("local draft")
    state.consume(_user_chunk("dataset prompt"))
    assert handle.group in state.items
    assert _queued(state) == [handle.group]


# ---------------------------------------------------------------------------
# mark_complete clears residual queued
# ---------------------------------------------------------------------------


def test_mark_complete_drops_any_remaining_queued_ephemerals() -> None:
    """``mark_complete`` clears any undrained ephemeral.

    Post-completion the transcript is read-only — leaving the dim row
    mounted would misrepresent never-delivered text as delivered. The
    drop happens in the same notify batch as the sticky-complete flip
    so subscribers see a single coherent transition into ``complete``.
    """
    state = SessionState()
    state.enqueue_queued_user_message("never gonna land")
    state.enqueue_queued_user_message("also never")
    assert len(_queued(state)) == 1  # single-bucket — both appended into one

    state.mark_complete()

    assert _queued(state) == []
    assert state.lifecycle == "complete"


# ---------------------------------------------------------------------------
# Lifecycle composition
# ---------------------------------------------------------------------------


def test_queued_ephemerals_do_not_register_in_message_index() -> None:
    """Queued ephemerals live only in ``items`` — not in the lookup indexes.

    If they registered in ``_messages_by_id`` / ``_pending_message_ids``
    the locally-minted ``queued-N`` ids would interact with
    server-driven aliasing (retry collapse / drop tombstones /
    turn-cap logic) and produce wrong-looking transcript state.
    """
    state = SessionState()
    handle = state.enqueue_queued_user_message("only in items, please")
    assert handle.group.message_id not in state._messages_by_id
    assert handle.group.message_id not in state._pending_message_ids


# ---------------------------------------------------------------------------
# MessageWidget chip rendering for queued groups
# ---------------------------------------------------------------------------


def _new_widget(group: MessageGroup) -> MessageWidget:
    """Build a MessageWidget without mounting it.

    ``_chip_text`` is a pure method that only reads ``self._group`` /
    ``self._current_model`` / ``self._spinner_frame`` — no DOM access
    is needed, so we can construct the widget standalone and call
    the method directly.
    """
    return MessageWidget(group, current_model=None)


def test_queued_chip_reads_user_dot_queued_with_no_operator_suffix() -> None:
    group = MessageGroup(
        message_id="queued-1",
        role="user",
        user_source="operator",
        is_queued=True,
    )
    chip = _new_widget(group)._chip_text()
    assert "user" in chip
    assert "queued" in chip
    # Critical regression guard: the normal ``user · operator`` chip
    # MUST NOT also appear — the queued state is the only label.
    assert "operator" not in chip


def test_non_queued_operator_group_still_reads_user_dot_operator() -> None:
    """Non-queued operator groups still render the canonical chip.

    Confirms the queued branch doesn't shadow the regular path that
    the post-swap real chunk takes.
    """
    group = MessageGroup(
        message_id="srv-1",
        role="user",
        user_source="operator",
        is_queued=False,
    )
    chip = _new_widget(group)._chip_text()
    assert "user" in chip
    assert "operator" in chip
    assert "queued" not in chip


def test_non_queued_input_user_group_still_reads_user_dot_input() -> None:
    """Regression guard for dataset-input user groups."""
    group = MessageGroup(
        message_id="srv-2",
        role="user",
        user_source="input",
        is_queued=False,
    )
    chip = _new_widget(group)._chip_text()
    assert "input" in chip
    assert "queued" not in chip


# ---------------------------------------------------------------------------
# Retry-collapse interaction with queued ephemerals
# ---------------------------------------------------------------------------


def test_retry_collapse_walks_past_queued_ephemeral() -> None:
    """A queued ephemeral between pending bubbles must not block retry collapse.

    Regression: when the operator queues a message between a failed
    first attempt's empty pending bubble and the retry's pending signal,
    ``items[-1]`` is the queued ephemeral. The original
    ``_should_retry_collapse`` predicate only inspected ``items[-1]``
    and returned False — the retry was treated as a fresh turn, the
    first attempt's id stayed in ``_pending_message_ids`` forever
    (no completion marker because the model's retry produced content
    under the SECOND id), and the lifecycle pill stuck on ``running``
    even after the retry succeeded.

    Fix walks ``items`` in reverse skipping queued ephemerals, so the
    retry collapses onto the empty assistant bubble as it would have
    without an operator interjection. After ``content m2`` lands the
    first attempt's id is gone from ``_pending_message_ids`` (so
    lifecycle can reach ``idle``) and the assistant group reports
    ``retries=1`` + non-empty text.
    """
    state = SessionState()
    # First attempt — empty pending bubble.
    state.consume(_pending_signal("m1"))
    assert "m1" in state._pending_message_ids
    # Operator queues a message while m1 is in flight.
    state.enqueue_queued_user_message("any update?")
    # Retry — second pending signal with a fresh id. Without the fix,
    # this would create a new assistant bubble (items[-1] was the
    # queued ephemeral, so collapse was skipped) AND leave m1 stuck
    # in _pending_message_ids forever (no completion marker would
    # ever clear it because the model's retry produced content under
    # m2's id).
    state.consume(_pending_signal("m2"))
    # The retry was routed through the alias map — m2 resolves to m1.
    assert state._message_id_aliases.get("m2") == "m1"
    # Exactly ONE assistant group exists (the collapsed m1 bubble),
    # not two — the queued ephemeral is the only other item.
    assistant_groups = [
        item
        for item in state.items
        if isinstance(item, MessageGroup)
        and not item.is_queued
        and item.role == "assistant"
    ]
    assert len(assistant_groups) == 1
    assert assistant_groups[0].message_id == "m1"
    assert assistant_groups[0].retries == 1
    # m2 must NOT be a separate pending id — the collapse aliased it
    # to m1, so the only pending entry is m1 itself (re-stamped by
    # ``_apply_pending_lifecycle`` on the collapsed group). Without
    # the fix, _pending would be {m1, m2} here and m2's later content
    # would clear m2 but leave m1 stuck forever.
    assert state._pending_message_ids == {"m1"}
    # m2's content lands on the collapsed group via the alias —
    # closes the pending window on m1.
    state.consume(_agent_chunk("retry result", message_id="m2"))
    assert assistant_groups[0].text == "retry result"
    assert assistant_groups[0].pending is False
    # _pending_message_ids fully drains — the bug scenario kept m1
    # stuck here forever, holding lifecycle on ``running``.
    assert state._pending_message_ids == set()
