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
from inspect_ai.tool._tool_info import ToolInfo

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


# The second-turn request litellm 1.91.5 (mini-swe-agent 2.2.3's client) sends for
# `gemini/<model>`: tools, functionCall and functionResponse are snake_case.
_LITELLM_REQUEST: dict[str, object] = {
    "contents": [
        {"role": "user", "parts": [{"text": "List files."}]},
        {
            "role": "model",
            "parts": [
                {
                    "function_call": {"name": "bash", "args": {"command": "ls"}},
                    "thoughtSignature": "c2lnLTE=",
                }
            ],
        },
        {
            "role": "user",
            "parts": [
                {
                    "function_response": {
                        "name": "bash",
                        "response": {"content": "a.txt\nb.txt"},
                    }
                }
            ],
        },
    ],
    "tools": [
        {
            "function_declarations": [
                {
                    "name": "bash",
                    "description": "Execute a bash command",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "The bash command to execute",
                            }
                        },
                        "required": ["command"],
                    },
                }
            ]
        }
    ],
}


@pytest.mark.anyio
async def test_google_bridge_reads_snake_case_litellm_request() -> None:
    from inspect_ai.agent._agent import AgentState
    from inspect_ai.agent._bridge.google_api_impl import (
        inspect_google_api_request_impl,
    )
    from inspect_ai.agent._bridge.types import AgentBridge
    from inspect_ai.model._chat_message import ChatMessageUser
    from inspect_ai.model._model import get_model

    calls: list[dict[str, object]] = []

    def _capture(input, tools, tool_choice, config):
        calls.append({"input": input, "tools": tools})
        return ModelOutput.from_content(model="mockllm/model", content="done")

    model = get_model("mockllm/model", custom_outputs=_capture)
    bridge = AgentBridge(
        state=AgentState(messages=[ChatMessageUser(content="hi")]),
        model=str(model),
    )
    bridge.model_aliases = {"inspect": model}

    await inspect_google_api_request_impl(
        json_data={"model": "inspect", **_LITELLM_REQUEST},
        web_search_providers=None,
        code_execution_providers=None,
        bridge=bridge,
    )

    assert len(calls) == 1
    call = calls[0]
    tools = call["tools"]
    assert isinstance(tools, list)
    assert [tool.name for tool in tools] == ["bash"]
    assert tools[0].parameters.required == ["command"]

    input = call["input"]
    assert isinstance(input, list)
    assistant = next(m for m in input if isinstance(m, ChatMessageAssistant))
    assert assistant.tool_calls is not None
    assert assistant.tool_calls[0].function == "bash"
    tool_message = input[-1]
    assert isinstance(tool_message, ChatMessageTool)
    assert tool_message.tool_call_id == assistant.tool_calls[0].id


@pytest.mark.parametrize("google_tool", [{"codeExecution": {}}, {"code_execution": {}}])
def test_google_bridge_reads_code_execution_tool(
    google_tool: dict[str, object],
) -> None:
    from inspect_ai.agent._bridge.google_api_impl import tools_from_google_tools
    from inspect_ai.tool._tool_def import ToolDef

    tools = tools_from_google_tools(
        [google_tool],
        web_search_providers=None,
        code_execution_providers={"google": True},
    )
    assert len(tools) == 1
    tool = tools[0]
    assert not isinstance(tool, ToolInfo)
    assert ToolDef(tool).name == "code_execution"
