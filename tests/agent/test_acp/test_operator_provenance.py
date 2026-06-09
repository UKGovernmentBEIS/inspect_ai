"""Operator-provenance restoration for bridged agents.

A bridged scaffold (claude_code, codex, …) round-trips operator interventions
through its own conversation store, so an operator message re-enters the bridge as
a plain ``ChatMessageUser`` (``source=None``) — losing the ``"operator"``
provenance the ACP transport stamped at submit time. The ``bridge_generate``
chokepoint restores it so the source survives in the recorded ``ModelEvent`` input
and the final ``state.messages`` (the eval log, which scorers also read), and the
ACP TUI renders it distinctly.

The signal lives entirely on the ``bridge`` object — the only thing reliably
threaded into ``bridge_generate`` for both in-process and sandbox bridges. The
scaffold calls ``bridge.note_operator_message`` when it injects an operator
message; recognition is positional (the operator is the latest user message) and
carry-forward re-stamps it on later turns by the bridge's stable content key.
"""

from __future__ import annotations

import pytest
from test_helpers.utils import skip_if_trio

from inspect_ai._util.content import ContentText
from inspect_ai.agent import AgentState
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import (
    _restore_operator_message_source,
    bridge_generate,
)
from inspect_ai.log._transcript import Transcript, _transcript
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    get_model,
)
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput


def _bridge() -> AgentBridge:
    return AgentBridge(AgentState(messages=[]))


