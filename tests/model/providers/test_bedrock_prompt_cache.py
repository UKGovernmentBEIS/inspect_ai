"""Bedrock Converse prompt caching.

Placement rules and model gating are covered with a mocked Converse client;
the `@skip_if_no_bedrock` tests at the bottom are the ones that actually prove
caching happens, by asserting a non-zero `cacheReadInputTokens` on a repeat
request. Request-shape assertions alone cannot do that — botocore accepts
shapes the service then ignores or rejects.
"""

from typing import Any, Literal, cast

import pytest

pytest.importorskip("aiobotocore")
pytest.importorskip("botocore")

from test_helpers.utils import skip_if_no_bedrock  # noqa: E402

from inspect_ai.model import (  # noqa: E402
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    get_model,
)
from inspect_ai.model._providers.bedrock import (  # noqa: E402
    BedrockAPI,
    ConverseResponse,
    model_output_from_response,
)
from inspect_ai.tool import ToolInfo  # noqa: E402
from inspect_ai.tool._tool_call import ToolCall  # noqa: E402
from inspect_ai.tool._tool_params import ToolParam, ToolParams  # noqa: E402

CACHE_POINT = {"cachePoint": {"type": "default"}}

# Real Bedrock ids, as returned by `aws bedrock list-inference-profiles`.
# Note the 5-series and the 4.6+ ids carry no date/version suffix at all.
SUPPORTED_MODELS = [
    "anthropic.claude-3-5-haiku-20241022-v1:0",
    "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "eu.anthropic.claude-3-7-sonnet-20250219-v1:0",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "anthropic.claude-sonnet-4-6",
    "us.anthropic.claude-opus-4-7",
    "global.anthropic.claude-opus-4-8",
    # 5-series: the reason the gate is an exclusion list
    "anthropic.claude-opus-5",
    "us.anthropic.claude-sonnet-5",
    "global.anthropic.claude-fable-5",
    "us.amazon.nova-pro-v1:0",
    "global.amazon.nova-2-lite-v1:0",
]

UNSUPPORTED_MODELS = [
    "meta.llama3-1-70b-instruct-v1:0",
    "anthropic.claude-3-sonnet-20240229-v1:0",
    "anthropic.claude-3-haiku-20240307-v1:0",
    "anthropic.claude-3-opus-20240229-v1:0",
    "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "anthropic.claude-instant-v1",
    "anthropic.claude-v2:1",
]


# --- mocked Converse client ------------------------------------------------


class _FakeClient:
    def __init__(self) -> None:
        self.request: dict[str, Any] | None = None

    async def converse(self, **request: Any) -> dict[str, Any]:
        self.request = request
        return _response()


class _FakeClientContext:
    def __init__(self, client: _FakeClient) -> None:
        self.client = client

    async def __aenter__(self) -> _FakeClient:
        return self.client

    async def __aexit__(self, *args: object) -> None:
        return None


class _FakeSession:
    def __init__(self, client: _FakeClient) -> None:
        self.client_instance = client

    def client(self, **kwargs: Any) -> _FakeClientContext:
        return _FakeClientContext(self.client_instance)


class _FakeHooks:
    def start_request(self) -> str:
        return "request-id"

    def user_agent_extra(self, request_id: str) -> str:
        return f"test/{request_id}"

    def end_request(self, request_id: str) -> float:
        return 0.0


def _response(
    *, cache_read: int | None = None, cache_write: int | None = None
) -> dict[str, Any]:
    usage: dict[str, int] = {
        "inputTokens": 11,
        "outputTokens": 7,
        "totalTokens": 18 + (cache_read or 0) + (cache_write or 0),
    }
    if cache_read is not None:
        usage["cacheReadInputTokens"] = cache_read
    if cache_write is not None:
        usage["cacheWriteInputTokens"] = cache_write
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
        "stopReason": "end_turn",
        "usage": usage,
        "metrics": {"latencyMs": 1},
    }


def _make_api(model_name: str) -> tuple[BedrockAPI, _FakeClient]:
    api = BedrockAPI.__new__(BedrockAPI)
    api.model_name = model_name
    api.base_url = None
    api.model_args = {}
    api.read_timeout = 60
    api.connect_timeout = 60
    client = _FakeClient()
    api.session = cast(Any, _FakeSession(client))
    api._http_hooks = cast(Any, _FakeHooks())
    return api, client


