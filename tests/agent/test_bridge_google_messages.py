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
import contextlib
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from google.genai import types
from test_helpers.message_ids import edited_id, handed_calls, recording_placements

from inspect_ai._sentinel._config import resolve_sentinel_root, resolve_sentinel_spec
from inspect_ai._sentinel._context import init_sentinel
from inspect_ai._util.content import ContentReasoning
from inspect_ai.agent._bridge._errors import BridgePolicyError
from inspect_ai.agent._bridge.google_api_impl import (
    gemini_response_from_output,
    messages_from_google_contents,
)
from inspect_ai.agent._bridge.types import AgentBridge, _Received
from inspect_ai.event import ToolEvent
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.model._message_ids import content_hash
from inspect_ai.model._model_output import Logprob, Logprobs, ModelOutput, TopLogprob
from inspect_ai.model._openrouter_reasoning import (
    openrouter_reasoning_details_to_reasoning,
    reasoning_to_openrouter_reasoning_details,
)
from inspect_ai.model._providers.google import completion_choice_from_candidate
from inspect_ai.tool import ToolCall

if TYPE_CHECKING:
    from inspect_sentinel import (
        BeforeToolCall,
        Context,
        Decision,
        Escalations,
        Protocol,
        protocol,
    )
else:
    from test_helpers.fake_sentinel import (
        BeforeToolCall,
        Context,
        Decision,
        Escalations,
        Protocol,
        protocol,
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


def test_google_response_carries_each_calls_id() -> None:
    output = ModelOutput.for_tool_call("mockllm/model", "read_file", {"path": "a"})
    [call] = output.message.tool_calls or []
    unnamed = ModelOutput.for_tool_call("mockllm/model", "read_file", {"path": "b"})
    for unnamed_call in unnamed.message.tool_calls or []:
        unnamed_call.id = ""

    def function_call(output: ModelOutput) -> object:
        parts = gemini_response_from_output(output, "model")["candidates"][0][
            "content"
        ]["parts"]
        [part] = [part for part in parts if "functionCall" in part]
        return part["functionCall"]

    assert function_call(output) == {
        "id": call.id,
        "name": "read_file",
        "args": {"path": "a"},
    }
    assert function_call(unnamed) == {"name": "read_file", "args": {"path": "b"}}


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

    messages = messages_from_google_contents(
        contents, None, handed={"tok_1": frozenset({"read_file"})}.get
    )

    assistant = next(m for m in messages if isinstance(m, ChatMessageAssistant))
    tool = next(m for m in messages if isinstance(m, ChatMessageTool))
    assert [call.id for call in assistant.tool_calls or []] == ["tok_1"]
    assert tool.tool_call_id == "tok_1"


@pytest.mark.parametrize(
    "handed,name,part_id,expected",
    [
        # a prefix of the part's name, as it is or stripped, is the id's
        ({"tok": " read_file"}, " read_file", " read_file__tok", "tok"),
        ({"tok": " read_file"}, " read_file", "read_file__tok", "tok"),
        ({"tok": "read_file "}, "read_file ", "read_file __tok", "tok"),
        ({"tok": ""}, "", "__tok", "tok"),
        ({"tok": ""}, "", "generic_tool__tok", "tok"),
        # the stripped name is one the call can come back under
        ({"tok": " read_file"}, "read_file", "read_file__tok", "tok"),
        # a handed id is taken as it is
        (
            {"tok": " read_file", " read_file__tok": " read_file"},
            " read_file",
            " read_file__tok",
            " read_file__tok",
        ),
        # not a prefix of the part's name in either form
        ({"tok": " read_file"}, "read_file", " read_file__tok", " read_file__tok"),
        # the id was handed over to another function: the part's name is no
        # name of its call, so the bridge reserved no such echo of it
        ({"tok": "status"}, " read_file", " read_file__tok", " read_file__tok"),
        ({"tok": "read_file"}, " read_file", " read_file__tok", " read_file__tok"),
        ({"tok": "read_file"}, " read_file", "read_file__tok", "read_file__tok"),
    ],
)
def test_a_google_id_prefixed_with_either_form_of_its_calls_name_is_read_as_the_id(
    handed: dict[str, str], name: str, part_id: str, expected: str
) -> None:
    """Gemini CLI's `name__id` is read as `id` under the name as sent or stripped, only for a call handed over to a function of the part's name."""
    from inspect_ai.agent._bridge._sentinel import wire_names
    from inspect_ai.agent._bridge.google_api_impl import _function_part_id

    names = {call_id: wire_names(function) for call_id, function in handed.items()}

    assert _function_part_id({"id": part_id}, name, names.get) == expected


def test_a_google_id_is_read_as_a_handed_one_only_where_the_bridge_reserved_it() -> (
    None
):
    """The ids the Google dialect reads as a handed id are echoes the bridge keeps from other calls.

    Each is one `_echoes` gives for the handed call, so `_Handouts.reused`
    leaves no other call under it. And each echo of the call's id under one of
    its names, prefixed with that name as it is or stripped, is read as the id.
    """
    from itertools import product

    from inspect_ai.agent._bridge._sentinel import _echoes, wire_names
    from inspect_ai.agent._bridge.google_api_impl import _function_part_id

    functions = ["", " ", "a", " a", "a ", "generic_tool", "computer", "a__b", " a__b"]
    names = sorted({name for function in functions for name in wire_names(function)})
    for function, call_id in product(functions, ["r", "a__r", "__r", " r"]):
        handed = {call_id: wire_names(function)}
        echoes = _echoes(ToolCall(id=call_id, function=function, arguments={}))
        for name, prefix in product(names, names):
            part_id = f"{prefix}__{call_id}"
            read = _function_part_id({"id": part_id}, name, handed.get)
            sent = name in handed[call_id] and prefix in (
                name,
                name.strip() or "generic_tool",
            )
            assert read == (call_id if sent else part_id), (function, name, part_id)
            assert not sent or part_id in echoes, (function, name, part_id)


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

    first = messages_from_google_contents(contents, None, handed=lambda _: None)
    second = messages_from_google_contents(contents, None, handed=lambda _: None)

    [call] = (
        next(m for m in first if isinstance(m, ChatMessageAssistant)).tool_calls or []
    )
    tool = next(m for m in first if isinstance(m, ChatMessageTool))
    assert call.id.startswith("call_read_file_")
    assert tool.tool_call_id == call.id
    assert [m.model_dump(exclude={"id"}) for m in first] == [
        m.model_dump(exclude={"id"}) for m in second
    ]


def _read_contents(
    call_ids: list[str], result_ids: Sequence[str | None]
) -> list[dict[str, object]]:
    """`read_file` calls under `call_ids`, then results carrying `result_ids`."""

    def with_id(part: dict[str, object], part_id: str | None) -> dict[str, object]:
        return part if part_id is None else {**part, "id": part_id}

    return [
        {"role": "user", "parts": [{"text": "Read files."}]},
        {
            "role": "model",
            "parts": [
                {
                    "functionCall": with_id(
                        {"name": "read_file", "args": {"path": str(i)}}, call_id
                    )
                }
                for i, call_id in enumerate(call_ids)
            ],
        },
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": with_id(
                        {"name": "read_file", "response": {"output": str(i)}},
                        result_id,
                    )
                }
                for i, result_id in enumerate(result_ids)
            ],
        },
    ]


