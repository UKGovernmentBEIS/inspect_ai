"""Regression test for functionResponse-in-model-turn handling in the Gemini bridge.

localharness (Google Antigravity SDK) returns tool RESULTS as a `functionResponse`
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
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from inspect_ai._util.content import ContentReasoning
from inspect_ai.agent._bridge._errors import BridgePolicyError
from inspect_ai.agent._bridge.google_api_impl import (
    _PLACEHOLDER_THOUGHT_SIGNATURES,
    gemini_response_from_output,
    messages_from_google_contents,
)
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.model._model_output import (
    ChatCompletionChoice,
    Logprob,
    Logprobs,
    ModelOutput,
    TopLogprob,
)
from inspect_ai.tool._tool_call import ToolCall

if TYPE_CHECKING:
    from google.genai.types import Part

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


async def _model_turn_function_call(contents: list[dict[str, Any]]) -> Part:
    from inspect_ai.model._providers.google import as_chat_messages

    messages = messages_from_google_contents(contents, None)
    model_turn = (await as_chat_messages(MagicMock(), messages))[1]
    assert model_turn.parts is not None
    return next(part for part in model_turn.parts if part.function_call)


@pytest.mark.parametrize("placeholder", sorted(_PLACEHOLDER_THOUGHT_SIGNATURES))
async def test_placeholder_signature_uses_signature_embedded_by_bridge(
    placeholder: str,
) -> None:
    pytest.importorskip("google.genai")
    signature = b"\xfbreal-gemini-signature\xff"
    output = ModelOutput(
        model="model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content=[
                        ContentReasoning(
                            reasoning=base64.b64encode(signature).decode(),
                            redacted=True,
                        )
                    ],
                    tool_calls=[
                        ToolCall(id="call_1", function="ls", arguments={"path": "."})
                    ],
                ),
                stop_reason="tool_calls",
            )
        ],
    )
    parts = gemini_response_from_output(output, "model")["candidates"][0]["content"][
        "parts"
    ]
    # gemini-cli replays the turn with its placeholder in place of the signature
    for part in parts:
        if "thoughtSignature" in part:
            part["thoughtSignature"] = placeholder
    contents: list[dict[str, Any]] = [
        {"role": "user", "parts": [{"text": "list files"}]},
        {"role": "model", "parts": parts},
        {
            "role": "user",
            "parts": [{"functionResponse": {"name": "ls", "response": {"out": "a"}}}],
        },
    ]

    assert (await _model_turn_function_call(contents)).thought_signature == signature


@pytest.mark.parametrize("placeholder", sorted(_PLACEHOLDER_THOUGHT_SIGNATURES))
async def test_placeholder_signature_reaches_gemini_unchanged(placeholder: str) -> None:
    pytest.importorskip("google.genai")
    contents: list[dict[str, Any]] = [
        {"role": "user", "parts": [{"text": "list files"}]},
        {
            "role": "model",
            "parts": [
                {
                    "functionCall": {"name": "ls", "args": {}},
                    "thoughtSignature": placeholder,
                }
            ],
        },
        {
            "role": "user",
            "parts": [{"functionResponse": {"name": "ls", "response": {"out": "a"}}}],
        },
    ]

    part = await _model_turn_function_call(contents)

    # google-genai sends request bytes as URL-safe base64
    assert part.thought_signature is not None
    assert base64.urlsafe_b64encode(part.thought_signature).decode() == placeholder
