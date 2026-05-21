"""Tests for server-side coalescing of queued operator messages.

When the operator queues N sends while the agent is busy, the drained
list would otherwise produce N consecutive :class:`ChatMessageUser`
turns in ``state.messages`` — a degenerate conversation shape (models
expect alternating user/assistant). The drain coalesces N → 1 merged
message so every ACP client (Zed, TUI, anything else) sees a
well-formed conversation. See ``_coalesce_operator_messages`` in
``session_live.py``.
"""

from __future__ import annotations

from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.agent import acp_session
from inspect_ai.agent._acp.session_live import _coalesce_operator_messages
from inspect_ai.model._chat_message import ChatMessageTool, ChatMessageUser

# ---------------------------------------------------------------------------
# Pure helper — no session needed
# ---------------------------------------------------------------------------


def test_helper_passes_single_message_through_unchanged() -> None:
    """One queued message: no merge, no overhead — return identity-equal list."""
    msg = ChatMessageUser(content="hello", source="operator")
    result = _coalesce_operator_messages([msg])
    assert result == [msg]


def test_helper_passes_empty_list_through() -> None:
    """Defensive: empty drain returns empty list."""
    assert _coalesce_operator_messages([]) == []


def test_helper_merges_three_str_messages_with_paragraph_separator() -> None:
    r"""Text-only fast path: ``\n\n``-joined into a single ChatMessageUser."""
    messages = [
        ChatMessageUser(content="first", source="operator"),
        ChatMessageUser(content="second", source="operator"),
        ChatMessageUser(content="third", source="operator"),
    ]
    result = _coalesce_operator_messages(messages)
    assert len(result) == 1
    assert result[0].content == "first\n\nsecond\n\nthird"
    assert result[0].source == "operator"
    # Fresh id minted — not equal to any of the inputs.
    assert result[0].id not in {m.id for m in messages}


def test_helper_skips_coalesce_when_any_source_is_non_operator() -> None:
    """Defensive guard: mixed sources should not silently lose attribution.

    All :meth:`LiveAcpSession.submit_user_message` callers normalize
    ``source="operator"``, so this branch is theoretical for the
    queue — but if a caller ever feeds a non-operator message in,
    drop the merge rather than silently rewrite the conversation.
    """
    messages = [
        ChatMessageUser(content="op1", source="operator"),
        ChatMessageUser(content="dataset", source="input"),
    ]
    result = _coalesce_operator_messages(messages)
    assert result == messages


def test_helper_flattens_mixed_modal_into_content_list() -> None:
    """When any queued message has list-content, flatten all into one mixed list.

    String contents become a leading :class:`ContentText` block; list
    contents contribute their blocks in arrival order. Preserves images
    and other non-text blocks instead of silently dropping them.
    """
    image = ContentImage(image="data:image/png;base64,XXX")
    messages = [
        ChatMessageUser(content="please look at:", source="operator"),
        ChatMessageUser(
            content=[image, ContentText(text="caption")], source="operator"
        ),
        ChatMessageUser(content="also this", source="operator"),
    ]
    result = _coalesce_operator_messages(messages)
    assert len(result) == 1
    merged = result[0]
    assert merged.source == "operator"
    assert isinstance(merged.content, list)
    # Expected blocks in arrival order: text, image, text, text.
    assert len(merged.content) == 4
    assert isinstance(merged.content[0], ContentText)
    assert merged.content[0].text == "please look at:"
    assert merged.content[1] is image
    assert isinstance(merged.content[2], ContentText)
    assert merged.content[2].text == "caption"
    assert isinstance(merged.content[3], ContentText)
    assert merged.content[3].text == "also this"


def test_helper_flattens_when_only_message_is_multimodal_but_others_are_strings() -> (
    None
):
    """Branch coverage: one list-content msg flips the whole drain into list mode."""
    image = ContentImage(image="data:image/png;base64,YYY")
    messages = [
        ChatMessageUser(content="a", source="operator"),
        ChatMessageUser(content=[image], source="operator"),
    ]
    result = _coalesce_operator_messages(messages)
    assert len(result) == 1
    assert isinstance(result[0].content, list)
    assert isinstance(result[0].content[0], ContentText)
    assert result[0].content[0].text == "a"
    assert result[0].content[1] is image


# ---------------------------------------------------------------------------
# Integration through the live session — before_turn + after_cancel
# ---------------------------------------------------------------------------


async def test_before_turn_returns_single_message_when_multiple_queued() -> None:
    """End-to-end through the live queue: 3 sends → 1 drained merged msg."""
    async with acp_session() as acp:
        acp.submit_user_message(ChatMessageUser(content="first"))
        acp.submit_user_message(ChatMessageUser(content="second"))
        acp.submit_user_message(ChatMessageUser(content="third"))
        # ``messages`` is non-empty so before_turn doesn't block on the
        # initial-user-message gate; drains immediately.
        drained = await acp.before_turn([ChatMessageUser(content="kickoff")])
        assert len(drained) == 1
        assert drained[0].content == "first\n\nsecond\n\nthird"
        assert drained[0].source == "operator"


async def test_before_turn_passes_single_message_through_unchanged() -> None:
    """Common case: one queued send drains as a single message — no merge wrapper."""
    async with acp_session() as acp:
        acp.submit_user_message(ChatMessageUser(content="hello"))
        drained = await acp.before_turn([ChatMessageUser(content="kickoff")])
        assert len(drained) == 1
        assert drained[0].content == "hello"
        assert drained[0].source == "operator"


async def test_after_cancel_coalesces_drained_operator_messages_after_repairs() -> None:
    """``after_cancel`` returns ``[repair_tools..., merged_operator_msg]``.

    Repair tool messages stay separate (they're not operator-sourced);
    the operator drain is merged in place. Pins that the merge wrapper
    doesn't accidentally touch the repair half of the result.
    """
    async with acp_session() as acp:
        # Queue two operator messages then cancel; after_cancel drains.
        acp.submit_user_message(ChatMessageUser(content="resume one"))
        acp.submit_user_message(ChatMessageUser(content="resume two"))
        acp.cancel_current_turn()
        # No prior tool calls to repair — messages=[] keeps repair phase empty.
        drained = await acp.after_cancel(messages=[])
        # Filter to user messages — those are the ones that should be merged.
        user_msgs = [m for m in drained if isinstance(m, ChatMessageUser)]
        tool_msgs = [m for m in drained if isinstance(m, ChatMessageTool)]
        assert len(user_msgs) == 1
        assert user_msgs[0].content == "resume one\n\nresume two"
        assert user_msgs[0].source == "operator"
        # No repairs in this scenario.
        assert tool_msgs == []