def _cc_user(*texts: str, source: str | None = None) -> ChatMessageUser:
    """A Claude Code-style multi-block user message (reminder/skills + prompt)."""
    return ChatMessageUser(
        content=[ContentText(text=text) for text in texts],
        source=source,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# note_operator_message — the scaffold's signal
# ---------------------------------------------------------------------------


def test_note_operator_message_increments_pending() -> None:
    bridge = _bridge()
    assert bridge._pending_operator == 0
    bridge.note_operator_message(ChatMessageUser(content="first"))
    assert bridge._pending_operator == 1
    bridge.note_operator_message(ChatMessageUser(content="second"))
    assert bridge._pending_operator == 2


# ---------------------------------------------------------------------------
# _restore_operator_message_source — first recognition (positional + pending)
# ---------------------------------------------------------------------------


def test_restore_stamps_latest_user_when_pending() -> None:
    bridge = _bridge()
    bridge.note_operator_message(ChatMessageUser(content="let's continue working"))
    task = ChatMessageUser(content="solve the task")
    operator = ChatMessageUser(content="let's continue working")
    input: list[ChatMessage] = [task, ChatMessageAssistant(content="..."), operator]
    _restore_operator_message_source(bridge, input)

    assert operator.source == "operator"  # latest user message, pending > 0
    assert task.source is None  # the task sits behind an assistant turn
    assert bridge._pending_operator == 0  # consumed
    assert bridge._operator_keys  # key recorded for carry-forward


def test_restore_stamps_multiblock_operator() -> None:
    # The re-emitted operator arrives as multiple ContentText blocks (reminder /
    # skills + prompt). Recognized purely positionally — no content matching.
    bridge = _bridge()
    bridge.note_operator_message(ChatMessageUser(content="let's continue working"))
    task = ChatMessageUser(content="solve the task")
    redirect = _cc_user("<system-reminder>...</system-reminder>", "let's continue")
    input: list[ChatMessage] = [task, ChatMessageAssistant(content="..."), redirect]
    _restore_operator_message_source(bridge, input)

    assert redirect.source == "operator"
    assert task.source is None


def test_restore_tool_messages_skipped() -> None:
    # Tool results are ChatMessageTool, not ChatMessageUser; the latest USER
    # message (the operator) is stamped even with tool results after the assistant.
    bridge = _bridge()
    bridge.note_operator_message(ChatMessageUser(content="continue"))
    task = ChatMessageUser(content="solve the task")
    tool = ChatMessageTool(content="tool output", tool_call_id="t1")
    operator = ChatMessageUser(content="continue")
    input: list[ChatMessage] = [
        task,
        ChatMessageAssistant(content="calling tool"),
        tool,
        operator,
    ]
    _restore_operator_message_source(bridge, input)

    assert operator.source == "operator"
    assert task.source is None


def test_restore_coalesced_operator_stamped() -> None:
    # Several queued sends coalesce into one "a\n\nb" turn; the bridge stamps the
    # single arrived message and consumes ALL pending.
    bridge = _bridge()
    bridge.note_operator_message(ChatMessageUser(content="first"))
    bridge.note_operator_message(ChatMessageUser(content="second"))
    task = ChatMessageUser(content="solve the task")
    coalesced = ChatMessageUser(content="first\n\nsecond")
    input: list[ChatMessage] = [task, ChatMessageAssistant(content="..."), coalesced]
    _restore_operator_message_source(bridge, input)

    assert coalesced.source == "operator"
    assert task.source is None
    assert bridge._pending_operator == 0


def test_restore_already_operator_latest_does_not_overstamp_task() -> None:
    # If the latest user message is already operator (e.g. carry-forward stamped a
    # re-sent identical message, or a source-preserving bridge), first recognition
    # must NOT fall through and stamp the earlier task.
    bridge = _bridge()
    bridge.note_operator_message(ChatMessageUser(content="hi"))
    task = ChatMessageUser(content="solve the task")
    operator = ChatMessageUser(content="hi", source="operator")
    input: list[ChatMessage] = [task, ChatMessageAssistant(content="..."), operator]
    _restore_operator_message_source(bridge, input)

    assert operator.source == "operator"
    assert task.source is None
    assert bridge._pending_operator == 0


# ---------------------------------------------------------------------------
# _restore_operator_message_source — the pending gate (nothing stamped at 0)
# ---------------------------------------------------------------------------


def test_restore_no_stamp_without_pending() -> None:
    bridge = _bridge()  # no note_operator_message
    task = ChatMessageUser(content="solve the task")
    newish = ChatMessageUser(content="a fresh user message")
    input: list[ChatMessage] = [task, ChatMessageAssistant(content="..."), newish]
    _restore_operator_message_source(bridge, input)

    assert newish.source is None
    assert task.source is None


def test_restore_multi_message_history_not_stamped() -> None:
    # Robustness for non-claude_code / history-taking bridges: an ordinary
    # multi-message conversation (ending in a user turn) with no operator pending
    # is left entirely untouched.
    bridge = _bridge()
    user_a = ChatMessageUser(content="first user turn")
    user_b = ChatMessageUser(content="second user turn")
    input: list[ChatMessage] = [user_a, ChatMessageAssistant(content="..."), user_b]
    _restore_operator_message_source(bridge, input)

    assert user_a.source is None
    assert user_b.source is None


def test_restore_noop_when_no_operator_ever() -> None:
    # No pending and no recorded keys → restore touches nothing.
    bridge = _bridge()
    msg = ChatMessageUser(content="hello")
    _restore_operator_message_source(bridge, [msg])
    assert msg.source is None
    assert bridge._operator_keys == set()


# ---------------------------------------------------------------------------
# _restore_operator_message_source — carry-forward (re-recognition / log)
# ---------------------------------------------------------------------------


def test_restore_carries_forward_on_later_turn_without_pending() -> None:
    # First turn records the operator key; a LATER turn re-presents the same
    # operator message mid-history as source=None with NO pending — carry-forward
    # re-stamps it by key (so the source persists into that turn's ModelEvent /
    # state.messages → the log).
    bridge = _bridge()
    bridge.note_operator_message(ChatMessageUser(content="redirect"))

    # turn 1: operator arrives at the tail and is recognized
    operator_t1 = ChatMessageUser(content="redirect")
    _restore_operator_message_source(
        bridge, [ChatMessageUser(content="task"), operator_t1]
    )
    assert operator_t1.source == "operator"

    # turn 2: a fresh (source=None) copy mid-history, no pending submission
    operator_t2 = ChatMessageUser(content="redirect")
    input_t2: list[ChatMessage] = [
        ChatMessageUser(content="task"),
        ChatMessageAssistant(content="..."),
        operator_t2,
        ChatMessageAssistant(content="more"),
    ]
    _restore_operator_message_source(bridge, input_t2)
    assert operator_t2.source == "operator"  # carry-forward by key


def test_restore_carry_forward_does_not_touch_other_users() -> None:
    # Carry-forward only re-stamps the recorded operator key, not other user turns.
    bridge = _bridge()
    bridge.note_operator_message(ChatMessageUser(content="redirect"))
    _restore_operator_message_source(
        bridge, [ChatMessageUser(content="task"), ChatMessageUser(content="redirect")]
    )

    other = ChatMessageUser(content="a different user message")
    op_copy = ChatMessageUser(content="redirect")
    input2: list[ChatMessage] = [
        ChatMessageUser(content="task"),
        other,
        op_copy,
    ]
    _restore_operator_message_source(bridge, input2)
    assert op_copy.source == "operator"
    assert other.source is None


# ---------------------------------------------------------------------------
# Integration: bridge_generate + _track_state (the log path)
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_bridge_generate_restores_into_state_messages() -> None:
    """note_operator_message → bridge_generate stamps in place → _track_state.

    Proves source lands in BOTH the input list (which the ModelEvent records) and
    bridge.state.messages (which becomes the sample conversation in the log).
    """
    tr = Transcript()
    tok = _transcript.set(tr)
    try:
        model = get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.from_content(model="mockllm/model", content="ok")
            ],
        )
        bridge = AgentBridge(AgentState(messages=[]))
        bridge.note_operator_message(ChatMessageUser(content="let's continue working"))

        task = ChatMessageUser(content="solve the task")
        operator = ChatMessageUser(content="let's continue working")
        messages: list[ChatMessage] = [
            task,
            ChatMessageAssistant(content="working"),
            operator,
        ]
        output, _ = await bridge_generate(
            bridge, model, messages, [], None, GenerateConfig()
        )
        bridge._track_state(messages, output)  # mirrors completions.py:97

        assert operator.source == "operator"
        assert task.source is None
        assert bridge._pending_operator == 0
        # state.messages (→ sample.messages in the log) carries the stamped operator
        state_users = [
            m for m in bridge.state.messages if isinstance(m, ChatMessageUser)
        ]
        assert any(m.source == "operator" for m in state_users)
        assert any(m.source is None for m in state_users)
    finally:
        _transcript.reset(tok)