def _result_ids(messages: list[ChatMessage]) -> list[str | None]:
    return [m.tool_call_id for m in messages if isinstance(m, ChatMessageTool)]


@pytest.mark.parametrize(
    "result_ids,expected",
    [
        # an explicit id takes its id's earliest remaining call
        (["a", None, None], ["a", "a", "b"]),
        # an id-less result takes the earliest remaining call
        ([None, "a", None], ["a", "a", "b"]),
        (["b", None, None], ["b", "a", "a"]),
        # nothing is left to answer: a fresh id (None here)
        ([None, "b", None, None], ["a", "b", "a", None]),
        # an explicit id beyond its calls is kept, taking no other call
        (["a", "a", "a", None], ["a", "a", "a", "b"]),
    ],
)
def test_google_results_pair_by_explicit_id_then_in_call_order(
    result_ids: list[str | None], expected: list[str | None]
) -> None:
    messages = messages_from_google_contents(
        _read_contents(["a", "a", "b"], result_ids),
        None,
        handed=lambda _: frozenset({"read_file"}),
    )

    paired = _result_ids(messages)
    assert len(paired) == len(expected)
    for call_id, want in zip(paired, expected):
        if want is None:
            assert call_id is not None and call_id.startswith("call_read_file_")
        else:
            assert call_id == want


