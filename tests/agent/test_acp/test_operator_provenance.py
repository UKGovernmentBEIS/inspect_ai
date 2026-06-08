"""Operator-provenance restoration for bridged agents.

A bridged scaffold (claude_code, codex, …) round-trips operator
interventions through its own conversation store (e.g. Claude Code's
``--resume``), so an operator message re-enters the bridge as a plain
``ChatMessageUser`` (``source=None``) — losing the ``"operator"``
provenance the ACP transport stamped at submit time. The single
``bridge_generate`` chokepoint restores it so the source survives in the
recorded ``ModelEvent`` input (and thus the final ``state.messages``).

Recognition is positional, gated on transport ground truth. The transport's
pending-operator COUNT is the one thing known for certain — operator messages
enter via the ACP channel, so a positive count means an operator was actually
submitted and (by the time the scaffold calls back) resumed into the input.
When the count is positive the operator turn is the LATEST user message
(queued submits coalesce into one), so it is stamped and all pending consumed;
when the count is 0 nothing is stamped, leaving the task and a history-taking
bridge's ordinary multi-message input untouched. The restore is NOT repeated
on later turns: the ACP TUI latches a message's operator provenance on first
sight (stable content-hash id + per-id input dedup + first-chunk-wins), so a
single stamp suffices.
"""

from __future__ import annotations

import pytest
from test_helpers.utils import skip_if_trio

from inspect_ai._util.content import ContentText
from inspect_ai.agent import AgentState
from inspect_ai.agent._acp.transport import _acp_var, current_acp_transport
from inspect_ai.agent._acp.transport_live import LiveAcpTransport
from inspect_ai.agent._acp.transport_noop import NoOpAcpTransport
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import (
    _restore_operator_message_source,
    bridge_generate,
)
from inspect_ai.log._transcript import Transcript, _transcript
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    get_model,
)
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput


class _FakeRef:
    """Minimal channel-producer sink so ``submit_user_message`` records pending.

    A real ``submit_user_message`` only counts a submission once it is posted
    to a bound channel; tests that need a pending count therefore attach this
    stand-in via :func:`_live`.
    """

    def post(self, item: object) -> None:
        pass


def _live() -> LiveAcpTransport:
    """A LiveAcpTransport with a bound channel sink (so submits accrue pending)."""
    transport = LiveAcpTransport()
    transport._ref = _FakeRef()  # type: ignore[assignment]
    return transport


def _cc_user(*texts: str, source: str | None = None) -> ChatMessageUser:
    """A Claude Code-style multi-block user message.

    Claude Code returns a user turn as multiple ``ContentText`` blocks —
    ``<system-reminder>`` / skills content as their own blocks alongside the
    actual prompt text as a separate block — so the concatenated ``.text``
    never equals any single block's text.
    """
    return ChatMessageUser(
        content=[ContentText(text=text) for text in texts],
        source=source,  # type: ignore[arg-type]
    )


_REMINDER = (
    "<system-reminder>\nThe following skills are available...\n</system-reminder>"
)


# ---------------------------------------------------------------------------
# Transport pending-operator count
# ---------------------------------------------------------------------------


def test_submit_user_message_increments_pending_operator_count() -> None:
    transport = _live()
    assert transport.pending_operator_count == 0
    transport.submit_user_message(ChatMessageUser(content="first"))
    assert transport.pending_operator_count == 1
    transport.submit_user_message(ChatMessageUser(content="second"))
    assert transport.pending_operator_count == 2


def test_submit_without_bound_channel_does_not_count() -> None:
    # A message dropped for lack of a bound channel never round-trips through a
    # bridge, so it must NOT leave a phantom pending count.
    transport = LiveAcpTransport()  # no _ref bound
    transport.submit_user_message(ChatMessageUser(content="dropped"))
    assert transport.pending_operator_count == 0


