"""Reasoning round trips through the LiteLLM proxy.

The proxy translates requests and responses in both directions, so a correct
request from Inspect does not show that the upstream model got its reasoning
back. These tests compare what the upstream provider returned on one turn with
what LiteLLM sent it on the next (see `test_helpers.litellm_proxy.artifacts`).
"""

import copy
import os
import uuid
from collections.abc import Callable, Iterator
from typing import Any, Literal, NamedTuple

import pytest
from test_helpers.litellm_proxy.artifacts import (
    GEMINI_PLACEHOLDER_SIGNATURE,
    ReplayError,
    check_anthropic_replay,
    check_bedrock_converse_replay,
    check_gemini_replay,
    check_openai_responses_replay,
    check_reasoning_content_replay,
)
from test_helpers.litellm_proxy.proxy import (
    LiteLLMProxy,
    UpstreamExchange,
    isolate_model_info,
    run_litellm_proxy,
    skip_if_no_litellm_proxy,
    upstream_exchange,
)
from test_helpers.litellm_proxy.stubs import (
    FakeUpstream,
    anthropic_response,
    bedrock_converse_response,
    fake_upstream,
    gemini_response,
    openai_responses_response,
    reasoning_content_chat_response,
)
from test_helpers.utils import skip_if_no_openai_package

from inspect_ai.model import (
    ChatMessage,
    ChatMessageUser,
    GenerateConfig,
    Model,
    ModelOutput,
    execute_tools,
    get_model,
)
from inspect_ai.tool import Tool, tool

CALL_ID = "x-litellm-call-id"


@pytest.fixture(autouse=True)
def isolated_model_info(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_model_info(monkeypatch)


# Checker unit tests: hand-built payloads in each provider's wire format ------

ANTHROPIC_RESPONSE: dict[str, Any] = {
    "content": [
        {"type": "thinking", "thinking": "Need the weather.", "signature": "sig-1"},
        {"type": "redacted_thinking", "data": "opaque-1"},
        {"type": "text", "text": "Checking."},
        {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {}},
    ]
}

ANTHROPIC_NEXT_REQUEST: dict[str, Any] = {
    "messages": [
        {"role": "user", "content": "Weather?"},
        {"role": "assistant", "content": copy.deepcopy(ANTHROPIC_RESPONSE["content"])},
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "Sunny"}
            ],
        },
    ]
}


def test_anthropic_replay_passes_when_unchanged() -> None:
    assert check_anthropic_replay(ANTHROPIC_RESPONSE, ANTHROPIC_NEXT_REQUEST) == 2


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda c: c.pop(0), id="dropped-thinking"),
        pytest.param(lambda c: c.pop(1), id="dropped-redacted"),
        pytest.param(lambda c: c[0].update(signature="other"), id="altered-signature"),
        pytest.param(lambda c: c.insert(0, c.pop(1)), id="reordered"),
        pytest.param(lambda c: c.append(c.pop(0)), id="after-tool-use"),
    ],
)
def test_anthropic_replay_detects_loss(mutate: Any) -> None:
    request = copy.deepcopy(ANTHROPIC_NEXT_REQUEST)
    mutate(request["messages"][1]["content"])
    with pytest.raises(ReplayError):
        check_anthropic_replay(ANTHROPIC_RESPONSE, request)


GEMINI_RESPONSE: dict[str, Any] = {
    "candidates": [
        {
            "content": {
                "role": "model",
                "parts": [
                    {
                        "functionCall": {
                            "name": "get_weather",
                            "args": {"city": "Paris"},
                        },
                        "thoughtSignature": "gsig-1",
                    },
                    {"functionCall": {"name": "get_weather", "args": {"city": "Rome"}}},
                ],
            }
        }
    ]
}

GEMINI_NEXT_REQUEST: dict[str, Any] = {
    "contents": [
        {"role": "user", "parts": [{"text": "Weather in Paris and Rome?"}]},
        copy.deepcopy(GEMINI_RESPONSE["candidates"][0]["content"]),
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": "get_weather",
                        "response": {"content": "Sunny"},
                    }
                }
            ],
        },
    ]
}


def test_gemini_replay_passes_when_unchanged() -> None:
    assert check_gemini_replay(GEMINI_RESPONSE, GEMINI_NEXT_REQUEST) == 1