def _lookup_tool() -> ToolInfo:
    return ToolInfo(
        name="lookup",
        description="Look up a record.",
        parameters=ToolParams(
            properties={"q": ToolParam(type="string", description="query")},
            required=["q"],
        ),
    )


async def _request(
    *,
    model_name: str = "anthropic.claude-sonnet-4-6",
    input: list[Any],
    config: GenerateConfig | None = None,
    tools: list[ToolInfo] | None = None,
) -> dict[str, Any]:
    api, client = _make_api(model_name)
    await api.generate(
        cast(Any, input), tools or [], "auto", config or GenerateConfig()
    )
    assert client.request is not None
    return client.request


def _count_cache_points(request: dict[str, Any]) -> int:
    total = sum(1 for block in request.get("system", []) or [] if "cachePoint" in block)
    for tool in (request.get("toolConfig") or {}).get("tools", []) or []:
        if "cachePoint" in tool:
            total += 1
    for message in request["messages"]:
        total += sum(1 for block in message["content"] if "cachePoint" in block)
    return total


CONVERSATION = [
    ChatMessageSystem(content="stable instructions"),
    ChatMessageUser(content="stable context"),
    ChatMessageAssistant(content="stable answer"),
    ChatMessageUser(content="dynamic question"),
]


# --- placement -------------------------------------------------------------


@pytest.mark.parametrize("cache_prompt", [None, "auto", True])
async def test_marks_system_lookback_and_rolling_prefixes(
    cache_prompt: Literal["auto"] | bool | None,
) -> None:
    """Three points: static system prefix, lookback, and end of conversation."""
    request = await _request(
        input=CONVERSATION, config=GenerateConfig(cache_prompt=cache_prompt)
    )

    assert request["system"][-1] == CACHE_POINT
    # lookback on the penultimate message, rolling point on the final one
    assert request["messages"][-2]["content"][-1] == CACHE_POINT
    assert request["messages"][-1]["content"][-1] == CACHE_POINT
    # the first message is not a boundary we mark
    assert not any("cachePoint" in b for b in request["messages"][0]["content"])


@pytest.mark.parametrize("model_name", SUPPORTED_MODELS)
async def test_supported_models_are_cached(model_name: str) -> None:
    request = await _request(model_name=model_name, input=CONVERSATION)
    assert _count_cache_points(request) > 0


@pytest.mark.parametrize("model_name", UNSUPPORTED_MODELS)
async def test_unsupported_models_preserve_request_shape(model_name: str) -> None:
    request = await _request(model_name=model_name, input=CONVERSATION)
    assert _count_cache_points(request) == 0


async def test_cache_prompt_false_preserves_request_shape() -> None:
    request = await _request(
        input=CONVERSATION, config=GenerateConfig(cache_prompt=False)
    )
    assert _count_cache_points(request) == 0


async def test_single_message_marks_only_the_static_prefix() -> None:
    """A lone message is volatile, so only the static prefix is marked.

    With one message there is no prior request whose cache this could serve,
    and that message is the per-sample question or document — caching it would
    pay a write premium that is never read back.
    """
    request = await _request(
        input=[
            ChatMessageSystem(content="stable instructions"),
            ChatMessageUser(content="dynamic question"),
        ]
    )

    assert request["system"][-1] == CACHE_POINT
    assert not any("cachePoint" in b for m in request["messages"] for b in m["content"])


async def test_falls_back_to_tools_when_there_is_no_system_prompt() -> None:
    request = await _request(input=CONVERSATION[1:], tools=[_lookup_tool()])

    assert "system" not in request
    assert request["toolConfig"]["tools"][-1] == CACHE_POINT


async def test_nova_never_marks_tools() -> None:
    """Nova never gets a cachePoint in toolConfig.tools.

    Bedrock rejects one outright with
    `Malformed input request: #/toolConfig/tools/0`.
    """
    request = await _request(
        model_name="us.amazon.nova-pro-v1:0",
        input=CONVERSATION[1:],
        tools=[_lookup_tool()],
    )

    assert not any("cachePoint" in t for t in request["toolConfig"]["tools"])
    assert _count_cache_points(request) > 0


