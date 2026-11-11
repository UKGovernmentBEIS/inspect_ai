"""Tests for message and response translation in the Gemini bridge.

functionResponse in a model turn: localharness (Google Antigravity SDK) returns tool RESULTS as a `functionResponse`
part inside a `role="model"` turn (cloudcode dialect), not the public-Gemini
`role="user"`/function turn. Before the fix, `_extract_model_parts` had no
functionResponse branch, so the result was silently dropped -> an empty assistant turn
-> the request Inspect then sent to Gemini ended on a model turn and Gemini rejected it
with 400 "Requests ending with a model turn are not supported", stalling the agent
after a single tool call.

The fixture is the inbound `contents` captured from a live gemini-3.6-flash
Antigravity SDK run (roles: user, model[functionCall call_mcp_tool],
model[functionResponse]), trimmed for the repo: the system prompt is replaced with a
short stub and the thought-signature blobs are shortened (the tests rely only on the
turn structure and tool name, and the think-body/thoughtSignature strings still match).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from google.genai import types

from inspect_ai._util.content import ContentReasoning
from inspect_ai.agent._bridge._errors import BridgePolicyError
from inspect_ai.agent._bridge.google_api_impl import (
    gemini_response_from_output,
    messages_from_google_contents,
)
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.model._model_output import Logprob, Logprobs, ModelOutput, TopLogprob
from inspect_ai.model._openrouter_reasoning import (
    openrouter_reasoning_details_to_reasoning,
    reasoning_to_openrouter_reasoning_details,
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


@pytest.mark.parametrize("role", ["user", "model"])
def test_google_bridge_rejects_file_data_parts(role: str) -> None:
    contents = [
        {
            "role": role,
            "parts": [
                {
                    "fileData": {
                        "mimeType": "application/pdf",
                        "fileUri": "https://example.com/report.pdf",
                    }
                }
            ],
        }
    ]

    with pytest.raises(BridgePolicyError, match="send the bytes as inlineData"):
        messages_from_google_contents(contents, None)


def test_google_response_preserves_token_logprobs() -> None:
    output = ModelOutput.from_content("mockllm/model", "Hello 世界")
    output.choices[0].logprobs = Logprobs(
        content=[
            Logprob(
                token="Hello",
                logprob=-0.3,
                top_logprobs=[
                    TopLogprob(token="Hi", logprob=-0.1),
                    TopLogprob(token="Hello", logprob=-0.3),
                ],
            ),
            Logprob(token=" 世界", logprob=-0.9, top_logprobs=[]),
            Logprob(token="", logprob=0.0),
        ]
    )

    candidate = gemini_response_from_output(output, "model")["candidates"][0]

    assert candidate["logprobsResult"] == {
        "chosenCandidates": [
            {"token": "Hello", "logProbability": -0.3},
            {"token": " 世界", "logProbability": -0.9},
            {"token": "", "logProbability": 0.0},
        ],
        "topCandidates": [
            {
                "candidates": [
                    {"token": "Hi", "logProbability": -0.1},
                    {"token": "Hello", "logProbability": -0.3},
                ]
            },
            {"candidates": []},
            {"candidates": []},
        ],
    }
    assert candidate["avgLogprobs"] == pytest.approx(-0.4)


@pytest.mark.parametrize("logprobs", [None, Logprobs(content=[])])
def test_google_response_without_logprobs_is_unchanged(
    logprobs: Logprobs | None,
) -> None:
    output = ModelOutput.from_content("mockllm/model", "Hello")
    expected = gemini_response_from_output(output, "model")
    output.choices[0].logprobs = logprobs

    response = gemini_response_from_output(output, "model")

    assert response == expected
    assert "logprobsResult" not in response["candidates"][0]
    assert "avgLogprobs" not in response["candidates"][0]


def _assistant_from_parts(parts: list[dict[str, object]]) -> ChatMessageAssistant:
    messages = messages_from_google_contents(
        [
            {"role": "user", "parts": [{"text": "Read a."}]},
            {"role": "model", "parts": parts},
        ],
        None,
    )
    assert isinstance(messages[-1], ChatMessageAssistant)
    return messages[-1]


def _reasoning(message: ChatMessageAssistant) -> ContentReasoning:
    assert isinstance(message.content, list)
    reasoning = [c for c in message.content if isinstance(c, ContentReasoning)]
    assert len(reasoning) == 1
    return reasoning[0]


@pytest.mark.parametrize(
    "signature",
    [
        base64.b64encode(b"\xfb\xff\xfe\xfa").decode(),
        "not a signature",
        "pas de clé",
    ],
)
def test_google_bridge_keeps_readable_reasoning_beside_signature(
    signature: str,
) -> None:
    message = _assistant_from_parts(
        [
            {"text": "<think>I should read the file.</think>"},
            {
                "functionCall": {"name": "read_file", "args": {"path": "a"}},
                "thoughtSignature": signature,
            },
        ]
    )

    assert message.tool_calls and message.tool_calls[0].function == "read_file"
    reasoning = _reasoning(message)
    assert reasoning.reasoning == signature
    assert reasoning.redacted


@pytest.mark.parametrize("keep_signature_field", [True, False])
def test_google_bridge_round_trips_openai_reasoning_token(
    keep_signature_field: bool,
) -> None:
    token = base64.urlsafe_b64encode(b"\x80\x00\xfb\xef\xbe\xff\xff\xff" * 3).decode()
    assert "-" in token and "_" in token
    output = ModelOutput.for_tool_call("mockllm/model", "read_file", {"path": "a"})
    output.message.content = [
        ContentReasoning(reasoning=token, signature="rs_1", redacted=True)
    ]

    content = gemini_response_from_output(output, "model")["candidates"][0]["content"]
    if not keep_signature_field:
        for part in content["parts"]:
            part.pop("thoughtSignature", None)
    message = _assistant_from_parts(content["parts"])

    reasoning = _reasoning(message)
    assert reasoning.reasoning == token
    assert reasoning.signature == "rs_1"
    assert reasoning.redacted


def test_google_bridge_keeps_openrouter_reasoning_after_sdk_serialization() -> None:
    original = openrouter_reasoning_details_to_reasoning(
        [
            {
                "type": "reasoning.text",
                "text": "read file",
                "format": "google-gemini-v1",
            },
            {
                "type": "reasoning.encrypted",
                "data": "+//++g==",
                "format": "google-gemini-v1",
            },
        ]
    )
    assert isinstance(original, ContentReasoning) and original.signature
    output = ModelOutput.for_tool_call("mockllm/model", "read_file", {"path": "a"})
    output.message.content = [original]

    content = gemini_response_from_output(output, "model")["candidates"][0]["content"]
    sdk_parts = types.Content(role="model", parts=content["parts"]).model_dump(
        mode="json", exclude_none=True
    )["parts"]
    assert any(p.get("thought_signature") == "-__--g==" for p in sdk_parts)
    reasoning = _reasoning(_assistant_from_parts(sdk_parts))

    assert reasoning.reasoning == original.reasoning
    assert reasoning.signature == original.signature
    assert reasoning.summary == original.summary
    assert reasoning.redacted == original.redacted
    assert reasoning_to_openrouter_reasoning_details(
        reasoning
    ) == reasoning_to_openrouter_reasoning_details(original)


@pytest.mark.parametrize(
    "clear_before_typing",
    [None, False, True],
    ids=["omitted", "false", "true"],
)
def test_google_response_sends_type_text_at_clear_before_typing(
    clear_before_typing: bool | None,
) -> None:
    """The bridged agent clears the field when the flag is missing, so False is sent."""
    # computer() call as made by a Gemini model given computer() as an ordinary
    # function (e.g. gemini-2.5-pro), which leaves clear_before_typing out
    arguments: dict[str, object] = {
        "action": "type",
        "text": "200",
        "coordinate": [683, 384],
    }
    if clear_before_typing is not None:
        arguments["clear_before_typing"] = clear_before_typing
    output = ModelOutput.for_tool_call("mockllm/model", "computer", arguments)

    parts = gemini_response_from_output(output, "model")["candidates"][0]["content"][
        "parts"
    ]

    function_call = next(p["functionCall"] for p in parts if "functionCall" in p)
    assert function_call["name"] == "type_text_at"
    assert function_call["args"]["clear_before_typing"] is bool(clear_before_typing)
