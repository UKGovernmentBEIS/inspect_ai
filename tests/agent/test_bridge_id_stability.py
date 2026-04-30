"""Tests for stable IDs across agent_bridge() round trips.

The bridge translates inspect's `ChatMessage` / `ToolCall` / `ChatMessageSystem`
objects to whatever native format the harness uses (Gemini, Anthropic, OpenAI
Responses, ...) and back. None of those native formats carry inspect's own
``ChatMessage.id``, and Gemini in particular reformats / mints fresh
``tool_call.id`` values on every round trip.

Without an explicit mapping, the bridge ends up minting a fresh id for the
*same logical message* every time it appears in echoed history. Downstream
consumers that build a transcript tree by id then see the same message twice
with two different ids and fork the tree.

These tests pin the desired behavior: an output emitted in turn N must have
the same ``ChatMessage.id`` and the same ``ToolCall.id`` values when it
re-appears as input in turn N+1, and a ``ChatMessageSystem`` must keep its
id even when its *content* mutates mid-conversation.
"""

from __future__ import annotations

from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import apply_message_ids
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool_call import ToolCall


def _make_bridge() -> AgentBridge:
    return AgentBridge(state=AgentState(messages=[]))


def test_assistant_message_id_preserved_when_echoed_back() -> None:
    """An assistant message emitted in turn N keeps its id in turn N+1."""
    bridge = _make_bridge()

    # Turn 1 input: just a user message.
    user_msg = ChatMessageUser(content="Hello")
    turn1_input: list = [user_msg]
    apply_message_ids(bridge, turn1_input)

    # Turn 1 output: the model emits an assistant message with a stable id.
    # ``bridge_generate`` calls ``_register_output_message`` after each
    # successful generation; we invoke it directly here to keep the test
    # focused on the id-bookkeeping contract.
    output_msg = ChatMessageAssistant(id="ASSIST_TURN_1", content="Hi there!")
    bridge._register_output_message(output_msg)

    # Turn 2 input: harness echoes back the assistant message (without an id,
    # which is what every native protocol does).
    echoed_assistant = ChatMessageAssistant(content="Hi there!")
    follow_up = ChatMessageUser(content="Tell me more")
    turn2_input: list = [user_msg, echoed_assistant, follow_up]
    apply_message_ids(bridge, turn2_input)

    assert turn2_input[1].id == "ASSIST_TURN_1", (
        "echoed assistant message must reuse the id from its turn-1 output"
    )


def test_tool_call_id_preserved_when_echoed_back() -> None:
    """ToolCall ids on an echoed assistant message resolve to the originals.

    Models like Gemini do not carry inspect's ``tool_call.id`` over the wire;
    the bridge's inbound translation invents a fresh id (e.g.
    ``call_<func>_<short>``) deterministic in function name and args. The
    fix should map that synthesized id back to the original on round trip,
    on the assistant message *and* on any ``ChatMessageTool`` referencing it.
    """
    bridge = _make_bridge()

    user_msg = ChatMessageUser(content="Search for hello")
    turn1_input: list = [user_msg]
    apply_message_ids(bridge, turn1_input)

    # Turn 1 output: an assistant tool call with a stable id.
    original_tool_call = ToolCall(
        id="TC_TURN_1",
        function="search",
        arguments={"q": "hello"},
        type="function",
    )
    output_msg = ChatMessageAssistant(
        id="ASSIST_T1",
        content="",
        tool_calls=[original_tool_call],
    )
    bridge._register_output_message(output_msg)

    # Turn 2 input: harness echoes the message back. The tool_call.id has
    # been rewritten by the bridge's inbound translation (Gemini-style).
    echoed_tool_call = ToolCall(
        id="call_search_abc12345",
        function="search",
        arguments={"q": "hello"},
        type="function",
    )
    echoed_assistant = ChatMessageAssistant(
        content="",
        tool_calls=[echoed_tool_call],
    )
    tool_result = ChatMessageTool(
        content="ok",
        tool_call_id="call_search_abc12345",
        function="search",
    )

    turn2_input: list = [user_msg, echoed_assistant, tool_result]
    apply_message_ids(bridge, turn2_input)

    assert turn2_input[1].tool_calls is not None
    assert turn2_input[1].tool_calls[0].id == "TC_TURN_1", (
        "echoed tool call must be remapped to the id minted in turn 1"
    )
    assert turn2_input[2].tool_call_id == "TC_TURN_1", (
        "ChatMessageTool.tool_call_id must follow the rename"
    )