async def test_parallel_tool_results_are_not_split() -> None:
    """A parallel tool-call turn's toolResult group is never split.

    Consecutive tool messages collapse into a single user message, so a
    cachePoint placed by block offset rather than message boundary would land
    between the toolResult blocks.
    """
    request = await _request(
        input=[
            ChatMessageUser(content="look up a and b"),
            ChatMessageAssistant(
                content="",
                tool_calls=[
                    ToolCall(id="tooluse_a", function="lookup", arguments={"q": "a"}),
                    ToolCall(id="tooluse_b", function="lookup", arguments={"q": "b"}),
                ],
            ),
            ChatMessageTool(content="ra", tool_call_id="tooluse_a", function="lookup"),
            ChatMessageTool(content="rb", tool_call_id="tooluse_b", function="lookup"),
        ],
        tools=[_lookup_tool()],
    )

    blocks = request["messages"][-1]["content"]
    tool_results = [i for i, b in enumerate(blocks) if "toolResult" in b]
    cache_points = [i for i, b in enumerate(blocks) if "cachePoint" in b]
    assert len(tool_results) == 2
    # every cachePoint sits after the whole toolResult group, never inside it
    assert all(i > max(tool_results) for i in cache_points)


@pytest.mark.parametrize("model_name", SUPPORTED_MODELS)
async def test_never_exceeds_bedrock_cache_point_limit(model_name: str) -> None:
    """Claude rejects a fifth cachePoint with a ValidationException."""
    long_conversation: list[Any] = [ChatMessageSystem(content="stable instructions")]
    for i in range(6):
        long_conversation.append(ChatMessageUser(content=f"q{i}"))
        long_conversation.append(ChatMessageAssistant(content=f"a{i}"))

    request = await _request(
        model_name=model_name, input=long_conversation, tools=[_lookup_tool()]
    )
    assert _count_cache_points(request) <= 4


# --- usage accounting ------------------------------------------------------


def test_cache_usage_is_reported_and_counted_in_total() -> None:
    output = model_output_from_response(
        "m", ConverseResponse(**_response(cache_read=100, cache_write=25)), []
    )
    usage = output.usage
    assert usage is not None
    # input_tokens excludes cache reads/writes; total sums all four
    assert usage.input_tokens == 11
    assert usage.input_tokens_cache_read == 100
    assert usage.input_tokens_cache_write == 25
    assert usage.total_tokens == 11 + 100 + 25 + 7


def test_missing_cache_usage_fields_remain_compatible() -> None:
    """Some models omit the fields entirely rather than reporting 0."""
    output = model_output_from_response("m", ConverseResponse(**_response()), [])
    usage = output.usage
    assert usage is not None
    assert usage.input_tokens_cache_read is None
    assert usage.input_tokens_cache_write is None
    assert usage.total_tokens == 18


def test_zero_cache_usage_fields_are_preserved() -> None:
    output = model_output_from_response(
        "m", ConverseResponse(**_response(cache_read=0, cache_write=0)), []
    )
    usage = output.usage
    assert usage is not None
    assert usage.input_tokens_cache_read == 0
    assert usage.input_tokens_cache_write == 0
    assert usage.total_tokens == 18


# --- live -----------------------------------------------------------------
#
# The only tests that can show caching actually works. Prefixes must clear the
# model's minimum cacheable length (1024 tokens on sonnet-4-6, 4096 on
# haiku-4-5) or Bedrock silently declines to cache with no error.

LIVE_MODEL = "bedrock/us.anthropic.claude-sonnet-4-6"


