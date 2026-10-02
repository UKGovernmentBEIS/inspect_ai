"""Gemini tool calling through the LiteLLM proxy.

Thought signatures on replayed tool calls, the function-calling hint,
recovery from MALFORMED_FUNCTION_CALL, which LiteLLM reports as a plain `stop`,
and tool results that are JSON objects, which LiteLLM would otherwise send as
the function response itself (see
`inspect_ai.model._providers._litellm_proxy_gemini`). The proxy alias
deliberately does not contain "gemini": LiteLLM's pre-call hook then strips
the signature it embedded in each tool call id, as it does for production
aliases such as `google/<codename>`.
"""

import base64
import json
from collections.abc import Iterator
from typing import Any, NamedTuple

import pytest
from openai.types.chat import ChatCompletionMessageParam
from test_helpers.litellm_proxy.proxy import (
    LiteLLMProxy,
    isolate_model_info,
    run_litellm_proxy,
    skip_if_no_litellm_proxy,
)
from test_helpers.litellm_proxy.stubs import (
    SSE,
    FakeUpstream,
    StubRequest,
    fake_upstream,
    gemini_response,
)
from test_helpers.utils import skip_if_no_openai_package

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
    Model,
    ModelOutput,
    ModelUsage,
    StopReason,
    execute_tools,
    get_model,
)
from inspect_ai.model._model_output import ChatCompletionChoice
from inspect_ai.model._providers._gemini_function_calling import (
    DEFAULT_MALFORMED_FUNCTION_MESSAGE,
    FUNCTION_CALLING_HINT,
    MALFORMED_FUNCTION_RETRY_PROMPT,
)
from inspect_ai.model._providers._litellm_proxy_gemini import (
    malformed_function_call,
    with_json_tool_results_wrapped,
)
from inspect_ai.tool import Tool, ToolCall, tool

PLACEHOLDER_SIGNATURE = base64.b64encode(b"skip_thought_signature_validator").decode()
TEXT_FUNCTION_CALL = "call:default_api:get_weather{city:Paris}"
# run 1061: an OpenAPI document read with curl; Vertex rejects `$ref` keys in a
# function response (400 "The referenced name ... does not match to a display_name
# in the function_response.parts")
OPENAPI_DOCUMENT = json.dumps(
    {
        "openapi": "3.1.0",
        "paths": {
            "/campaign": {
                "post": {"requestBody": {"$ref": "#/components/schemas/ConfigBody"}}
            }
        },
        "components": {"schemas": {"ConfigBody": {"type": "object"}}},
    },
    indent=4,
)


@pytest.fixture(autouse=True)
def isolated_model_info(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_model_info(monkeypatch)


@tool
def get_weather() -> Tool:
    async def execute(city: str) -> str:
        """Get the current weather for a city.

        Args:
            city: Name of the city.
        """
        return f"It is sunny in {city}."

    return execute


@tool
def get_city_api() -> Tool:
    async def execute(city: str) -> str:
        """Get the OpenAPI document of a city's campaign API.

        Args:
            city: Name of the city.
        """
        return OPENAPI_DOCUMENT

    return execute


# Unit tests for the tool result wrapping -------------------------------------


def test_json_object_tool_results_are_wrapped_for_litellm() -> None:
    messages: list[ChatCompletionMessageParam] = [
        {"role": "user", "content": "{not a tool result}"},
        {"role": "tool", "tool_call_id": "c1", "content": OPENAPI_DOCUMENT},
        {"role": "tool", "tool_call_id": "c2", "content": '  \n{"a": 1}'},
        {"role": "tool", "tool_call_id": "c3", "content": "[1, 2]"},
        {"role": "tool", "tool_call_id": "c4", "content": "{not json"},
        {"role": "tool", "tool_call_id": "c5", "content": "total 0"},
    ]
    wrapped = with_json_tool_results_wrapped(messages)
    assert wrapped[0] == messages[0]
    for index, original in ((1, OPENAPI_DOCUMENT), (2, '  \n{"a": 1}')):
        message, wrapped_message = messages[index], wrapped[index]
        assert message["role"] == "tool" and wrapped_message["role"] == "tool"
        content = wrapped_message["content"]
        assert isinstance(content, str)
        assert json.loads(content) == {"content": original}
        assert wrapped_message["tool_call_id"] == message["tool_call_id"]
    # a list, broken JSON and plain text LiteLLM already sends under `content`
    assert wrapped[3:] == messages[3:]


# Unit tests for the turn classifier ------------------------------------------


def _output(
    content: str | list[Any],
    tool_calls: list[ToolCall] | None = None,
    stop_reason: StopReason = "stop",
) -> ModelOutput:
    return ModelOutput(
        model="google/boston",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(content=content, tool_calls=tool_calls),
                stop_reason=stop_reason,
            )
        ],
    )