@skip_if_trio
@pytest.mark.anyio
async def test_bridge_generate_carry_forward_into_state_on_later_turn() -> None:
    """A later (larger) turn carries the operator source into state.messages.

    The operator was recognized on turn 1; on turn 2 it re-enters source=None with
    no pending submission, and carry-forward re-stamps it so the FINAL logged
    conversation (state.messages, taken from the larger turn) shows source=operator.
    """
    tr = Transcript()
    tok = _transcript.set(tr)
    try:
        model = get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.from_content(model="mockllm/model", content="ok"),
                ModelOutput.from_content(model="mockllm/model", content="ok2"),
            ],
        )
        bridge = AgentBridge(AgentState(messages=[]))
        bridge.note_operator_message(ChatMessageUser(content="redirect"))

        # turn 1 (first recognition)
        t1: list[ChatMessage] = [
            ChatMessageUser(content="task"),
            ChatMessageAssistant(content="a"),
            ChatMessageUser(content="redirect"),
        ]
        out1, _ = await bridge_generate(bridge, model, t1, [], None, GenerateConfig())
        bridge._track_state(t1, out1)

        # turn 2: larger, operator mid-history, source-less, NO pending
        operator_t2 = ChatMessageUser(content="redirect")
        t2: list[ChatMessage] = [
            ChatMessageUser(content="task"),
            ChatMessageAssistant(content="a"),
            operator_t2,
            ChatMessageAssistant(content="b"),
        ]
        out2, _ = await bridge_generate(bridge, model, t2, [], None, GenerateConfig())
        bridge._track_state(t2, out2)

        assert operator_t2.source == "operator"  # carry-forward
        # state.messages updated to the larger turn 2 and carries the operator
        assert any(
            isinstance(m, ChatMessageUser) and m.source == "operator"
            for m in bridge.state.messages
        )
    finally:
        _transcript.reset(tok)