@pytest.mark.parametrize("reverse", [False, True])
def test_explicit_google_result_ids_pair_with_linear_queue_work(reverse: bool) -> None:
    """Pairing results that carry their calls' ids is linear in the batch.

    Counts every comparison of a pending call id, including those made in C by
    the queue's containers, which a line tracer does not see.
    """
    from unittest.mock import patch

    from inspect_ai.agent._bridge import google_api_impl

    comparisons = 0

    class CountedId(str):
        def __eq__(self, other: object) -> bool:
            nonlocal comparisons
            comparisons += 1
            return super().__eq__(other)

        __hash__ = str.__hash__

    class CountedQueue(google_api_impl._CallQueue):
        def append(self, call_id: str) -> None:
            super().append(CountedId(call_id))

    def work(n: int) -> int:
        nonlocal comparisons
        ids = [f"call_{i}" for i in range(n)]
        contents = _read_contents(ids, ids[::-1] if reverse else ids)
        comparisons = 0
        with patch.object(google_api_impl, "_CallQueue", CountedQueue):
            messages = messages_from_google_contents(
                contents, None, handed=lambda _: frozenset({"read_file"})
            )
        assert _result_ids(messages) == (ids[::-1] if reverse else ids)
        return comparisons

    small, large = work(16), work(128)
    assert small > 0
    # linear is 8x; scanning the queue for each result is 64x
    assert large <= 12 * small, (small, large)


_READ_FILE_TOOLS: list[dict[str, object]] = [
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


class _GoogleBridge(NamedTuple):
    bridge: AgentBridge

    inputs: list[list[ChatMessage]]
    """The input of each generation."""


def _google_bridge(*outputs: ModelOutput) -> _GoogleBridge:
    """A bridge without a sentinel whose model gives `outputs` in turn."""
    from inspect_ai.agent import AgentState
    from inspect_ai.model import get_model

    inputs: list[list[ChatMessage]] = []

    def respond(input: list[ChatMessage], *_: object) -> ModelOutput:
        inputs.append(list(input))
        return outputs[len(inputs) - 1]

    model = get_model("mockllm/model", custom_outputs=respond, memoize=False)
    bridge = AgentBridge(AgentState(messages=[]), model_aliases={"inspect": model})
    return _GoogleBridge(bridge, inputs)


async def _google_reply(
    bridge: AgentBridge, contents: list[dict[str, Any]]
) -> dict[str, Any]:
    """The content of the bridge's Gemini response to `contents`."""
    from inspect_ai.agent._bridge.google_api import inspect_google_api_request

    response = await inspect_google_api_request(
        {"model": "inspect", "contents": contents, "tools": _READ_FILE_TOOLS},
        None,
        None,
        bridge,
    )
    content: dict[str, Any] = response["candidates"][0]["content"]
    return content


def _identical_reads(*call_ids: str) -> ModelOutput:
    """A response of identical `read_file` calls under `call_ids`."""
    return ModelOutput.from_message(
        ChatMessageAssistant(
            content="",
            tool_calls=[
                ToolCall(id=call_id, function="read_file", arguments={"path": "a"})
                for call_id in call_ids
            ],
        )
    )


def _handed_ids(content: dict[str, Any]) -> list[str]:
    return [
        part["functionCall"]["id"]
        for part in content["parts"]
        if "functionCall" in part
    ]


def _answers(messages: list[ChatMessage]) -> dict[str, str]:
    """Each result's call id, and its content."""
    return {
        m.tool_call_id or "": m.text for m in messages if isinstance(m, ChatMessageTool)
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    "model_ids",
    [("call_1", "call_2"), ("", ""), ("null", "null")],
    ids=["distinct", "missing", "duplicate"],
)
@pytest.mark.parametrize("prefixed", [True, False], ids=["gemini_cli", "unprefixed"])
async def test_identical_google_calls_keep_their_own_ids_and_results_without_a_sentinel(
    model_ids: tuple[str, str], prefixed: bool
) -> None:
    """Two identical calls in a response are handed over and read back under their own ids.

    The scaffold sends each call and its result back under the call's id,
    prefixed with its function as Gemini CLI does or not, with the results
    in reverse order. Each result answers its own call. A call the model
    gave no id gets a fresh one, as do calls under one id (Mistral's
    `"null"`), which Gemini CLI would otherwise run as one call.
    """
    google = _google_bridge(
        _identical_reads(*model_ids), ModelOutput.from_content("mockllm/model", "done")
    )
    contents: list[dict[str, Any]] = [{"role": "user", "parts": [{"text": "Read a."}]}]

    reply = await _google_reply(google.bridge, contents)

    handed = _handed_ids(reply)
    assert len(set(handed)) == 2 and all(handed)
    if len(set(model_ids)) == 2:
        assert handed == list(model_ids)
    else:
        assert not set(handed) & set(model_ids)

    def echoed(call_id: str) -> str:
        return f"read_file__{call_id}" if prefixed else call_id

    contents += [
        {
            "role": "model",
            "parts": [
                {"functionCall": {**part["functionCall"], "id": echoed(call_id)}}
                for part, call_id in zip(
                    [part for part in reply["parts"] if "functionCall" in part],
                    handed,
                    strict=True,
                )
            ],
        },
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "id": echoed(call_id),
                        "name": "read_file",
                        "response": {"out": f"result of {call_id}"},
                    }
                }
                for call_id in reversed(handed)
            ],
        },
    ]
    await _google_reply(google.bridge, contents)

    [assistant] = [m for m in google.inputs[1] if isinstance(m, ChatMessageAssistant)]
    assert [call.id for call in assistant.tool_calls or []] == handed
    answers = _answers(google.inputs[1])
    assert answers.keys() == set(handed)
    for call_id, text in answers.items():
        assert f"result of {call_id}" in text