def test_clear_pending_operators_zeroes_count() -> None:
    transport = _live()
    transport.submit_user_message(ChatMessageUser(content="first"))
    assert transport.pending_operator_count == 1
    transport.clear_pending_operators()
    assert transport.pending_operator_count == 0


def test_pending_count_cleared_on_unbind() -> None:
    # A posted submission's pending count must not survive a consumer handoff:
    # unbind() resets it so a successor (e.g. bridged) consumer bound in the
    # same sample starts clean and can't be mis-stamped by a stale count.
    transport = _live()
    ref = transport._ref
    transport.submit_user_message(ChatMessageUser(content="op"))
    assert transport.pending_operator_count == 1
    transport.unbind(ref)  # type: ignore[arg-type]
    assert transport.pending_operator_count == 0


def test_noop_transport_pending_operator_count_is_zero() -> None:
    transport = NoOpAcpTransport()
    transport.submit_user_message(ChatMessageUser(content="anything"))
    assert transport.pending_operator_count == 0
    transport.clear_pending_operators()  # no-op, must not raise
    assert transport.pending_operator_count == 0


# ---------------------------------------------------------------------------
# _restore_operator_message_source — stamping when an operator is pending
# ---------------------------------------------------------------------------


def test_restore_stamps_last_user_when_pending() -> None:
    transport = _live()
    transport.submit_user_message(ChatMessageUser(content="let's continue working"))
    token = _acp_var.set(transport)
    try:
        task = ChatMessageUser(content="solve the task")
        operator = ChatMessageUser(content="let's continue working")
        input: list[ChatMessage] = [task, ChatMessageAssistant(content="..."), operator]
        _restore_operator_message_source(input)

        assert operator.source == "operator"  # latest user message, pending > 0
        assert task.source is None  # the task sits behind an assistant turn
        assert transport.pending_operator_count == 0  # consumed
    finally:
        _acp_var.reset(token)


def test_restore_stamps_multiblock_operator() -> None:
    # A round-tripped operator message arrives as multiple ContentText blocks
    # (reminder / skills + prompt). It is still recognized purely positionally
    # (latest user message + pending) — no content matching of any kind.
    transport = _live()
    transport.submit_user_message(ChatMessageUser(content="let's continue working"))
    token = _acp_var.set(transport)
    try:
        task = ChatMessageUser(content="solve the task")
        redirect = _cc_user(_REMINDER, "let's continue working")
        system = ChatMessageSystem(content="system prompt")
        input: list[ChatMessage] = [system, task, redirect]
        _restore_operator_message_source(input)

        assert redirect.source == "operator"
        assert task.source is None
        assert system.source is None
    finally:
        _acp_var.reset(token)


def test_restore_operator_text_colliding_with_task_is_irrelevant() -> None:
    # Positional stamping does not look at content, so an operator whose text
    # happens to equal the task's is still correctly identified as the latest
    # user message; the earlier (same-text) task is left untouched.
    transport = _live()
    transport.submit_user_message(ChatMessageUser(content="repeat"))
    token = _acp_var.set(transport)
    try:
        input_task = ChatMessageUser(content="repeat")  # earlier turn
        operator = ChatMessageUser(content="repeat")  # operator, same text, latest
        input: list[ChatMessage] = [
            input_task,
            ChatMessageAssistant(content="..."),
            operator,
        ]
        _restore_operator_message_source(input)

        assert operator.source == "operator"
        assert input_task.source is None
        assert transport.pending_operator_count == 0
    finally:
        _acp_var.reset(token)


