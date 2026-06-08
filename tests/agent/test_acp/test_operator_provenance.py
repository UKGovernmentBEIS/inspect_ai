"""Operator-provenance restoration for bridged agents.

A bridged scaffold (claude_code, codex, …) round-trips operator
interventions through its own conversation store (e.g. Claude Code's
``--resume``), so an operator message re-enters the bridge as a plain
``ChatMessageUser`` (``source=None``) — losing the ``"operator"``
provenance the ACP transport stamped at submit time. The single
``bridge_generate`` chokepoint restores it so the source survives in BOTH
the recorded ``ModelEvent`` input and the final ``state.messages`` — for
every bridged agent, regardless of its live consumption technique.

Recognition is scoped, not a global ledger: the transport holds only
submitted-but-not-yet-seen operator messages (consumed on first match),
and thereafter provenance is carried forward from the bridge's own tracked
conversation (``bridge.state.messages``).
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
from inspect_ai.model import ChatMessageSystem, ChatMessageUser, get_model
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput


def _bridge(*messages: ChatMessageUser) -> AgentBridge:
    return AgentBridge(AgentState(messages=list(messages)))


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
# Transport pending set (consume-on-match)
# ---------------------------------------------------------------------------


def test_consume_operator_message_is_one_shot_and_normalized() -> None:
    transport = LiveAcpTransport()
    transport.submit_user_message(ChatMessageUser(content="let's continue working"))
    # whitespace-normalized match
    assert transport.consume_operator_message(
        ChatMessageUser(content="\n  let's continue working  \n")
    )
    # one-shot: the entry was popped, so a second match fails
    assert not transport.consume_operator_message(
        ChatMessageUser(content="let's continue working")
    )


def test_consume_operator_message_no_match() -> None:
    transport = LiveAcpTransport()
    transport.submit_user_message(ChatMessageUser(content="alpha"))
    assert not transport.consume_operator_message(ChatMessageUser(content="beta"))


def test_consume_operator_message_matches_multiblock_round_trip() -> None:
    # The pending set holds the SHORT submitted text; Claude Code re-emits the
    # turn as multiple blocks (reminder/skills + the operator text as its own
    # block). The concatenated ``.text`` won't match, but the per-block
    # candidate does.
    transport = LiveAcpTransport()
    transport.submit_user_message(ChatMessageUser(content="let's continue working"))
    round_tripped = _cc_user(_REMINDER, "let's continue working")
    assert round_tripped.text.strip() != "let's continue working"  # sanity
    assert transport.consume_operator_message(round_tripped)
    # one-shot: the matched candidate was popped
    assert not transport.consume_operator_message(
        _cc_user(_REMINDER, "let's continue working")
    )


def test_noop_transport_never_consumes_operator_message() -> None:
    assert (
        NoOpAcpTransport().consume_operator_message(ChatMessageUser(content="anything"))
        is False
    )


# ---------------------------------------------------------------------------
# _restore_operator_message_source (the bridge helper)
# ---------------------------------------------------------------------------


def test_restore_recognizes_pending_message_first_time() -> None:
    transport = LiveAcpTransport()
    transport.submit_user_message(ChatMessageUser(content="let's continue working"))
    token = _acp_var.set(transport)
    try:
        dataset = ChatMessageUser(content="solve the task")
        # round-tripped operator message: source lost, leading newline added
        redirect = ChatMessageUser(content="\nlet's continue working")
        system = ChatMessageSystem(content="let's continue working")  # not a user msg
        _restore_operator_message_source(_bridge(), [dataset, redirect, system])

        assert redirect.source == "operator"  # recognized via pending set
        assert dataset.source is None  # non-operator user message untouched
        assert system.source is None  # system messages are never stamped
    finally:
        _acp_var.reset(token)


def test_restore_recognizes_multiblock_pending_first_time() -> None:
    # A multi-block redirect (operator text as a non-first block) is recognized
    # via the pending set; a sibling dataset message that shares the SAME
    # reminder block must NOT be stamped (the pending set only holds operator
    # texts, never reminders, so per-block matching is safe here).
    transport = LiveAcpTransport()
    transport.submit_user_message(ChatMessageUser(content="let's continue working"))
    token = _acp_var.set(transport)
    try:
        redirect = _cc_user(_REMINDER, "let's continue working")
        dataset = _cc_user(_REMINDER, "solve the original task")  # shares reminder
        _restore_operator_message_source(_bridge(), [dataset, redirect])
        assert redirect.source == "operator"
        assert dataset.source is None
    finally:
        _acp_var.reset(token)


def test_restore_carry_forward_multiblock_no_reminder_false_positive() -> None:
    # No pending entry (already consumed on a prior turn). Carry-forward matches
    # the FULL ``.text`` of a prior operator message — Claude Code keeps a user
    # turn's representation stable once it is history, so the same operator
    # message re-enters with an identical whole text. A dataset message that
    # shares only the reminder block must NOT be falsely stamped operator.
    transport = LiveAcpTransport()
    token = _acp_var.set(transport)
    try:
        prior = _cc_user(_REMINDER, "let's continue working", source="operator")
        this_turn = _cc_user(_REMINDER, "let's continue working")  # same whole text
        dataset = _cc_user(_REMINDER, "solve the original task")  # shares reminder
        _restore_operator_message_source(_bridge(prior), [dataset, this_turn])
        assert this_turn.source == "operator"
        assert dataset.source is None
    finally:
        _acp_var.reset(token)


def test_restore_carries_forward_from_bridge_state() -> None:
    # No pending transport entry (already consumed on a prior turn); the
    # operator message is recognized purely from the tracked conversation.
    transport = LiveAcpTransport()
    token = _acp_var.set(transport)
    try:
        prior = ChatMessageUser(content="let's continue working", source="operator")
        # fresh same-text message rebuilt by the bridge this turn (source lost)
        this_turn = ChatMessageUser(content="let's continue working")
        _restore_operator_message_source(_bridge(prior), [this_turn])
        assert this_turn.source == "operator"
    finally:
        _acp_var.reset(token)


def test_restore_is_noop_without_active_transport() -> None:
    # No ACP transport installed → current_acp_transport() is the no-op
    # singleton → nothing is stamped (graceful no-op for non-ACP evals).
    assert isinstance(current_acp_transport(), NoOpAcpTransport)
    msg = ChatMessageUser(content="let's continue working")
    _restore_operator_message_source(_bridge(), [msg])
    assert msg.source is None


def test_restore_does_not_downgrade_existing_operator_source() -> None:
    transport = LiveAcpTransport()
    token = _acp_var.set(transport)
    try:
        msg = ChatMessageUser(content="hi", source="operator")
        _restore_operator_message_source(_bridge(), [msg])
        assert msg.source == "operator"
    finally:
        _acp_var.reset(token)


# ---------------------------------------------------------------------------
# Integration: bridge_generate restores provenance end to end
# ---------------------------------------------------------------------------


@skip_if_trio
@pytest.mark.anyio
async def test_bridge_generate_restores_operator_source() -> None:
    """The restore runs inside the shared ``bridge_generate`` chokepoint.

    Proves the wiring: an operator message submitted to the transport, then
    re-entering ``bridge_generate`` as a plain (source-less) user message, is
    re-stamped ``operator`` in place — so the same object the caller records
    as the ``ModelEvent`` input and tracks into ``state.messages`` carries
    the restored source.
    """
    tr = Transcript()
    tok_tr = _transcript.set(tr)
    transport = LiveAcpTransport()
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
        redirect = ChatMessageUser(content="\nlet's continue working")
        input_messages = [ChatMessageUser(content="solve the task"), redirect]
        await bridge_generate(bridge, model, input_messages, [], None, GenerateConfig())
        assert redirect.source == "operator"
        assert input_messages[0].source is None
    finally:
        _acp_var.reset(tok_acp)
        _transcript.reset(tok_tr)
