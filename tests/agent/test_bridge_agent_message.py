r"""Unit tests for Codex Multi-Agent V2 `agent_message` handling in the bridge.

Codex >= 0.146 delivers inter-agent communication (spawn_agent / send_message /
followup_task tasking and child FINAL_ANSWER returns) as Responses input items
of type `agent_message` (openai/codex#26210). The bridge must:

(a) not choke on the item when converting input to messages (regression:
    it previously raised "Type agent_message is not supported by the agent
    bridge", #4762);
(b) attribute the message to its author in the rendered text, using Codex's
    own downgrade convention ("Agent message from {author}:\n{text}") so the
    receiving model never mistakes another agent's words for the user's or
    its own;
(c) preserve the original item verbatim (via ContentText.internal) so the
    OpenAI Responses provider can replay it natively -- `encrypted_content`
    parts are undecryptable to us but ARE decryptable by OpenAI server-side,
    so dropping them would silently degrade delegation on OpenAI targets;
(d) never drop content silently: an item with no plaintext still produces an
    attributed placeholder (and the verbatim payload for replay), plus a
    logged warning that non-OpenAI targets see only the placeholder.

These tests cover the conversion helpers directly (no network).
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from openai.types.responses import ResponseInputItemParam

from inspect_ai._util.content import ContentText
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge._errors import BridgePolicyError
from inspect_ai.agent._bridge.responses_impl import (
    messages_from_responses_input,
)
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import validate_bridge_media
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._openai_responses import (
    is_agent_message,
    openai_responses_inputs,
)

MODEL_NAME = "openai/gpt-5.6"


@pytest.fixture
def _warn_once_messages() -> Any:
    # warn_once dedupes via a module-level list; clear it and yield it so the
    # test can assert on what was emitted. caplog isn't reliable here because
    # init_logger sets propagate=False on the inspect_ai logger once any
    # earlier test triggers it.
    from inspect_ai._util import logger as _inspect_logger

    _inspect_logger._warned.clear()
    yield _inspect_logger._warned
    _inspect_logger._warned.clear()


def _agent_message_item(
    *content: dict[str, Any],
    author: str = "subagent",
    recipient: str = "parent",
) -> dict[str, Any]:
    return {
        "type": "agent_message",
        "author": author,
        "recipient": recipient,
        "content": list(content),
    }


def _text(text: str) -> dict[str, Any]:
    return {"type": "input_text", "text": text}


def _encrypted(ciphertext: str = "gAAAAA-ciphertext") -> dict[str, Any]:
    return {"type": "encrypted_content", "encrypted_content": ciphertext}


# 1. predicate


def test_is_agent_message_predicate() -> None:
    assert is_agent_message(
        cast(ResponseInputItemParam, _agent_message_item(_text("delegate result")))
    )
    assert not is_agent_message(
        cast(
            ResponseInputItemParam,
            {"type": "message", "role": "user", "content": "hi"},
        )
    )
    assert not is_agent_message(
        cast(
            ResponseInputItemParam,
            {"type": "additional_tools", "role": "developer", "tools": []},
        )
    )


# 2. conversion: agent_message becomes an author-attributed user message


def test_agent_message_converts_to_attributed_user_message() -> None:
    input_items = cast(
        list[ResponseInputItemParam],
        [
            {
                "type": "message",
                "role": "user",
                "content": [_text("delegate this")],
            },
            _agent_message_item(_text("delegate result")),
        ],
    )

    messages = messages_from_responses_input(input_items, [], MODEL_NAME)

    assert [message.text for message in messages] == [
        "delegate this",
        "Agent message from subagent:\ndelegate result",
    ]
    assert all(isinstance(message, ChatMessageUser) for message in messages)


def test_agent_message_attribution_uses_author_field() -> None:
    input_items = cast(
        list[ResponseInputItemParam],
        [_agent_message_item(_text("do the subtask"), author="parent")],
    )

    messages = messages_from_responses_input(input_items, [], MODEL_NAME)

    assert len(messages) == 1
    assert messages[0].text == "Agent message from parent:\ndo the subtask"


def test_agent_message_with_null_author_uses_default_attribution() -> None:
    # an explicit null author must not render as "Agent message from None:"
    item = _agent_message_item(_text("delegate result"))
    item["author"] = None

    messages = messages_from_responses_input(
        cast(list[ResponseInputItemParam], [item]), [], MODEL_NAME
    )

    assert len(messages) == 1
    assert messages[0].text == "Agent message from agent:\ndelegate result"


def test_agent_message_with_role_key_is_still_attributed() -> None:
    # dispatch-order guard: is_agent_message (exact type match) must win over
    # is_response_input_message (loose keys-based match), so an agent_message
    # that grows a "role" key in a future Codex version keeps its attribution
    # and verbatim stash instead of being swallowed as a plain message
    item = _agent_message_item(_text("delegate result"))
    item["role"] = "user"

    messages = messages_from_responses_input(
        cast(list[ResponseInputItemParam], [item]), [], MODEL_NAME
    )

    assert len(messages) == 1
    assert messages[0].text == "Agent message from subagent:\ndelegate result"
    content = messages[0].content
    assert isinstance(content, list)
    assert isinstance(content[0], ContentText)
    assert content[0].internal == {"agent_message": item}


@pytest.mark.parametrize("update", [{"author": None}, {"role": "user"}])
async def test_agent_message_supported_envelope_variants_pass_validation(
    update: dict[str, Any],
) -> None:
    item = _agent_message_item(_text("delegate result"))
    item.update(update)
    messages = messages_from_responses_input(
        cast(list[ResponseInputItemParam], [item]), [], MODEL_NAME
    )

    await validate_bridge_media(
        AgentBridge(AgentState(messages=[]), allow_remote_media=False), messages
    )
    assert dict((await openai_responses_inputs(messages))[0]) == item


async def test_agent_message_media_is_rejected_by_sandbox_bridge() -> None:
    item = _agent_message_item(
        {"type": "input_image", "image_url": "https://example.com/secret"}
    )
    messages = messages_from_responses_input(
        cast(list[ResponseInputItemParam], [item]), [], MODEL_NAME
    )

    with pytest.raises(BridgePolicyError, match="input_image.*cannot be replayed"):
        await validate_bridge_media(
            AgentBridge(AgentState(messages=[]), allow_remote_media=False), messages
        )


def test_agent_message_joins_multiple_text_parts() -> None:
    input_items = cast(
        list[ResponseInputItemParam],
        [_agent_message_item(_text("part one"), _text("part two"))],
    )

    messages = messages_from_responses_input(input_items, [], MODEL_NAME)

    assert len(messages) == 1
    assert messages[0].text == "Agent message from subagent:\npart one\npart two"


# 3. fidelity: the original item round-trips verbatim to an OpenAI Responses
#    target (encrypted_content is undecryptable to us but decryptable by
#    OpenAI server-side, so it must survive the bridge round-trip)


async def test_agent_message_round_trips_verbatim_to_openai_responses() -> None:
    original = _agent_message_item(_text("Payload:"), _encrypted())

    messages = messages_from_responses_input(
        cast(list[ResponseInputItemParam], [original]), [], MODEL_NAME
    )
    assert len(messages) == 1

    items = await openai_responses_inputs(messages)

    assert len(items) == 1
    assert dict(items[0]) == original


async def test_plain_user_message_still_emits_message_item() -> None:
    # guard: the verbatim replay path must not hijack ordinary user messages
    messages = messages_from_responses_input(
        cast(
            list[ResponseInputItemParam],
            [
                {
                    "type": "message",
                    "role": "user",
                    "content": [_text("hello")],
                }
            ],
        ),
        [],
        MODEL_NAME,
    )

    items = await openai_responses_inputs(messages)

    assert len(items) == 1
    assert dict(items[0]).get("type") == "message"


# 4. no silent drops: encrypted-only items produce an attributed placeholder,
#    preserve the verbatim payload for replay, and log a warning


async def test_encrypted_only_agent_message_is_not_silently_dropped(
    _warn_once_messages: list[str],
) -> None:
    original = _agent_message_item(_encrypted(), author="parent")

    messages = messages_from_responses_input(
        cast(list[ResponseInputItemParam], [original]), [], MODEL_NAME
    )

    # a message survives, attributed, with a placeholder mentioning the
    # encrypted payload (non-OpenAI targets see this text)
    assert len(messages) == 1
    assert isinstance(messages[0], ChatMessageUser)
    assert messages[0].text.startswith("Agent message from parent:")
    assert "encrypted" in messages[0].text

    # the warning names the degradation
    assert any(
        "agent_message" in message and "encrypted" in message
        for message in _warn_once_messages
    )

    # and the verbatim payload still replays natively to OpenAI targets
    items = await openai_responses_inputs(messages)
    assert len(items) == 1
    assert dict(items[0]) == original


def test_empty_agent_message_is_not_silently_dropped(
    _warn_once_messages: list[str],
) -> None:
    # content with neither input_text nor encrypted_content parts must still
    # produce an attributed placeholder plus a warning
    original = _agent_message_item(author="parent")

    messages = messages_from_responses_input(
        cast(list[ResponseInputItemParam], [original]), [], MODEL_NAME
    )

    assert len(messages) == 1
    assert isinstance(messages[0], ChatMessageUser)
    assert messages[0].text == "Agent message from parent:\n[no readable content]"
    assert any(
        "agent_message" in message and "no readable content" in message
        for message in _warn_once_messages
    )


def test_agent_message_carries_verbatim_item_as_internal() -> None:
    original = _agent_message_item(_text("delegate result"))

    messages = messages_from_responses_input(
        cast(list[ResponseInputItemParam], [original]), [], MODEL_NAME
    )

    assert len(messages) == 1
    content = messages[0].content
    assert isinstance(content, list)
    assert isinstance(content[0], ContentText)
    assert content[0].internal == {"agent_message": original}