def test_malformed_function_call_recognizes_litellm_turns() -> None:
    # run 1040's empty turns: reasoning (summary and signature), no text, no call
    reasoning = [
        ContentReasoning(reasoning="sig", redacted=True, internal="thought_signatures"),
        ContentReasoning(reasoning="**Analyzing**", internal="reasoning_content"),
        ContentText(text=""),
    ]
    assert malformed_function_call(_output(reasoning), None) == (
        DEFAULT_MALFORMED_FUNCTION_MESSAGE
    )
    assert malformed_function_call(_output("\n"), None) == (
        DEFAULT_MALFORMED_FUNCTION_MESSAGE
    )
    # a function call written as text is quoted back
    text = "call:default_api:bash{command:nl -ba lib/compiler.js | sed -n '1,10p'}"
    assert (
        malformed_function_call(_output([*reasoning[:1], ContentText(text=text)]), None)
        == text
    )
    assert (
        malformed_function_call(_output("print(default_api.bash(command='ls'))"), None)
        is not None
    )
    # no choice at all (LiteLLM 1.96 for a content-less candidate)
    assert malformed_function_call(ModelOutput(model="m"), None) == (
        DEFAULT_MALFORMED_FUNCTION_MESSAGE
    )
    # LiteLLM's native finish reason wins even with text
    response = {
        "choices": [
            {
                "provider_specific_fields": {
                    "native_finish_reason": "MALFORMED_FUNCTION_CALL"
                }
            }
        ]
    }
    assert malformed_function_call(_output("Sure."), response) == "Sure."


def test_malformed_function_call_leaves_sound_turns_alone() -> None:
    call = ToolCall(
        id="call_1__thought__sig", function="get_weather", arguments={"city": "Paris"}
    )
    assert malformed_function_call(_output("", [call]), None) is None
    assert malformed_function_call(_output("It is sunny in Paris."), None) is None
    assert malformed_function_call(_output("", stop_reason="max_tokens"), None) is None
    assert (
        malformed_function_call(_output("Let me call the default_api tool."), None)
        is None
    )


# Docker tests against a fake Gemini upstream --------------------------------


class Script:
    """Gemini responses to serve next, in order; the fake's default after that."""

    def __init__(self) -> None:
        self.queue: list[dict[str, Any]] = []

    def route(self, request: StubRequest) -> dict[str, Any] | SSE | None:
        path = request.path.split("?")[0]
        if ":generateContent" not in path and ":streamGenerateContent" not in path:
            return None
        response = self.queue.pop(0) if self.queue else gemini_response(request.body)
        return SSE([(None, response)]) if "streamGenerateContent" in path else response


def malformed_response(with_thought: bool = True) -> dict[str, Any]:
    candidate: dict[str, Any] = {
        "finishReason": "MALFORMED_FUNCTION_CALL",
        "finishMessage": "Malformed function call: print(default_api.get_weather(city='Paris'))",
        "index": 0,
    }
    if with_thought:
        candidate["content"] = {
            "role": "model",
            "parts": [
                {
                    "text": "**Checking the weather**",
                    "thought": True,
                    "thoughtSignature": base64.b64encode(
                        b"malformed-turn-signature"
                    ).decode(),
                }
            ],
        }
    return {
        "candidates": [candidate],
        "usageMetadata": {
            "promptTokenCount": 100,
            "thoughtsTokenCount": 7,
            "totalTokenCount": 107,
        },
        "modelVersion": "stub-gemini",
    }


def tool_call_response() -> dict[str, Any]:
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {"text": "**Checking the weather**", "thought": True},
                        {
                            "functionCall": {
                                "name": "get_weather",
                                "args": {"city": "Paris"},
                            },
                            "thoughtSignature": base64.b64encode(
                                b"recovered-call-signature"
                            ).decode(),
                        },
                    ],
                },
                "finishReason": "STOP",
                "index": 0,
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 100,
            "candidatesTokenCount": 10,
            "thoughtsTokenCount": 10,
            "totalTokenCount": 120,
        },
        "modelVersion": "stub-gemini",
    }