def test_gemini_replay_accepts_snake_case_function_calls() -> None:
    request = copy.deepcopy(GEMINI_NEXT_REQUEST)
    for part in request["contents"][1]["parts"]:
        part["function_call"] = part.pop("functionCall")
    assert check_gemini_replay(GEMINI_RESPONSE, request) == 1


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda p: p[0].pop("thoughtSignature"), id="dropped"),
        pytest.param(
            lambda p: p[0].update(thoughtSignature=GEMINI_PLACEHOLDER_SIGNATURE),
            id="placeholder",
        ),
        pytest.param(
            lambda p: (p[1].update(thoughtSignature=p[0].pop("thoughtSignature"))),
            id="moved-to-other-call",
        ),
    ],
)
def test_gemini_replay_detects_loss(mutate: Any) -> None:
    request = copy.deepcopy(GEMINI_NEXT_REQUEST)
    mutate(request["contents"][1]["parts"])
    with pytest.raises(ReplayError):
        check_gemini_replay(GEMINI_RESPONSE, request)


OPENAI_RESPONSE: dict[str, Any] = {
    "output": [
        {
            "type": "reasoning",
            "id": "rs_1",
            "encrypted_content": "enc-1",
            "summary": [],
        },
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "get_weather",
            "arguments": "{}",
        },
    ]
}

OPENAI_NEXT_REQUEST: dict[str, Any] = {
    "input": [
        {"role": "user", "content": "Weather?"},
        {
            "type": "reasoning",
            "id": "rs_1",
            "encrypted_content": "enc-1",
            "summary": [],
        },
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "get_weather",
            "arguments": "{}",
        },
        {"type": "function_call_output", "call_id": "call_1", "output": "Sunny"},
    ]
}


def test_openai_responses_replay_passes_when_unchanged() -> None:
    assert check_openai_responses_replay(OPENAI_RESPONSE, OPENAI_NEXT_REQUEST) == 1


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda items: items.pop(1), id="dropped"),
        pytest.param(
            lambda items: items[1].update(encrypted_content="x"), id="altered"
        ),
        pytest.param(lambda items: items.insert(3, items.pop(1)), id="after-call"),
    ],
)
def test_openai_responses_replay_detects_loss(mutate: Any) -> None:
    request = copy.deepcopy(OPENAI_NEXT_REQUEST)
    mutate(request["input"])
    with pytest.raises(ReplayError):
        check_openai_responses_replay(OPENAI_RESPONSE, request)


BEDROCK_RESPONSE: dict[str, Any] = {
    "output": {
        "message": {
            "role": "assistant",
            "content": [
                {
                    "reasoningContent": {
                        "reasoningText": {"text": "Hmm.", "signature": "bsig"}
                    }
                },
                {"reasoningContent": {"redactedContent": "b3BhcXVl"}},
                {
                    "toolUse": {
                        "toolUseId": "tooluse_1",
                        "name": "get_weather",
                        "input": {},
                    }
                },
            ],
        }
    }
}

BEDROCK_NEXT_REQUEST: dict[str, Any] = {
    "messages": [
        {"role": "user", "content": [{"text": "Weather?"}]},
        copy.deepcopy(BEDROCK_RESPONSE["output"]["message"]),
        {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": "tooluse_1",
                        "content": [{"text": "Sunny"}],
                    }
                }
            ],
        },
    ]
}


def test_bedrock_replay_passes_when_unchanged() -> None:
    assert check_bedrock_converse_replay(BEDROCK_RESPONSE, BEDROCK_NEXT_REQUEST) == 2


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda c: c.pop(0), id="dropped"),
        pytest.param(
            lambda c: c[0]["reasoningContent"]["reasoningText"].update(signature="x"),
            id="altered",
        ),
        pytest.param(lambda c: c.append(c.pop(0)), id="after-tool-use"),
    ],
)
def test_bedrock_replay_detects_loss(mutate: Any) -> None:
    request = copy.deepcopy(BEDROCK_NEXT_REQUEST)
    mutate(request["messages"][1]["content"])
    with pytest.raises(ReplayError):
        check_bedrock_converse_replay(BEDROCK_RESPONSE, request)


REASONING_CONTENT_RESPONSE: dict[str, Any] = {
    "choices": [
        {
            "message": {
                "role": "assistant",
                "content": None,
                "reasoning_content": "The user wants the weather.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": "{}"},
                    }
                ],
            }
        }
    ]
}

