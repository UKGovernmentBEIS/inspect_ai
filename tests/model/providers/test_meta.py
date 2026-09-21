from typing import Any
from unittest.mock import AsyncMock

import pytest
from test_helpers.utils import skip_if_no_meta

from inspect_ai._util.content import ContentReasoning
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    StopReason,
    get_model,
)
from inspect_ai.model._model_output import StopDetails
from inspect_ai.model._providers.meta import (
    META_UNSUPPORTED_PARAM_WARNING,
    MetaAPI,
    _flag_refusal_stop,
    supports_max_reasoning_effort,
)
from inspect_ai.tool import ToolFunction, ToolInfo, ToolParams
from inspect_ai.util import json_schema


@pytest.fixture
def mock_meta_env(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("META_API_KEY", "test-key")


@pytest.fixture
def _warn_once_messages():
    # warn_once dedupes via a module-level list; clear it and yield it so the
    # test can assert on what was emitted.
    from inspect_ai._util import logger as _inspect_logger

    _inspect_logger._warned.clear()
    yield _inspect_logger._warned
    _inspect_logger._warned.clear()


def _tool() -> ToolInfo:
    return ToolInfo(
        name="lookup",
        description="Look something up.",
        parameters=ToolParams(
            properties={"query": json_schema(str)}, required=["query"]
        ),
    )


def test_meta_defaults(mock_meta_env):
    api = MetaAPI(model_name="muse-spark-1.3")
    assert api.base_url == "https://api.meta.ai/v1"
    assert api.api_key == "test-key"
    assert api.responses_api is True
    assert api.strict_tools is False
    assert api.should_stream(GenerateConfig()) is True
    assert api.resolve_stream(GenerateConfig()) is True
    assert api.canonical_name() == "meta/muse-spark-1.3"


def test_meta_model_args_override_defaults(mock_meta_env):
    api = MetaAPI(model_name="muse-spark-1.3", responses_api=False, stream=False)
    assert api.responses_api is False
    assert api.resolve_stream(GenerateConfig()) is False


def test_meta_accepts_model_api_key(monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.setenv("MODEL_API_KEY", "official-key")
    api = MetaAPI(model_name="muse-spark-1.3")
    assert api.api_key == "official-key"
    assert api.api_key_vars == ["MODEL_API_KEY"]


def test_meta_prefers_meta_api_key(monkeypatch):
    monkeypatch.setenv("META_API_KEY", "inspect-key")
    monkeypatch.setenv("MODEL_API_KEY", "official-key")
    api = MetaAPI(model_name="muse-spark-1.3")
    assert api.api_key == "inspect-key"
    assert api.api_key_vars == ["META_API_KEY"]


def test_meta_missing_api_key_names_both_vars(monkeypatch):
    from inspect_ai._util.error import PrerequisiteError

    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(PrerequisiteError) as ex:
        MetaAPI(model_name="muse-spark-1.3")
    assert "META_API_KEY" in str(ex.value)
    assert "MODEL_API_KEY" in str(ex.value)


def test_meta_api_key_hook_supplies_credentials(monkeypatch):
    """With neither env var set, an api_key hook can still provide the key."""
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setattr("inspect_ai.hooks._hooks.has_api_key_override", lambda: True)
    monkeypatch.setattr(
        "inspect_ai.hooks._hooks.override_api_key",
        lambda env_var_name, value: "hook-key"
        if env_var_name == "META_API_KEY"
        else None,
    )
    api = MetaAPI(model_name="muse-spark-1.3")
    assert api.api_key == "hook-key"


def test_meta_model_info(mock_meta_env):
    from inspect_ai.model._model_info import get_model_info

    info = get_model_info("meta/muse-spark-1.3")
    assert info is not None
    assert info.context_length == 1048576
    assert info.output_tokens == 131072
    assert info.reasoning is True
    alias = get_model_info("meta/muse-spark-1.3-contributor")
    assert alias is not None
    assert alias.context_length == 1048576


def test_meta_forced_tool_choice_downgraded(mock_meta_env, _warn_once_messages):
    api = MetaAPI(model_name="muse-spark-1.3")
    tools = [_tool()]
    _, choice, _ = api.resolve_tools(tools, "any", GenerateConfig())
    assert choice == "auto"
    _, choice, _ = api.resolve_tools(
        tools, ToolFunction(name="lookup"), GenerateConfig()
    )
    assert choice == "auto"
    assert any('"any"' in m for m in _warn_once_messages)
    assert any('"lookup"' in m for m in _warn_once_messages)


def test_meta_tool_choice_auto_untouched(mock_meta_env, _warn_once_messages):
    api = MetaAPI(model_name="muse-spark-1.3")
    tools = [_tool()]
    resolved, choice, _ = api.resolve_tools(tools, "auto", GenerateConfig())
    assert resolved == tools
    assert choice == "auto"
    assert not _warn_once_messages


# Meta documents `max` reasoning for standard-tier muse-spark-1.3 only
MAX_REASONING_MODELS = ["muse-spark-1.3"]
NO_MAX_REASONING_MODELS = [
    "muse-spark-1.3-contributor",
    "muse-spark-1.2",
    "muse-spark-1.2-contributor",
    "muse-spark-1.1",
]


@pytest.mark.parametrize(
    "model,expected",
    [(m, True) for m in MAX_REASONING_MODELS]
    + [(m, False) for m in NO_MAX_REASONING_MODELS],
)
def test_meta_supports_max_reasoning_effort(mock_meta_env, model, expected):
    assert supports_max_reasoning_effort(model) is expected
    assert MetaAPI(model_name=model).supports_max_reasoning_effort() is expected


def test_meta_resolve_config_reasoning_effort(mock_meta_env, _warn_once_messages):
    api = MetaAPI(model_name="muse-spark-1.3")
    assert (
        api.resolve_config(GenerateConfig(reasoning_effort="none")).reasoning_effort
        is None
    )
    # standard-tier 1.3 supports max, so it passes through like the others
    for effort in ("minimal", "low", "medium", "high", "xhigh", "max"):
        assert (
            api.resolve_config(GenerateConfig(reasoning_effort=effort)).reasoning_effort
            == effort
        )
    assert any("cannot be disabled" in m for m in _warn_once_messages)
    assert not any('"max"' in m for m in _warn_once_messages)


@pytest.mark.parametrize("model", NO_MAX_REASONING_MODELS)
def test_meta_resolve_config_max_downgraded_without_support(
    mock_meta_env, _warn_once_messages, model
):
    api = MetaAPI(model_name=model)
    assert (
        api.resolve_config(GenerateConfig(reasoning_effort="max")).reasoning_effort
        == "xhigh"
    )
    assert not any('"max"' in m for m in _warn_once_messages)


def test_meta_resolve_config_drops_logprobs(mock_meta_env, _warn_once_messages):
    api = MetaAPI(model_name="muse-spark-1.3")
    config = api.resolve_config(
        GenerateConfig(logprobs=True, top_logprobs=3, temperature=0.5)
    )
    assert config.logprobs is None
    assert config.top_logprobs is None
    assert config.temperature == 0.5
    assert any("logprobs" in m for m in _warn_once_messages)


def test_meta_resolve_config_noop_when_nothing_to_change(mock_meta_env):
    api = MetaAPI(model_name="muse-spark-1.3")
    config = GenerateConfig(temperature=0.5, reasoning_effort="high")
    assert api.resolve_config(config) is config


def test_meta_chat_completion_params(mock_meta_env, _warn_once_messages):
    api = MetaAPI(model_name="muse-spark-1.3", responses_api=False)
    params = api.completion_params(
        config=GenerateConfig(
            max_tokens=100,
            stop_seqs=["END"],
            logit_bias={1: 1.0},
            num_choices=2,
            temperature=0.5,
        ),
        tools=False,
    )
    assert params["max_completion_tokens"] == 100
    assert "max_tokens" not in params
    assert "stop" not in params
    assert "logit_bias" not in params
    assert "n" not in params
    assert params["temperature"] == 0.5
    for parameter in ("stop", "logit_bias", "n"):
        assert (
            META_UNSUPPORTED_PARAM_WARNING.format(
                parameter=parameter, model="muse-spark-1.3"
            )
            in _warn_once_messages
        )


def test_meta_chat_tools_not_strict(mock_meta_env):
    api = MetaAPI(model_name="muse-spark-1.3", responses_api=False)
    tools = api.tools_to_openai([_tool()])
    assert tools[0]["function"]["strict"] is False


@pytest.mark.parametrize("responses_api", [True, False], ids=["responses", "chat"])
@pytest.mark.parametrize(
    "model,expected",
    [(m, "max") for m in MAX_REASONING_MODELS]
    + [(m, "xhigh") for m in NO_MAX_REASONING_MODELS],
)
async def test_meta_max_reasoning_effort_in_request(
    mock_meta_env, monkeypatch, responses_api, model, expected
):
    """The assembled request carries `max` only where Meta supports it.

    Both protocols are checked at the SDK call: the Chat path is shaped by
    `resolve_config`, the Responses path also by the shared request builder,
    which maps `max` to `xhigh` unless the provider says it is supported.
    """
    from openai.types.chat import ChatCompletion
    from openai.types.responses import Response

    api = MetaAPI(model_name=model, responses_api=responses_api, stream=False)
    if responses_api:
        create = AsyncMock(
            return_value=Response.model_construct(
                id="resp_test",
                model=model,
                created_at=0.0,
                object="response",
                status="completed",
                output=[],
                tools=[],
            )
        )
        monkeypatch.setattr(api.client.responses, "create", create)
    else:
        create = AsyncMock(
            return_value=ChatCompletion(
                id="chat_test",
                model=model,
                created=0,
                object="chat.completion",
                choices=[],
            )
        )
        monkeypatch.setattr(api.client.chat.completions, "create", create)
    try:
        await api.generate(
            input=[ChatMessageUser(content="hi")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(reasoning_effort="max"),
        )
    finally:
        await api.aclose()
    request = create.call_args.kwargs
    assert request["model"] == model
    if responses_api:
        assert request["reasoning"]["effort"] == expected
    else:
        assert request["reasoning_effort"] == expected


async def test_meta_generate_applies_request_shaping(mock_meta_env, monkeypatch):
    """Unsupported options and forced tool choice are fixed up before the request."""
    captured: dict[str, Any] = {}

    async def mock_generate_responses(**kwargs: Any) -> ModelOutput:
        captured.update(kwargs)
        return ModelOutput.from_content(model="muse-spark-1.3", content="ok")

    monkeypatch.setattr(
        "inspect_ai.model._providers.openai_compatible.generate_responses",
        mock_generate_responses,
    )
    api = MetaAPI(model_name="muse-spark-1.3")
    try:
        forced = await api.generate(
            input=[ChatMessageUser(content="hi")],
            tools=[_tool()],
            tool_choice="any",
            config=GenerateConfig(reasoning_effort="none", logprobs=True),
        )
        assert captured["streaming"] is True
        assert captured["tool_choice"] == "auto"
        assert captured["config"].reasoning_effort is None
        assert captured["config"].logprobs is None
        assert captured["model_name"] == "muse-spark-1.3"
        # the degraded forced choice is recorded per-request in the output
        assert isinstance(forced, ModelOutput)
        assert forced.metadata == {
            "tool_choice_degraded": {
                "requested": {"type": "any"},
                "used": {"type": "auto"},
            }
        }
        unforced = await api.generate(
            input=[ChatMessageUser(content="hi")],
            tools=[_tool()],
            tool_choice="auto",
            config=GenerateConfig(),
        )
        assert isinstance(unforced, ModelOutput)
        assert unforced.metadata is None
    finally:
        await api.aclose()


def _output(
    text: str, stop_reason: StopReason, details: StopDetails | None
) -> ModelOutput:
    return ModelOutput(
        model="muse-spark-1.3",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(content=text, model="muse-spark-1.3"),
                stop_reason=stop_reason,
                stop_details=details,
            )
        ],
    )


def test_meta_structured_refusal_becomes_content_filter():
    """A streamed Responses refusal part arrives as `stop`; promote it."""
    output = _output(
        "I'm sorry, but I can't help with that request.",
        "stop",
        StopDetails(type="refusal", explanation="I'm sorry, but I can't help."),
    )
    _flag_refusal_stop(output)
    assert output.stop_reason == "content_filter"


def test_meta_refusal_stop_left_alone_when_already_filtered():
    details = StopDetails(type="content_filter", explanation="blocked")
    output = _output("blocked", "content_filter", details)
    _flag_refusal_stop(output)
    assert output.stop_reason == "content_filter"
    assert output.choices[0].stop_details is details


@pytest.mark.parametrize(
    ("text", "stop_reason", "details"),
    [
        # a plain decline carries no refusal field: left as a normal stop
        ("I can't help with that.", "stop", None),
        ("The answer is 42.", "stop", None),
        # never override a non-stop reason
        ("truncated", "max_tokens", StopDetails(type="refusal", explanation="x")),
    ],
)
def test_meta_refusal_stop_not_promoted(text, stop_reason, details):
    output = _output(text, stop_reason, details)
    _flag_refusal_stop(output)
    assert output.stop_reason == stop_reason


async def test_meta_streamed_policy_block_is_content_filter(mock_meta_env, monkeypatch):
    """The default (streamed Responses) path, end to end, on a policy block.

    Meta's streamed refusal is a completed response whose only content is a
    `refusal` part and whose `model` is null. It must survive `ModelOutput`
    validation (falling back to the requested model) and stop as
    `content_filter`.
    """
    from openai.types.responses import (
        Response,
        ResponseCompletedEvent,
        ResponseOutputMessage,
        ResponseOutputRefusal,
    )

    blocked = Response.model_construct(
        id="resp_blocked",
        created_at=0.0,
        model=None,
        object="response",
        output=[
            ResponseOutputMessage(
                id="msg_1",
                role="assistant",
                status="completed",
                type="message",
                content=[
                    ResponseOutputRefusal(
                        type="refusal", refusal="This request violates our policies."
                    )
                ],
            )
        ],
        tools=[],
        status="completed",
    )

    class _FakeStream:
        async def __aenter__(self) -> "_FakeStream":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        def __aiter__(self) -> Any:
            async def gen() -> Any:
                yield ResponseCompletedEvent(
                    response=blocked, sequence_number=0, type="response.completed"
                )

            return gen()

    captured: dict[str, Any] = {}

    async def create(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _FakeStream()

    api = MetaAPI(model_name="muse-spark-1.3")
    monkeypatch.setattr(api.client.responses, "create", create)
    try:
        result = await api.generate(
            input=[ChatMessageUser(content="hi")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
        )
    finally:
        await api.aclose()

    assert captured["stream"] is True
    assert isinstance(result, tuple)
    output, _ = result
    assert isinstance(output, ModelOutput)
    assert output.model == "muse-spark-1.3"
    assert output.stop_reason == "content_filter"
    details = output.choices[0].stop_details
    assert details is not None and details.type == "refusal"


def test_meta_registered_provider(mock_meta_env):
    model = get_model("meta/muse-spark-1.3")
    assert isinstance(model.api, MetaAPI)
    assert model.api.model_name == "muse-spark-1.3"


@skip_if_no_meta
async def test_meta_live_generate():
    model = get_model("meta/muse-spark-1.3")
    output = await model.generate("Reply with the single word: pong")
    assert "pong" in output.completion.lower()
    assert output.stop_reason == "stop"
    assert output.usage is not None and output.usage.output_tokens > 0


@skip_if_no_meta
async def test_meta_live_max_reasoning_effort():
    """Standard-tier 1.3 accepts `max`; the provider must not downgrade it."""
    model = get_model(
        "meta/muse-spark-1.3", config=GenerateConfig(reasoning_effort="max")
    )
    output = await model.generate("Reply with the single word: pong")
    assert "pong" in output.completion.lower()
    assert output.stop_reason == "stop"


@skip_if_no_meta
async def test_meta_live_reasoning_replay():
    model = get_model("meta/muse-spark-1.3")
    first = await model.generate("What is 17 * 23? Answer with just the number.")
    assert any(isinstance(c, ContentReasoning) for c in first.message.content)
    second = await model.generate(
        [
            ChatMessageUser(content="What is 17 * 23? Answer with just the number."),
            first.message,
            ChatMessageUser(content="Now add 1 to that. Just the number."),
        ]
    )
    assert "392" in second.completion


@skip_if_no_meta
async def test_meta_live_tool_call():
    from inspect_ai.tool import tool

    @tool
    def add():
        async def execute(x: int, y: int) -> int:
            """Add two numbers.

            Args:
                x: First number.
                y: Second number.
            """
            return x + y

        return execute

    model = get_model("meta/muse-spark-1.3")
    output = await model.generate("Use the add tool to compute 2 + 3.", tools=[add()])
    assert output.message.tool_calls
    assert output.message.tool_calls[0].function == "add"