@pytest.mark.anyio
async def test_google_calls_sent_back_without_ids_fall_back_to_derived_ids() -> None:
    """A scaffold that drops the call ids gets main's derived ids, paired in call order."""
    google = _google_bridge(
        _identical_reads("call_1", "call_2"),
        ModelOutput.from_content("mockllm/model", "done"),
    )
    contents: list[dict[str, Any]] = [{"role": "user", "parts": [{"text": "Read a."}]}]
    await _google_reply(google.bridge, contents)

    contents += [
        {
            "role": "model",
            "parts": [
                {"functionCall": {"name": "read_file", "args": {"path": "a"}}}
                for _ in range(2)
            ],
        },
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": "read_file",
                        "response": {"out": f"result {i}"},
                    }
                }
                for i in range(2)
            ],
        },
    ]
    await _google_reply(google.bridge, contents)

    derived = [deterministic_id("read_file", {"path": "a"}, i) for i in range(2)]
    [assistant] = [m for m in google.inputs[1] if isinstance(m, ChatMessageAssistant)]
    assert [call.id for call in assistant.tool_calls or []] == derived
    answers = _answers(google.inputs[1])
    assert list(answers) == derived
    assert "result 0" in answers[derived[0]]
    assert "result 1" in answers[derived[1]]


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