REASONING_CONTENT_NEXT_REQUEST: dict[str, Any] = {
    "messages": [
        {"role": "user", "content": "Weather?"},
        copy.deepcopy(REASONING_CONTENT_RESPONSE["choices"][0]["message"]),
        {"role": "tool", "tool_call_id": "call_1", "content": "Sunny"},
    ]
}


def test_reasoning_content_replay_passes_when_unchanged() -> None:
    assert (
        check_reasoning_content_replay(
            REASONING_CONTENT_RESPONSE, REASONING_CONTENT_NEXT_REQUEST
        )
        == 1
    )


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda m: m.pop("reasoning_content"), id="dropped"),
        pytest.param(lambda m: m.update(reasoning_content="other"), id="altered"),
    ],
)
def test_reasoning_content_replay_detects_loss(mutate: Any) -> None:
    request = copy.deepcopy(REASONING_CONTENT_NEXT_REQUEST)
    mutate(request["messages"][1])
    with pytest.raises(ReplayError):
        check_reasoning_content_replay(REASONING_CONTENT_RESPONSE, request)


# Proxy round trips against fake upstreams ----------------------------------


@tool
def get_weather() -> Tool:
    async def execute(city: str) -> str:
        """Get the current weather for a city.

        Args:
            city: Name of the city.
        """
        return f"It is sunny in {city}."

    return execute


class ProxyTurns(NamedTuple):
    first: UpstreamExchange
    second: UpstreamExchange
    first_output: ModelOutput


async def _generate(
    proxy: LiteLLMProxy, model: Model, messages: list[ChatMessage], **kwargs: Any
) -> tuple[ModelOutput, UpstreamExchange]:
    assert proxy.capture_dir is not None
    call_id = f"inspect-{uuid.uuid4().hex}"
    output = await model.generate(
        messages, config=GenerateConfig(extra_headers={CALL_ID: call_id}), **kwargs
    )
    return output, upstream_exchange(proxy.capture_dir, call_id)


# Prompts that need real deduction, so models with adaptive reasoning (Claude 5,
# GPT-6) reason before answering rather than skipping it.
TOOL_PROMPT = (
    "Ana, Ben, Cleo and Dev each live in a different one of Oslo, Lisbon, "
    "Budapest and Quito. The person in Quito has a name one letter shorter than "
    "the person in Lisbon. Ben's city name is longer than Ana's. Dev does not "
    "live in a city containing the letter 'o'. Work out who lives where, then "
    "use the tool to get the weather in Ana's city and in Ben's city."
)
TEXT_PROMPT = (
    "Five runners (P, Q, R, S, T) finished a race with no ties. Q finished "
    "directly after P. R finished before S but after T. P did not finish first "
    "and S did not finish last. What was the finishing "
    "order? Answer with the order only."
)
TEXT_FOLLOW_UP = "Who finished directly before R?"

# Makes Claude return redacted thinking (documented by Anthropic for testing)
REDACTED_THINKING_TRIGGER = "ANTHROPIC_MAGIC_STRING_TRIGGER_REDACTED_THINKING_46C9A13E193C177646C7398A98432ECCCE4C1253D5E2D82641AC0E52CC2876CB"


async def run_tool_loop(
    proxy: LiteLLMProxy, model: Model, prompt: str = TOOL_PROMPT
) -> ProxyTurns:
    """Generate, run the requested tools, generate again."""
    tools = [get_weather()]
    messages: list[ChatMessage] = [ChatMessageUser(content=prompt)]
    first_output, first = await _generate(proxy, model, messages, tools=tools)
    messages.append(first_output.message)
    tool_messages, _ = await execute_tools(messages, tools)
    messages.extend(tool_messages)
    _, second = await _generate(proxy, model, messages, tools=tools)
    return ProxyTurns(first=first, second=second, first_output=first_output)


async def run_text_turns(proxy: LiteLLMProxy, model: Model) -> ProxyTurns:
    """Generate, add a user follow-up, generate again."""
    messages: list[ChatMessage] = [ChatMessageUser(content=TEXT_PROMPT)]
    first_output, first = await _generate(proxy, model, messages)
    messages += [first_output.message, ChatMessageUser(content=TEXT_FOLLOW_UP)]
    _, second = await _generate(proxy, model, messages)
    return ProxyTurns(first=first, second=second, first_output=first_output)


