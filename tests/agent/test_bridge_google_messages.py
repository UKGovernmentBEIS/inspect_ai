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

import hashlib
import json
from pathlib import Path

import pytest

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


def test_google_response_carries_each_calls_id() -> None:
    output = ModelOutput.for_tool_call("mockllm/model", "read_file", {"path": "a"})
    [call] = output.message.tool_calls or []
    unnamed = ModelOutput.for_tool_call("mockllm/model", "read_file", {"path": "b"})
    for unnamed_call in unnamed.message.tool_calls or []:
        unnamed_call.id = ""

    def function_call(output: ModelOutput, call_ids: bool = True) -> object:
        parts = gemini_response_from_output(output, "model", call_ids=call_ids)[
            "candidates"
        ][0]["content"]["parts"]
        [part] = [part for part in parts if "functionCall" in part]
        return part["functionCall"]

    assert function_call(output) == {
        "id": call.id,
        "name": "read_file",
        "args": {"path": "a"},
    }
    assert function_call(unnamed) == {"name": "read_file", "args": {"path": "b"}}
    # without a sentinel, as before
    assert function_call(output, call_ids=False) == {
        "name": "read_file",
        "args": {"path": "a"},
    }


def echoed_contents(echoed: str) -> list[dict[str, object]]:
    return [
        {"role": "user", "parts": [{"text": "Read a."}]},
        {
            "role": "model",
            "parts": [
                {
                    "functionCall": {
                        "id": echoed,
                        "name": "read_file",
                        "args": {"path": "a"},
                    }
                }
            ],
        },
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "id": echoed,
                        "name": "read_file",
                        "response": {"out": "x"},
                    }
                }
            ],
        },
    ]


def deterministic_id(name: str, args: dict[str, object], position: int) -> str:
    # the id main derives for a call carrying no id the bridge reads
    args_str = json.dumps(args, sort_keys=True) if args else ""
    digest = hashlib.md5(f"{name}:{args_str}:{position}".encode()).hexdigest()[:8]
    return f"call_{name}_{digest}"


def test_google_ids_the_scaffold_echoes_are_ignored_without_call_ids() -> None:
    messages = messages_from_google_contents(
        echoed_contents("read_file__read_file_1712_0"), None
    )

    assistant = next(m for m in messages if isinstance(m, ChatMessageAssistant))
    tool = next(m for m in messages if isinstance(m, ChatMessageTool))
    expected = deterministic_id("read_file", {"path": "a"}, 0)
    assert [call.id for call in assistant.tool_calls or []] == [expected]
    assert tool.tool_call_id == expected


@pytest.mark.parametrize("prefixed", [False, True])
def test_google_ids_the_scaffold_echoes_are_kept(prefixed: bool) -> None:
    # gemini-cli prefixes the id it is handed with `<function>__`
    echoed = "read_file__tok_1" if prefixed else "tok_1"
    contents = echoed_contents(echoed)

    messages = messages_from_google_contents(contents, None, call_ids=True)

    assistant = next(m for m in messages if isinstance(m, ChatMessageAssistant))
    tool = next(m for m in messages if isinstance(m, ChatMessageTool))
    assert [call.id for call in assistant.tool_calls or []] == ["tok_1"]
    assert tool.tool_call_id == "tok_1"


def test_google_calls_without_ids_keep_their_deterministic_ids() -> None:
    contents: list[dict[str, object]] = [
        {"role": "user", "parts": [{"text": "Read a."}]},
        {
            "role": "model",
            "parts": [{"functionCall": {"name": "read_file", "args": {"path": "a"}}}],
        },
        {
            "role": "user",
            "parts": [
                {"functionResponse": {"name": "read_file", "response": {"out": "x"}}}
            ],
        },
    ]

    first = messages_from_google_contents(contents, None, call_ids=True)
    second = messages_from_google_contents(contents, None, call_ids=True)

    [call] = (
        next(m for m in first if isinstance(m, ChatMessageAssistant)).tool_calls or []
    )
    tool = next(m for m in first if isinstance(m, ChatMessageTool))
    assert call.id.startswith("call_read_file_")
    assert tool.tool_call_id == call.id
    assert [m.model_dump(exclude={"id"}) for m in first] == [
        m.model_dump(exclude={"id"}) for m in second
    ]


def test_a_google_round_trip_without_a_sentinel_keeps_mains_ids() -> None:
    import anyio

    from inspect_ai.agent import AgentState
    from inspect_ai.agent._bridge.google_api import inspect_google_api_request
    from inspect_ai.agent._bridge.types import AgentBridge
    from inspect_ai.model import ChatMessage, get_model
    from inspect_ai.tool import ToolCall

    inputs: list[list[ChatMessage]] = []
    outputs = [
        ModelOutput.for_tool_call("mockllm/model", "read_file", {"path": "a"}),
        ModelOutput.from_content("mockllm/model", "done"),
    ]

    def respond(input: list[ChatMessage], *_: object) -> ModelOutput:
        inputs.append(list(input))
        return outputs[len(inputs) - 1]

    model = get_model("mockllm/model", custom_outputs=respond, memoize=False)
    bridge = AgentBridge(AgentState(messages=[]), model_aliases={"inspect": model})
    tools = [
        {
            "functionDeclarations": [
                {
                    "name": "read_file",
                    "description": "Read",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                }
            ]
        }
    ]

    async def round_trip() -> dict[str, object]:
        contents: list[dict[str, object]] = [
            {"role": "user", "parts": [{"text": "Read a."}]}
        ]
        response = await inspect_google_api_request(
            {"model": "inspect", "contents": contents, "tools": tools},
            None,
            None,
            bridge,
        )
        [part] = [
            part
            for part in response["candidates"][0]["content"]["parts"]
            if "functionCall" in part
        ]
        # gemini-cli synthesizes an id when it is handed none
        synthesized = "read_file__read_file_1712_0"
        call = {**part["functionCall"], "id": synthesized}
        contents += [
            {"role": "model", "parts": [{"functionCall": call}]},
            {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "id": synthesized,
                            "name": "read_file",
                            "response": {"out": "x"},
                        }
                    }
                ],
            },
        ]
        await inspect_google_api_request(
            {"model": "inspect", "contents": contents, "tools": tools},
            None,
            None,
            bridge,
        )
        return dict(part["functionCall"])

    function_call = anyio.run(round_trip)

    # the response carries no id, and the ids the scaffold sends back are not
    # read: the call and its result get the id main derives from the call
    assert function_call == {"name": "read_file", "args": {"path": "a"}}
    expected = deterministic_id("read_file", {"path": "a"}, 0)
    assistant = next(m for m in inputs[1] if isinstance(m, ChatMessageAssistant))
    tool = next(m for m in inputs[1] if isinstance(m, ChatMessageTool))
    assert assistant.tool_calls == [
        ToolCall(id=expected, function="read_file", arguments={"path": "a"})
    ]
    assert tool.tool_call_id == expected