def test_restore_coalesced_operator_stamped() -> None:
    # Several queued sends coalesce into one "first\n\nsecond" turn; the bridge
    # stamps the single arrived message and consumes ALL pending.
    transport = _live()
    transport.submit_user_message(ChatMessageUser(content="first"))
    transport.submit_user_message(ChatMessageUser(content="second"))
    token = _acp_var.set(transport)
    try:
        task = ChatMessageUser(content="solve the task")
        coalesced = ChatMessageUser(content="first\n\nsecond")
        input: list[ChatMessage] = [
            task,
            ChatMessageAssistant(content="..."),
            coalesced,
        ]
        _restore_operator_message_source(input)

        assert coalesced.source == "operator"
        assert task.source is None
        assert transport.pending_operator_count == 0
    finally:
        _acp_var.reset(token)


def test_restore_tool_messages_skipped() -> None:
    # Tool results are ChatMessageTool, not ChatMessageUser; the latest USER
    # message (the operator) is stamped even when tool results sit between it
    # and the preceding assistant turn.
    transport = _live()
    transport.submit_user_message(ChatMessageUser(content="let's continue working"))
    token = _acp_var.set(transport)
    try:
        task = ChatMessageUser(content="solve the task")
        tool = ChatMessageTool(content="tool output", tool_call_id="t1")
        operator = ChatMessageUser(content="let's continue working")
        input: list[ChatMessage] = [
            task,
            ChatMessageAssistant(content="calling tool"),
            tool,
            operator,
        ]
        _restore_operator_message_source(input)

        assert operator.source == "operator"
        assert task.source is None
    finally:
        _acp_var.reset(token)


def test_restore_does_not_downgrade_existing_operator_source() -> None:
    # Stamping the latest user message is a no-op when it is already operator.
    transport = _live()
    transport.submit_user_message(ChatMessageUser(content="hi"))
    token = _acp_var.set(transport)
    try:
        task = ChatMessageUser(content="solve the task")
        operator = ChatMessageUser(content="hi", source="operator")
        input: list[ChatMessage] = [task, ChatMessageAssistant(content="..."), operator]
        _restore_operator_message_source(input)

        assert operator.source == "operator"
        assert task.source is None  # not stamped via fall-through
        assert transport.pending_operator_count == 0
    finally:
        _acp_var.reset(token)


# ---------------------------------------------------------------------------
# _restore_operator_message_source — the pending gate (nothing stamped at 0)
# ---------------------------------------------------------------------------


def test_restore_no_stamp_without_pending() -> None:
    # No operator submission is pending → the latest user message is NOT stamped
    # (the count gates recognition).
    transport = _live()
    token = _acp_var.set(transport)
    try:
        task = ChatMessageUser(content="solve the task")
        newish = ChatMessageUser(content="a fresh user message")
        input: list[ChatMessage] = [task, ChatMessageAssistant(content="..."), newish]
        _restore_operator_message_source(input)

        assert newish.source is None
        assert task.source is None
    finally:
        _acp_var.reset(token)


def test_restore_multi_message_history_not_stamped() -> None:
    # Key robustness case for non-claude_code / history-taking bridges: an
    # ordinary multi-message conversation input (ending in a user turn) with no
    # operator pending must be left entirely untouched.
    transport = _live()
    token = _acp_var.set(transport)
    try:
        user_a = ChatMessageUser(content="first user turn")
        user_b = ChatMessageUser(content="second user turn")
        input: list[ChatMessage] = [
            user_a,
            ChatMessageAssistant(content="..."),
            user_b,
        ]
        _restore_operator_message_source(input)

        assert user_a.source is None
        assert user_b.source is None
    finally:
        _acp_var.reset(token)


def test_restore_does_not_stamp_task_from_unposted_submission() -> None:
    # Reviewer probe: a submission dropped for lack of a channel must not leave
    # a pending count that later marks an unrelated bridged task as operator.
    transport = LiveAcpTransport()  # no _ref bound → submit is dropped, no count
    transport.submit_user_message(ChatMessageUser(content="op"))
    token = _acp_var.set(transport)
    try:
        task = ChatMessageUser(content="solve the task")
        _restore_operator_message_source([task])
        assert task.source is None
        assert transport.pending_operator_count == 0
    finally:
        _acp_var.reset(token)