SCENARIOS = {"tool_loop": run_tool_loop, "text": run_text_turns}


class FakeProvider(NamedTuple):
    name: str
    litellm_params: Callable[[str], dict[str, Any]]
    """Deployment params, given the fake upstream's base URL."""

    served: Callable[[dict[str, Any]], dict[str, Any]]
    """The response the fake served for an upstream request."""

    check: Callable[[dict[str, Any], dict[str, Any]], int]
    responses_api: tuple[bool, ...] = (False, True)
    stream: tuple[bool, ...] = (False, True)


FAKE_PROVIDERS = [
    FakeProvider(
        name="anthropic",
        litellm_params=lambda url: {
            "model": "anthropic/claude-sonnet-4-5",
            "api_base": url,
            "api_key": "fake",
        },
        served=anthropic_response,
        check=check_anthropic_replay,
    ),
    FakeProvider(
        name="gemini",
        litellm_params=lambda url: {
            "model": "gemini/gemini-3-pro-preview",
            "api_base": f"{url}/v1beta",
            "api_key": "fake",
        },
        served=gemini_response,
        check=check_gemini_replay,
    ),
    # OpenAI upstreams only ever carry reasoning on the Responses API
    FakeProvider(
        name="openai",
        litellm_params=lambda url: {
            "model": "openai/gpt-5",
            "api_base": f"{url}/v1",
            "api_key": "fake",
        },
        served=openai_responses_response,
        check=check_openai_responses_replay,
        responses_api=(True,),
    ),
    # an open model behind a provider LiteLLM bridges from Responses to chat
    FakeProvider(
        name="deepseek",
        litellm_params=lambda url: {
            "model": "deepseek/deepseek-reasoner",
            "api_base": f"{url}/v1",
            "api_key": "fake",
        },
        served=reasoning_content_chat_response,
        check=check_reasoning_content_replay,
    ),
    # the fake speaks Converse JSON only, not the eventstream encoding
    FakeProvider(
        name="bedrock",
        litellm_params=lambda url: {
            "model": "bedrock/converse/anthropic.claude-sonnet-4-5-20250929-v1:0",
            "api_base": url,
            "aws_access_key_id": "fake",
            "aws_secret_access_key": "fake",
            "aws_region_name": "us-east-1",
        },
        served=bedrock_converse_response,
        check=check_bedrock_converse_replay,
        stream=(False,),
    ),
]


class FakeProxy(NamedTuple):
    proxy: LiteLLMProxy
    upstream: FakeUpstream


@pytest.fixture(scope="module")
def fake_proxy(tmp_path_factory: pytest.TempPathFactory) -> Iterator[FakeProxy]:
    with fake_upstream() as upstream:
        config = {
            "model_list": [
                {
                    "model_name": f"fake-{provider.name}",
                    "litellm_params": provider.litellm_params(upstream.docker_url),
                }
                for provider in FAKE_PROVIDERS
            ]
        }
        with run_litellm_proxy(
            tmp_path_factory.mktemp("litellm-fake"), config, capture=True
        ) as proxy:
            yield FakeProxy(proxy=proxy, upstream=upstream)


def proxy_model(
    proxy: LiteLLMProxy,
    alias: str,
    reasoning_effort: Literal["medium", "high"] = "medium",
    **model_args: Any,
) -> Model:
    return get_model(
        f"litellm-proxy/{alias}",
        base_url=proxy.base_url,
        api_key=proxy.api_key,
        config=GenerateConfig(max_retries=0, reasoning_effort=reasoning_effort),
        **model_args,
    )