def test_system_message_id_preserved_across_content_mutation() -> None:
    """The system message's id stays stable when its *content* changes.

    Bridged scaffolds (Gemini CLI's plan-mode toggle, skill activation, etc.)
    routinely mutate the system prompt mid-conversation. A naive content-hash
    approach would mint a fresh id every time, splitting downstream transcript
    trees into N parallel roots. The bridge should treat the system prompt as
    a single slot per conversation: same slot, same id, regardless of content.
    """
    bridge = _make_bridge()

    sys_v1 = ChatMessageSystem(content="You are a helpful assistant.")
    user_msg = ChatMessageUser(content="Hello")
    turn1_input: list = [sys_v1, user_msg]
    apply_message_ids(bridge, turn1_input)
    first_id = turn1_input[0].id
    assert first_id is not None

    # Turn 2: agent toggled plan mode. Same conversation, mutated system text.
    sys_v2 = ChatMessageSystem(
        content="You are a helpful assistant. (Plan mode active.)",
    )
    follow_up = ChatMessageUser(content="Plan it.")
    turn2_input: list = [sys_v2, user_msg, follow_up]
    apply_message_ids(bridge, turn2_input)

    assert turn2_input[0].id == first_id, (
        "mutated system prompt must keep the id from the first turn"
    )

    # Turn 3: content reverts (plan-mode off). Still the same slot.
    sys_v3 = ChatMessageSystem(content="You are a helpful assistant.")
    turn3_input: list = [sys_v3, user_msg, follow_up]
    apply_message_ids(bridge, turn3_input)

    assert turn3_input[0].id == first_id, (
        "reverted system prompt must keep the id from the first turn"
    )


def test_gemini_round_trip_preserves_ids_end_to_end() -> None:
    """End-to-end check that ids survive the Gemini-shaped translation.

    Drives one turn through ``gemini_response_from_output`` (outbound) and
    ``messages_from_google_contents`` (inbound) to confirm the deterministic
    Gemini ``call_id`` reconstruction in ``_extract_model_parts`` still
    resolves back to the original ids once ``apply_message_ids`` runs over
    the reconstructed conversation.
    """
    from inspect_ai.agent._bridge.google_api_impl import (
        gemini_response_from_output,
        messages_from_google_contents,
    )

    bridge = _make_bridge()

    # Turn 1: bridge sees the first request from the harness.
    system_text = "You are a helpful assistant."
    contents_t1 = [{"role": "user", "parts": [{"text": "Search for hello"}]}]
    messages_t1 = messages_from_google_contents(
        contents_t1,
        {"parts": [{"text": system_text}]},
    )
    apply_message_ids(bridge, messages_t1)

    # Output from inspect: an assistant message with a tool call.
    original_tc = ToolCall(
        id="ORIGINAL_TC_ID",
        function="search",
        arguments={"q": "hello"},
        type="function",
    )
    output_msg = ChatMessageAssistant(
        id="ORIGINAL_MSG_ID",
        content="searching...",
        tool_calls=[original_tc],
    )
    output = ModelOutput.from_message(output_msg)
    bridge._register_output_message(output_msg)

    # Bridge's outbound translation. Note that Gemini drops both ids.
    gemini_response = gemini_response_from_output(output, "inspect")
    model_parts = gemini_response["candidates"][0]["content"]["parts"]

    # Turn 2: harness echoes the assistant turn back as part of history.
    contents_t2 = [
        contents_t1[0],
        {"role": "model", "parts": model_parts},
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": "search",
                        "response": {"results": ["hello, world"]},
                    }
                }
            ],
        },
    ]
    messages_t2 = messages_from_google_contents(
        contents_t2,
        {"parts": [{"text": system_text}]},
    )
    apply_message_ids(bridge, messages_t2)

    # find the assistant message and its tool result
    assistant = next(m for m in messages_t2 if isinstance(m, ChatMessageAssistant))
    tool_result = next(m for m in messages_t2 if isinstance(m, ChatMessageTool))

    assert assistant.id == "ORIGINAL_MSG_ID", (
        "assistant message id must be preserved through Gemini round trip"
    )
    assert assistant.tool_calls is not None
    assert assistant.tool_calls[0].id == "ORIGINAL_TC_ID", (
        "tool_call id must be remapped from the synthesized Gemini id"
    )
    assert tool_result.tool_call_id == "ORIGINAL_TC_ID", (
        "tool result must follow the tool_call rename"
    )
