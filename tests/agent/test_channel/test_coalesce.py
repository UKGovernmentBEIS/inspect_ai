"""Tests for :func:`coalesce` channel helper.

When the operator queues N sends while the agent is busy, the drained
items would otherwise produce N consecutive :class:`ChatMessageUser`
turns in ``state.messages`` — a degenerate conversation shape (models
expect alternating user/assistant). The helper coalesces N → 1 merged
message so every producer (ACP, future operator consoles) sees a
well-formed conversation.
"""

from __future__ import annotations

from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.agent._channel import UserMessage
from inspect_ai.agent._channel.items import coalesce
from inspect_ai.model._chat_message import ChatMessageUser


def _wrap(*messages: ChatMessageUser) -> list[UserMessage]:
    return [UserMessage(message=m) for m in messages]


def test_passes_single_message_through_unchanged() -> None:
    """One queued message: no merge, no overhead — return identity-equal list."""
    msg = ChatMessageUser(content="hello", source="operator")
    result = coalesce(_wrap(msg))
    assert result == [msg]


def test_passes_empty_list_through() -> None:
    """Defensive: empty drain returns empty list."""
    assert coalesce([]) == []


def test_merges_three_str_messages_with_paragraph_separator() -> None:
    r"""Text-only fast path: ``\n\n``-joined into a single ChatMessageUser."""
    messages = [
        ChatMessageUser(content="first", source="operator"),
        ChatMessageUser(content="second", source="operator"),
        ChatMessageUser(content="third", source="operator"),
    ]
    result = coalesce(_wrap(*messages))
    assert len(result) == 1
    assert result[0].content == "first\n\nsecond\n\nthird"
    assert result[0].source == "operator"
    # Fresh id minted — not equal to any of the inputs.
    assert result[0].id not in {m.id for m in messages}


def test_skips_coalesce_when_any_source_is_non_operator() -> None:
    """Defensive guard: mixed sources should not silently lose attribution.

    All ACP producers normalize ``source="operator"``, so this branch
    is theoretical for the queue — but if a caller ever feeds a
    non-operator message in, drop the merge rather than silently
    rewrite the conversation.
    """
    messages = [
        ChatMessageUser(content="op1", source="operator"),
        ChatMessageUser(content="dataset", source="input"),
    ]
    result = coalesce(_wrap(*messages))
    assert result == messages


def test_flattens_mixed_modal_into_content_list() -> None:
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
    result = coalesce(_wrap(*messages))
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


def test_flattens_when_only_one_message_is_multimodal() -> None:
    """Branch coverage: one list-content msg flips the whole drain into list mode."""
    image = ContentImage(image="data:image/png;base64,YYY")
    messages = [
        ChatMessageUser(content="a", source="operator"),
        ChatMessageUser(content=[image], source="operator"),
    ]
    result = coalesce(_wrap(*messages))
    assert len(result) == 1
    assert isinstance(result[0].content, list)
    assert isinstance(result[0].content[0], ContentText)
    assert result[0].content[0].text == "a"
    assert result[0].content[1] is image