def _filler(marker: str, tokens: int) -> str:
    line = f"Note {marker}: inventory audit line covering warehouse aisle number "
    return " ".join(line + str(i) + "." for i in range(max(1, tokens // 15)))


@pytest.mark.anyio
@skip_if_no_bedrock
async def test_bedrock_live_multi_turn_reads_cache() -> None:
    """A second turn re-reads the history cached by the first."""
    model = get_model(LIVE_MODEL, config=GenerateConfig(max_tokens=16))
    messages: list[Any] = [
        ChatMessageSystem(content="You are an auditor. " + _filler("live-sys", 1500)),
        ChatMessageUser(content="Audit aisle 1. " + _filler("live-u0", 600)),
    ]
    first = await model.generate(messages, tools=[], cache=False)
    assert first.usage is not None

    messages += [
        ChatMessageAssistant(content="Checked. " + _filler("live-a0", 400)),
        ChatMessageUser(content="Next please."),
    ]
    second = await model.generate(messages, tools=[], cache=False)
    assert second.usage is not None
    assert (second.usage.input_tokens_cache_read or 0) > 0, (
        "second turn did not read the prefix cached by the first"
    )


@pytest.mark.anyio
@skip_if_no_bedrock
async def test_bedrock_live_shared_system_prompt_reads_cache() -> None:
    """The single-turn eval shape: one system prompt, many varying questions.

    The question must stay uncached — caching it would pay a write premium on
    content no later request ever reads.
    """
    model = get_model(LIVE_MODEL, config=GenerateConfig(max_tokens=16))
    system = ChatMessageSystem(
        content="You are an auditor. " + _filler("live-shared", 2000)
    )
    await model.generate(
        [system, ChatMessageUser(content="Question 0. " + _filler("live-q0", 300))],
        tools=[],
        cache=False,
    )
    second = await model.generate(
        [system, ChatMessageUser(content="Question 1. " + _filler("live-q1", 300))],
        tools=[],
        cache=False,
    )
    assert second.usage is not None
    assert (second.usage.input_tokens_cache_read or 0) > 0, (
        "shared system prompt was not served from cache"
    )


@pytest.mark.anyio
@skip_if_no_bedrock
async def test_bedrock_live_cache_prompt_false_does_not_cache() -> None:
    model = get_model(
        LIVE_MODEL, config=GenerateConfig(max_tokens=16, cache_prompt=False)
    )
    messages: list[Any] = [
        ChatMessageSystem(content="You are an auditor. " + _filler("live-off", 1500)),
        ChatMessageUser(content="Hello."),
        ChatMessageAssistant(content="Hi."),
        ChatMessageUser(content="Reply OK."),
    ]
    await model.generate(messages, tools=[], cache=False)
    output = await model.generate(messages, tools=[], cache=False)
    assert output.usage is not None
    assert not output.usage.input_tokens_cache_read
    assert not output.usage.input_tokens_cache_write


@pytest.mark.anyio
@skip_if_no_bedrock
async def test_bedrock_live_parallel_tool_results_accepted() -> None:
    """Guards the toolResult-group placement against a live ValidationException."""
    model = get_model(LIVE_MODEL, config=GenerateConfig(max_tokens=16))
    messages: list[Any] = [
        ChatMessageSystem(content="You are an auditor. " + _filler("live-par", 1500)),
        ChatMessageUser(content="Look up a and b."),
        ChatMessageAssistant(
            content="",
            tool_calls=[
                ToolCall(id="tooluse_a", function="lookup", arguments={"q": "a"}),
                ToolCall(id="tooluse_b", function="lookup", arguments={"q": "b"}),
            ],
        ),
        ChatMessageTool(content="ra", tool_call_id="tooluse_a", function="lookup"),
        ChatMessageTool(content="rb", tool_call_id="tooluse_b", function="lookup"),
    ]
    output = await model.generate(messages, tools=[_lookup_tool()], cache=False)
    assert output.usage is not None


@pytest.mark.anyio
@skip_if_no_bedrock
async def test_bedrock_live_nova_accepts_cache_points() -> None:
    """Nova rejects a cachePoint in toolConfig.tools; system/messages are fine."""
    model = get_model(
        "bedrock/us.amazon.nova-pro-v1:0", config=GenerateConfig(max_tokens=16)
    )
    messages: list[Any] = [
        ChatMessageUser(content=_filler("live-nova", 2000)),
        ChatMessageAssistant(content="Understood."),
        ChatMessageUser(content="Reply OK."),
    ]
    output = await model.generate(messages, tools=[_lookup_tool()], cache=False)
    assert output.usage is not None