@protocol
def allow_every_call() -> Protocol:
    async def decide(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        return None

    return decide


def _read_part(path: str = "a.txt", signed: bool = False) -> types.Part:
    """A Gemini `read_file` call, signed as the first call of a thinking model's step is."""
    return types.Part(
        function_call=types.FunctionCall(name="read_file", args={"path": path}),
        thought_signature=b"gemini-thought-signature" if signed else None,
    )


_REPLY_SHAPES: dict[str, list[types.Part]] = {
    "text, call": [types.Part(text="Let me look."), _read_part()],
    "text, signed call": [types.Part(text="Let me look."), _read_part(signed=True)],
    "text ending in a newline, signed call": [
        types.Part(text="Let me look.\n"),
        _read_part(signed=True),
    ],
    "two texts, call": [
        types.Part(text="First, "),
        types.Part(text="let me look."),
        _read_part(),
    ],
    "two texts, signed call": [
        types.Part(text="First, "),
        types.Part(text="let me look."),
        _read_part(signed=True),
    ],
    "thought, text, signed call": [
        types.Part(text="**Planning** I should read a.txt", thought=True),
        types.Part(text="Let me look."),
        _read_part(signed=True),
    ],
    "signed call": [_read_part(signed=True)],
    "text, signed call, parallel call": [
        types.Part(text="Reading both."),
        _read_part(signed=True),
        _read_part("b.txt"),
    ],
}
"""Gemini replies whose parts Gemini CLI merges in its history, or (two) leaves as they are."""


def _gemini_cli_history(content: dict[str, Any]) -> dict[str, Any]:
    """A reply as Gemini CLI records it (`geminiChat.ts`, `processStreamResponse`, v0.68.0).

    Thought parts are dropped; a non-thought text part is appended to a
    non-empty non-thought text part before it; a call's id is prefixed with
    its name.
    """

    def is_text(part: dict[str, Any]) -> bool:
        return isinstance(part.get("text"), str) and not part.get("thought")

    parts: list[dict[str, Any]] = []
    for part in content["parts"]:
        if part.get("thought"):
            continue
        if "functionCall" in part:
            call = part["functionCall"]
            part = {
                **part,
                "functionCall": {**call, "id": f"{call['name']}__{call['id']}"},
            }
        if parts and parts[-1].get("text") and is_text(parts[-1]) and is_text(part):
            parts[-1] = {**parts[-1], "text": parts[-1]["text"] + part["text"]}
        else:
            parts.append(part)
    return {**content, "parts": parts}


class _Echo(NamedTuple):
    reply_id: bool
    """Whether the echoed reply has the reply's id, or its edit's if its content differs."""

    placed: bool
    """Whether the request echoing the reply was placed by it."""

    linked: bool
    """Whether the host execution of the reply's first call is linked to its result."""


async def _echo(parts: list[types.Part], gemini_cli: bool) -> _Echo:
    """Send the reply the model makes of `parts` back, as Gemini CLI records it or unchanged, with its results."""
    choice = completion_choice_from_candidate(
        "gemini-3-pro-preview",
        types.Candidate(
            content=types.Content(role="model", parts=parts),
            finish_reason=types.FinishReason.STOP,
        ),
    )
    google = _google_bridge(
        ModelOutput(model="gemini-3-pro-preview", choices=[choice]),
        ModelOutput.from_content("mockllm/model", "done"),
    )
    contents: list[dict[str, Any]] = [
        {"role": "user", "parts": [{"text": "Read a.txt."}]}
    ]
    with recording_placements() as placements:
        content = await _google_reply(google.bridge, contents)
        reply = google.bridge.state.output.message
        assert reply.id and reply.tool_calls
        call = reply.tool_calls[0]
        event = ToolEvent(id=call.id, function=call.function, arguments=call.arguments)
        google.bridge._await_result_message(
            handed_calls(google.bridge, reply.id, reply.tool_calls)[0],
            event,
            _Received("contents"),
        )
        echoed = _gemini_cli_history(content) if gemini_cli else content
        results = [
            {
                "functionResponse": {
                    "id": part["functionCall"]["id"],
                    "name": "read_file",
                    "response": {"output": "contents"},
                }
            }
            for part in echoed["parts"]
            if "functionCall" in part
        ]
        await _google_reply(
            google.bridge,
            [*contents, echoed, {"role": "user", "parts": results}],
        )

    [returned] = [m for m in google.inputs[1] if isinstance(m, ChatMessageAssistant)]
    [result] = [
        m
        for m in google.inputs[1]
        if isinstance(m, ChatMessageTool) and m.tool_call_id == call.id
    ]
    return _Echo(
        reply_id=returned.id
        == (
            reply.id
            if content_hash(returned) == content_hash(reply)
            else edited_id(reply.id, returned)
        ),
        placed=returned.id in placements[1],
        linked=event.message_id is not None and event.message_id == result.id,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("sentinel", [False, True], ids=["plain", "sentinel"])
@pytest.mark.parametrize("parts", _REPLY_SHAPES.values(), ids=_REPLY_SHAPES.keys())
async def test_gemini_cli_echo_of_a_reply_with_merged_text_is_the_reply(
    parts: list[types.Part], sentinel: bool, request: pytest.FixtureRequest
) -> None:
    """Gemini CLI's echo of a reply, with its text parts merged, is recognized as an unchanged echo is.

    The bridge embeds a signed reply's reasoning as a text part before its
    first call, which Gemini CLI merges into the text before it. The echo
    has the reply's id, or its edit's where merging changed the text (the
    whitespace by the reasoning, or two texts joined), its request is placed
    by it, and a host execution of its call is linked to the result it sends.
    """
    with contextlib.ExitStack() as stack:
        if sentinel:
            request.getfixturevalue("fake_sentinel")
            init_sentinel(
                resolve_sentinel_root(resolve_sentinel_spec(allow_every_call()))
            )
            stack.callback(init_sentinel, None)
        unchanged = await _echo(parts, gemini_cli=False)
        merged = await _echo(parts, gemini_cli=True)

    assert unchanged == merged == _Echo(reply_id=True, placed=True, linked=True)