def without_nulls(value: Any) -> Any:
    """Drop null-valued keys (the OpenAI SDK adds them when re-serializing)."""
    if isinstance(value, dict):
        return {k: without_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [without_nulls(v) for v in value]
    return value


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
async def test_capture_records_exact_upstream_traffic(fake_proxy: FakeProxy) -> None:
    turns = await run_tool_loop(
        fake_proxy.proxy, proxy_model(fake_proxy.proxy, "fake-deepseek")
    )
    received = [r.body for r in fake_proxy.upstream.requests]
    assert turns.first.request in received
    assert turns.second.request in received
    assert turns.first.response is not None
    assert without_nulls(turns.first.response) == without_nulls(
        reasoning_content_chat_response(turns.first.request)
    )


class Gap(NamedTuple):
    reason: str
    raises: type[BaseException] | tuple[type[BaseException], ...]


def known_gap(
    family: str,
    responses_api: bool,
    stream: bool,
    scenario: str,
    *,
    redacted: bool,
    checked: bool,
    text_with_tools: bool,
) -> Gap | None:
    """How a round trip is known to fail through LiteLLM (None if it should pass).

    Each gap is a LiteLLM conversion bug, kept as an xfail so a LiteLLM fix
    shows up as an unexpected pass.

    Args:
        family: Provider wire format (a `FakeProvider` name).
        responses_api: Inspect uses the Responses API.
        stream: Inspect streams.
        scenario: `tool_loop` or `text`.
        redacted: The provider returns redacted thinking.
        checked: Replayed reasoning is compared with the response (live
            streaming runs only check that the provider accepts the turn).
        text_with_tools: The model may write text before its tool calls
            (Gemini 2.5 then signs the text part rather than the call).
    """
    if family == "bedrock" and redacted:
        # when redacted blocks sit between signed ones, Bedrock also rejects
        # the turn, so this shows up without a checked response too
        return Gap(
            "LiteLLM #43009: redacted_thinking is not converted to Bedrock "
            "redactedContent",
            (ReplayError, RuntimeError),
        )
    if not checked:
        return None
    if family == "anthropic" and responses_api and stream:
        return Gap(
            "LiteLLM #43010: the streaming Responses bridge doubles the thinking text "
            "(the signature chunk repeats the full text)",
            ReplayError,
        )
    if family == "gemini" and responses_api and (scenario == "text" or text_with_tools):
        return Gap(
            "LiteLLM #43011: the Responses bridge drops thought signatures on text "
            "parts",
            ReplayError,
        )
    return None


def _matrix_param(
    provider: FakeProvider, responses_api: bool, stream: bool, scenario: str
) -> Any:
    # the fakes return redacted thinking for Claude and always serve a
    # response that can be checked, streaming or not
    gap = known_gap(
        provider.name,
        responses_api,
        stream,
        scenario,
        redacted=True,
        checked=True,
        text_with_tools=False,
    )
    return pytest.param(
        provider,
        responses_api,
        stream,
        scenario,
        id=f"{provider.name}-{'responses' if responses_api else 'chat'}"
        f"-{'stream' if stream else 'nostream'}-{scenario}",
        marks=[pytest.mark.xfail(strict=True, reason=gap.reason, raises=gap.raises)]
        if gap
        else [],
    )


MATRIX = [
    _matrix_param(provider, responses_api, stream, scenario)
    for provider in FAKE_PROVIDERS
    for responses_api in provider.responses_api
    for stream in provider.stream
    for scenario in SCENARIOS
]


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
@pytest.mark.parametrize("provider,responses_api,stream,scenario", MATRIX)
async def test_reasoning_round_trip(
    fake_proxy: FakeProxy,
    provider: FakeProvider,
    responses_api: bool,
    stream: bool,
    scenario: str,
) -> None:
    model = proxy_model(
        fake_proxy.proxy,
        f"fake-{provider.name}",
        responses_api=responses_api,
        stream=stream,
    )
    turns = await SCENARIOS[scenario](fake_proxy.proxy, model)
    served = provider.served(turns.first.request)
    assert provider.check(served, turns.second.request) > 0


# Live round trips against real providers -----------------------------------
#
# Same checks through a proxy with real deployments. LiteLLM keeps no raw
# streamed responses, so streaming runs only check that the provider accepts
# the replayed turn (a provider that validates reasoning rejects a lossy one).


async def run_redacted_tool_loop(proxy: LiteLLMProxy, model: Model) -> ProxyTurns:
    return await run_tool_loop(
        proxy, model, f"{REDACTED_THINKING_TRIGGER} {TOOL_PROMPT}"
    )


LIVE_SCENARIOS = SCENARIOS | {"redacted_tool_loop": run_redacted_tool_loop}


class LiveProvider(NamedTuple):
    name: str
    family: str
    """Fake provider whose wire format and known gaps apply."""

    env: tuple[str, ...]
    """Environment variables required to run (and passed to the proxy)."""

    litellm_params: dict[str, Any]
    check: Callable[[dict[str, Any], dict[str, Any]], int]
    responses_api: tuple[bool, ...] = (False, True)
    stream: tuple[bool, ...] = (False, True)
    scenarios: tuple[str, ...] = ("tool_loop", "text")
    gap: Gap | None = None
    """A failure specific to this deployment, for every case."""


AWS_ENV = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION")

LIVE_PROVIDERS = [
    LiveProvider(
        name="claude-sonnet-4-5",
        family="anthropic",
        env=("ANTHROPIC_API_KEY",),
        litellm_params={
            "model": "anthropic/claude-sonnet-4-5",
            "api_key": "os.environ/ANTHROPIC_API_KEY",
        },
        check=check_anthropic_replay,
        scenarios=("tool_loop", "text", "redacted_tool_loop"),
    ),
    LiveProvider(
        name="claude-opus-5-5",
        family="anthropic",
        env=("ANTHROPIC_API_KEY",),
        litellm_params={
            "model": "anthropic/claude-opus-5-5",
            "api_key": "os.environ/ANTHROPIC_API_KEY",
        },
        check=check_anthropic_replay,
    ),
    LiveProvider(
        name="gemini-3-flash",
        family="gemini",
        env=("GOOGLE_API_KEY",),
        litellm_params={
            "model": "gemini/gemini-3-flash-preview",
            "api_key": "os.environ/GOOGLE_API_KEY",
        },
        check=check_gemini_replay,
    ),
    LiveProvider(
        name="gemini-2.5-flash",
        family="gemini",
        env=("GOOGLE_API_KEY",),
        litellm_params={
            "model": "gemini/gemini-2.5-flash",
            "api_key": "os.environ/GOOGLE_API_KEY",
        },
        check=check_gemini_replay,
    ),
    LiveProvider(
        name="gpt-5-mini",
        family="openai",
        env=("OPENAI_API_KEY",),
        litellm_params={
            "model": "openai/gpt-5-mini",
            "api_key": "os.environ/OPENAI_API_KEY",
        },
        check=check_openai_responses_replay,
        responses_api=(True,),
    ),
    LiveProvider(
        name="bedrock-claude-sonnet-4-5",
        family="bedrock",
        env=("ENABLE_BEDROCK_TESTS", *AWS_ENV),
        litellm_params={
            "model": "bedrock/converse/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "aws_access_key_id": "os.environ/AWS_ACCESS_KEY_ID",
            "aws_secret_access_key": "os.environ/AWS_SECRET_ACCESS_KEY",
            "aws_region_name": "os.environ/AWS_DEFAULT_REGION",
        },
        check=check_bedrock_converse_replay,
        scenarios=("tool_loop", "text", "redacted_tool_loop"),
    ),
    LiveProvider(
        name="claude-sonnet-5",
        family="anthropic",
        env=("ANTHROPIC_API_KEY",),
        litellm_params={
            "model": "anthropic/claude-sonnet-5",
            "api_key": "os.environ/ANTHROPIC_API_KEY",
        },
        check=check_anthropic_replay,
        scenarios=("tool_loop", "text", "redacted_tool_loop"),
    ),
    LiveProvider(
        name="claude-fable-5-1",
        family="anthropic",
        env=("ANTHROPIC_API_KEY",),
        litellm_params={
            "model": "anthropic/claude-fable-5-1",
            "api_key": "os.environ/ANTHROPIC_API_KEY",
        },
        check=check_anthropic_replay,
    ),
    LiveProvider(
        name="gemini-3.1-pro",
        family="gemini",
        env=("GOOGLE_API_KEY",),
        litellm_params={
            "model": "gemini/gemini-3.1-pro-preview",
            "api_key": "os.environ/GOOGLE_API_KEY",
        },
        check=check_gemini_replay,
    ),
    LiveProvider(
        name="gemini-3.5-flash",
        family="gemini",
        env=("GOOGLE_API_KEY",),
        litellm_params={
            "model": "gemini/gemini-3.5-flash",
            "api_key": "os.environ/GOOGLE_API_KEY",
        },
        check=check_gemini_replay,
    ),
    LiveProvider(
        name="gpt-6-astra",
        family="openai",
        env=("OPENAI_API_KEY",),
        litellm_params={
            "model": "openai/gpt-6-astra",
            "api_key": "os.environ/OPENAI_API_KEY",
        },
        check=check_openai_responses_replay,
        responses_api=(True,),
    ),
    LiveProvider(
        name="gpt-5.5",
        family="openai",
        env=("OPENAI_API_KEY",),
        litellm_params={
            "model": "openai/gpt-5.5",
            "api_key": "os.environ/OPENAI_API_KEY",
        },
        check=check_openai_responses_replay,
        responses_api=(True,),
    ),
    LiveProvider(
        name="kimi-k2.6",
        family="deepseek",
        env=("MOONSHOT_API_KEY",),
        litellm_params={
            "model": "moonshot/kimi-k2.6",
            "api_key": "os.environ/MOONSHOT_API_KEY",
        },
        check=check_reasoning_content_replay,
    ),
    LiveProvider(
        name="together-deepseek-v4.1-flash",
        family="deepseek",
        env=("TOGETHER_API_KEY",),
        litellm_params={
            "model": "together_ai/deepseek-ai/DeepSeek-V4.1-Flash",
            "api_key": "os.environ/TOGETHER_API_KEY",
        },
        check=check_reasoning_content_replay,
        gap=Gap(
            "LiteLLM rejects reasoning_effort for this model (UnsupportedParamsError); "
            "see reasoning effort normalization in design/litellm-proxy.md",
            Exception,
        ),
    ),
    LiveProvider(
        name="together-gpt-oss-120b",
        family="deepseek",
        env=("TOGETHER_API_KEY",),
        litellm_params={
            "model": "together_ai/openai/gpt-oss-120b",
            "api_key": "os.environ/TOGETHER_API_KEY",
        },
        check=check_reasoning_content_replay,
    ),
]


def _env_available(names: tuple[str, ...]) -> bool:
    return all(os.environ.get(name) for name in names)


@pytest.fixture(scope="module")
def live_proxy(tmp_path_factory: pytest.TempPathFactory) -> Iterator[LiteLLMProxy]:
    available = [p for p in LIVE_PROVIDERS if _env_available(p.env)]
    config = {
        "model_list": [
            {"model_name": f"live-{p.name}", "litellm_params": p.litellm_params}
            for p in available
        ]
    }
    env_vars = sorted({name for p in available for name in p.env})
    with run_litellm_proxy(
        tmp_path_factory.mktemp("litellm-live"),
        config,
        capture=True,
        env_vars=env_vars,
    ) as proxy:
        yield proxy


def _live_param(
    provider: LiveProvider, responses_api: bool, stream: bool, scenario: str
) -> Any:
    gap = provider.gap or known_gap(
        provider.family,
        responses_api,
        stream,
        "tool_loop" if scenario == "redacted_tool_loop" else scenario,
        redacted=scenario == "redacted_tool_loop",
        checked=not stream,
        text_with_tools=True,
    )
    marks: list[Any] = [
        pytest.mark.api,
        pytest.mark.skipif(
            not _env_available(provider.env),
            reason=f"Requires {', '.join(provider.env)}",
        ),
    ]
    if gap:
        # not strict: a real model may not produce the affected content
        marks.append(
            pytest.mark.xfail(strict=False, reason=gap.reason, raises=gap.raises)
        )
    return pytest.param(
        provider,
        responses_api,
        stream,
        scenario,
        id=f"{provider.name}-{'responses' if responses_api else 'chat'}"
        f"-{'stream' if stream else 'nostream'}-{scenario}",
        marks=marks,
    )


LIVE_MATRIX = [
    _live_param(provider, responses_api, stream, scenario)
    for provider in LIVE_PROVIDERS
    for responses_api in provider.responses_api
    for stream in provider.stream
    for scenario in provider.scenarios
]


@skip_if_no_openai_package
@skip_if_no_litellm_proxy
@pytest.mark.parametrize("provider,responses_api,stream,scenario", LIVE_MATRIX)
async def test_live_reasoning_round_trip(
    live_proxy: LiteLLMProxy,
    provider: LiveProvider,
    responses_api: bool,
    stream: bool,
    scenario: str,
) -> None:
    model = proxy_model(
        live_proxy,
        f"live-{provider.name}",
        responses_api=responses_api,
        stream=stream,
        reasoning_effort="high",
    )
    # the second generate raises if the provider rejects the replayed turn
    turns = await LIVE_SCENARIOS[scenario](live_proxy, model)
    if turns.first.response is None:
        assert stream, "no upstream response captured for a non-streaming call"
        return
    if provider.check(turns.first.response, turns.second.request) == 0:
        # e.g. adaptive thinking that chose not to think on this turn
        pytest.skip("the provider returned no reasoning on the first turn")
