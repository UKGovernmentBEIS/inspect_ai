"""Regression test for functionResponse-in-model-turn handling in the Gemini bridge.

localharness (Google Antigravity SDK) returns tool RESULTS as a `functionResponse`
part inside a `role="model"` turn (cloudcode dialect), not the public-Gemini
`role="user"`/function turn. Before the fix, `_extract_model_parts` had no
functionResponse branch, so the result was silently dropped -> an empty assistant turn
-> the request Inspect then sent to Gemini ended on a model turn and Gemini rejected it
with 400 "Requests ending with a model turn are not supported", stalling the agent
after a single tool call.

The fixture is the VERBATIM inbound `contents` captured from a live gemini-3.6-flash
Antigravity SDK run (roles: user, model[functionCall call_mcp_tool], model[functionResponse]).
"""

from __future__ import annotations

import json
from pathlib import Path

from inspect_ai.agent._bridge.google_api_impl import messages_from_google_contents
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageTool,
)

_FIXTURE = json.loads(
    (
        Path(__file__).parent
        / "fixtures"
        / "live_localharness_functionresponse_model_turn.json"
    ).read_text(encoding="utf-8")
)
_CONTENTS: list[dict[str, object]] = _FIXTURE["contents"]
_SYSTEM_INSTRUCTION = _FIXTURE["system_instruction"]


def test_functionresponse_in_model_turn_is_reroled_to_tool_message() -> None:
    messages = messages_from_google_contents(_CONTENTS, _SYSTEM_INSTRUCTION)

    # The functionResponse-bearing model turn must land as a tool message (which maps
    # back to a Gemini user/functionResponse turn), NOT get dropped into an empty
    # assistant turn.
    assert isinstance(messages[-1], ChatMessageTool), (
        f"expected trailing tool message, got {type(messages[-1]).__name__}"
    )
    tool_msg = messages[-1]
    assert tool_msg.function == "call_mcp_tool"
    assert tool_msg.content, "tool message must carry the real captured result"

    # It must link to the preceding assistant tool-call turn by id.
    assistant_calls = {
        tc.id: tc.function
        for m in messages
        if isinstance(m, ChatMessageAssistant)
        for tc in (m.tool_calls or [])
    }
    assert "call_mcp_tool" in assistant_calls.values()
    assert tool_msg.tool_call_id in assistant_calls


def test_converted_conversation_does_not_end_on_a_model_turn() -> None:
    # The exact regression: an empty/bare assistant (model) turn as the final message
    # is what Gemini 400s on. After the fix the conversation ends on the tool result.
    messages = messages_from_google_contents(_CONTENTS, _SYSTEM_INSTRUCTION)
    last = messages[-1]
    assert not (isinstance(last, ChatMessageAssistant) and not last.tool_calls), (
        "conversation ends on an empty model turn (the Gemini-400 bug)"
    )