def text_function_call_response() -> dict[str, Any]:
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {"text": "**Checking the weather**", "thought": True},
                        {
                            "text": TEXT_FUNCTION_CALL,
                            "thoughtSignature": base64.b64encode(
                                b"text-call-signature"
                            ).decode(),
                        },
                    ],
                },
                "finishReason": "STOP",
                "index": 0,
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 100,
            "candidatesTokenCount": 11,
            "thoughtsTokenCount": 5,
            "totalTokenCount": 116,
        },
        "modelVersion": "stub-gemini",
    }


class GeminiProxy(NamedTuple):
    proxy: LiteLLMProxy
    upstream: FakeUpstream
    script: Script


@pytest.fixture(scope="module")
def gemini_proxy(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GeminiProxy]:
    script = Script()
    with fake_upstream(script.route) as upstream:
        config = {
            "model_list": [
                {
                    "model_name": "google/fake",
                    "litellm_params": {
                        "model": "gemini/gemini-3-pro-preview",
                        "api_base": f"{upstream.docker_url}/v1beta",
                        "api_key": "fake",
                    },
                }
            ]
        }
        with run_litellm_proxy(
            tmp_path_factory.mktemp("litellm-gemini"), config
        ) as proxy:
            yield GeminiProxy(proxy=proxy, upstream=upstream, script=script)


def gemini_model(proxy: LiteLLMProxy, stream: bool) -> Model:
    return get_model(
        "litellm-proxy/google/fake",
        base_url=proxy.base_url,
        api_key=proxy.api_key,
        config=GenerateConfig(max_retries=0),
        stream=stream,
    )


async def generate(
    gemini: GeminiProxy, model: Model, messages: list[ChatMessage], tools: list[Tool]
) -> tuple[ModelOutput, list[dict[str, Any]]]:
    """Generate and return the upstream requests the turn produced."""
    before = len(gemini.upstream.requests)
    output = await model.generate(messages, tools=tools)
    return output, [r.body for r in gemini.upstream.requests[before:]]


def model_parts(request: dict[str, Any]) -> list[list[dict[str, Any]]]:
    return [c["parts"] for c in request["contents"] if c.get("role") == "model"]


def all_text(value: Any) -> str:
    """Every `text` field in a request, wherever LiteLLM placed it."""
    if isinstance(value, dict):
        return "".join(str(v) if k == "text" else all_text(v) for k, v in value.items())
    if isinstance(value, list):
        return "".join(all_text(v) for v in value)
    return ""