# ---------------------------------------------------------------------------
# _restore_operator_message_source — compaction summary safety
# ---------------------------------------------------------------------------


def test_restore_compaction_summary_not_stamped_without_pending() -> None:
    # A scaffold auto-compaction summary arrives as a synthetic user message
    # with no operator submission pending → never stamped.
    transport = _live()
    token = _acp_var.set(transport)
    try:
        summary = ChatMessageUser(content="[CONTEXT COMPACTION SUMMARY] ...")
        input: list[ChatMessage] = [summary, ChatMessageAssistant(content="...")]
        _restore_operator_message_source(input)
        assert summary.source is None
    finally:
        _acp_var.reset(token)


def test_restore_compaction_summary_spared_when_operator_follows() -> None:
    # Post-compaction shape [summary, operator] with a pending submission: the
    # operator is the LATEST user message and gets stamped; the summary (ahead
    # of it) is spared.
    transport = _live()
    transport.submit_user_message(ChatMessageUser(content="please refocus"))
    token = _acp_var.set(transport)
    try:
        summary = ChatMessageUser(content="[CONTEXT COMPACTION SUMMARY] ...")
        operator = ChatMessageUser(content="please refocus")
        input: list[ChatMessage] = [summary, operator]
        _restore_operator_message_source(input)

        assert operator.source == "operator"
        assert summary.source is None
        assert transport.pending_operator_count == 0
    finally:
        _acp_var.reset(token)


# ---------------------------------------------------------------------------
# _restore_operator_message_source — ACP-session gate
# ---------------------------------------------------------------------------


def test_restore_is_noop_without_active_transport() -> None:
    # No ACP transport installed → current_acp_transport() is the no-op
    # singleton → nothing is stamped (graceful no-op for non-ACP evals).
    assert isinstance(current_acp_transport(), NoOpAcpTransport)
    msg = ChatMessageUser(content="let's continue working")
    _restore_operator_message_source([msg])
    assert msg.source is None


def test_restore_skips_when_noop_even_with_subsequent_users() -> None:
    # Even a multi-user input is left untouched outside an ACP session.
    assert isinstance(current_acp_transport(), NoOpAcpTransport)
    task = ChatMessageUser(content="solve the task")
    op = ChatMessageUser(content="follow-up")
    input: list[ChatMessage] = [task, ChatMessageAssistant(content="..."), op]
    _restore_operator_message_source(input)
    assert task.source is None
    assert op.source is None


# ---------------------------------------------------------------------------
# Integration: bridge_generate restores provenance end to end
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_bridge_generate_restores_operator_source() -> None:
    """The restore runs inside the shared ``bridge_generate`` chokepoint.

    Proves the wiring: an operator message submitted to the transport (bumping
    the pending count), then re-entering ``bridge_generate`` as a plain
    (source-less) user message, is re-stamped ``operator`` in place — so the
    same object the caller records as the ``ModelEvent`` input and tracks into
    ``state.messages`` carries the restored source.
    """
    tr = Transcript()
    tok_tr = _transcript.set(tr)
    transport = _live()
    transport.submit_user_message(ChatMessageUser(content="let's continue working"))
    tok_acp = _acp_var.set(transport)
    try:
        model = get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.from_content(model="mockllm/model", content="ok")
            ],
        )
        bridge = AgentBridge(AgentState(messages=[]))
        redirect = ChatMessageUser(content="let's continue working")
        input_messages: list[ChatMessage] = [
            ChatMessageUser(content="solve the task"),
            ChatMessageAssistant(content="working"),
            redirect,
        ]
        await bridge_generate(bridge, model, input_messages, [], None, GenerateConfig())
        assert redirect.source == "operator"
        assert input_messages[0].source is None
        assert transport.pending_operator_count == 0
    finally:
        _acp_var.reset(tok_acp)
        _transcript.reset(tok_tr)