def texts(request: dict[str, Any], role: str) -> list[str]:
    return [
        part["text"]
        for content in request["contents"]
        if content.get("role") == role
        for part in content["parts"]
        if "text" in part and not part.get("thought")
    ]


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
@pytest.mark.parametrize("stream", [False, True], ids=["nostream", "stream"])
async def test_tool_call_signature_survives_replay(
    gemini_proxy: GeminiProxy, stream: bool
) -> None:
    model = gemini_model(gemini_proxy.proxy, stream)
    tools = [get_weather()]
    messages: list[ChatMessage] = [ChatMessageUser(content="Weather in Paris?")]
    first, _ = await generate(gemini_proxy, model, messages, tools)
    messages.append(first.message)
    tool_messages, _ = await execute_tools(messages, tools)
    messages.extend(tool_messages)
    _, requests = await generate(gemini_proxy, model, messages, tools)
    (parts,) = model_parts(requests[0])
    calls = [part for part in parts if "function_call" in part]
    assert len(calls) == 2
    # the fake signs the first of its two parallel calls; without the
    # signature in its own field LiteLLM would send the placeholder instead
    assert calls[0]["thoughtSignature"] == (
        base64.b64encode(b"stub-gemini-signature-1").decode()
    )
    assert calls[0]["thoughtSignature"] != PLACEHOLDER_SIGNATURE


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
async def test_json_object_tool_result_is_sent_under_content(
    gemini_proxy: GeminiProxy,
) -> None:
    model = gemini_model(gemini_proxy.proxy, stream=False)
    tools = [get_city_api()]
    messages: list[ChatMessage] = [ChatMessageUser(content="Read the Paris API.")]
    first, _ = await generate(gemini_proxy, model, messages, tools)
    messages.append(first.message)
    tool_messages, _ = await execute_tools(messages, tools)
    messages.extend(tool_messages)
    _, requests = await generate(gemini_proxy, model, messages, tools)
    responses = [
        (part.get("function_response") or part["functionResponse"])["response"]
        for content in requests[0]["contents"]
        for part in content["parts"]
        if "function_response" in part or "functionResponse" in part
    ]
    # the fake makes two parallel calls; LiteLLM would have sent each document
    # itself as the response, `$ref` keys and all
    assert len(responses) == 2
    assert all(response == {"content": OPENAPI_DOCUMENT} for response in responses)


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
async def test_function_calling_hint_sent_with_tools(gemini_proxy: GeminiProxy) -> None:
    model = gemini_model(gemini_proxy.proxy, stream=False)
    system = ChatMessageSystem(content="Be brief.")
    user = ChatMessageUser(content="Weather in Paris?")
    _, (with_tools,) = await generate(
        gemini_proxy, model, [system, user], [get_weather()]
    )
    # where the system text lands (system_instruction, or the first user turn
    # on LiteLLM 1.96 for a model its map doesn't know) is LiteLLM's business
    hint = FUNCTION_CALLING_HINT.strip()
    assert f"Be brief.\n{FUNCTION_CALLING_HINT}" in all_text(with_tools)
    _, (no_system,) = await generate(gemini_proxy, model, [user], [get_weather()])
    assert hint in all_text(no_system)
    _, (without_tools,) = await generate(gemini_proxy, model, [system, user], [])
    assert "default_api" not in all_text(without_tools)


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
@pytest.mark.parametrize("stream", [False, True], ids=["nostream", "stream"])
@pytest.mark.parametrize("with_thought", [True, False], ids=["thought", "bare"])
async def test_malformed_function_call_is_retried(
    gemini_proxy: GeminiProxy, stream: bool, with_thought: bool
) -> None:
    gemini_proxy.script.queue = [malformed_response(with_thought), tool_call_response()]
    model = gemini_model(gemini_proxy.proxy, stream)
    output, requests = await generate(
        gemini_proxy,
        model,
        [ChatMessageUser(content="Weather in Paris?")],
        [get_weather()],
    )
    assert len(requests) == 2
    assert (
        output.message.tool_calls
        and output.message.tool_calls[0].function == "get_weather"
    )
    retry = requests[1]
    assert texts(retry, "model")[-1].startswith(
        "I attempted to call a function but produced: "
    )
    assert texts(retry, "user")[-1] == MALFORMED_FUNCTION_RETRY_PROMPT
    assert retry["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"
    assert requests[0]["toolConfig"]["functionCallingConfig"]["mode"] == "AUTO"
    assert output.metadata == {"malformed_function_call_attempts": 1}
    # usage counts the discarded attempt (7 reasoning tokens) as well
    assert output.usage is not None
    assert output.usage.output_tokens == 7 + 20


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
async def test_text_function_call_is_retried(gemini_proxy: GeminiProxy) -> None:
    gemini_proxy.script.queue = [text_function_call_response(), tool_call_response()]
    model = gemini_model(gemini_proxy.proxy, stream=True)
    output, requests = await generate(
        gemini_proxy,
        model,
        [ChatMessageUser(content="Weather in Paris?")],
        [get_weather()],
    )
    assert len(requests) == 2
    assert output.message.tool_calls
    assert texts(requests[1], "model")[-1] == (
        f"I attempted to call a function but produced: {TEXT_FUNCTION_CALL}"
    )


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
async def test_malformed_function_call_exhausts_attempts(
    gemini_proxy: GeminiProxy,
) -> None:
    gemini_proxy.script.queue = [malformed_response() for _ in range(3)]
    model = gemini_model(gemini_proxy.proxy, stream=False)
    output, requests = await generate(
        gemini_proxy,
        model,
        [ChatMessageUser(content="Weather in Paris?")],
        [get_weather()],
    )
    assert len(requests) == 3
    assert not output.message.tool_calls
    assert "I seem to have had trouble calling a function" in output.message.text
    assert output.metadata == {"malformed_function_call_attempts": 3}
    assert output.usage == ModelUsage(
        input_tokens=300, output_tokens=21, total_tokens=321, reasoning_tokens=21
    )
    assert gemini_proxy.script.queue == []


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
async def test_sound_turns_are_not_retried(gemini_proxy: GeminiProxy) -> None:
    model = gemini_model(gemini_proxy.proxy, stream=True)
    output, requests = await generate(
        gemini_proxy, model, [ChatMessageUser(content="Hello")], []
    )
    assert len(requests) == 1
    assert output.metadata is None
    assert output.message.text == "Hello! Ask me about the weather."
