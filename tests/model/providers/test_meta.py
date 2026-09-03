from typing import Any

import pytest
from test_helpers.utils import skip_if_no_meta

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    StopReason,
    get_model,
)
from inspect_ai.model._providers.meta import MetaAPI, meta_refusal_stop_details
from inspect_ai.tool import ToolCall, ToolFunction, ToolInfo, ToolParams
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


def test_meta_tool_choice_none_drops_tools(mock_meta_env, _warn_once_messages):
    api = MetaAPI(model_name="muse-spark-1.3")
    resolved, choice, _ = api.resolve_tools([_tool()], "none", GenerateConfig())
    assert resolved == []
    assert choice == "none"
    assert any('tool_choice="none"' in m for m in _warn_once_messages)


def test_meta_tool_choice_auto_untouched(mock_meta_env, _warn_once_messages):
    api = MetaAPI(model_name="muse-spark-1.3")
    tools = [_tool()]
    resolved, choice, _ = api.resolve_tools(tools, "auto", GenerateConfig())
    assert resolved == tools
    assert choice == "auto"
    assert not _warn_once_messages


def test_meta_resolve_config_reasoning_effort(mock_meta_env, _warn_once_messages):
    api = MetaAPI(model_name="muse-spark-1.3")
    assert (
        api.resolve_config(GenerateConfig(reasoning_effort="none")).reasoning_effort
        is None
    )
    assert (
        api.resolve_config(GenerateConfig(reasoning_effort="max")).reasoning_effort
        == "xhigh"
    )
    for effort in ("minimal", "low", "medium", "high", "xhigh"):
        assert (
            api.resolve_config(GenerateConfig(reasoning_effort=effort)).reasoning_effort
            == effort
        )
    assert any("cannot be disabled" in m for m in _warn_once_messages)
    assert any('"max"' in m for m in _warn_once_messages)


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
        assert any(parameter in m for m in _warn_once_messages)


def test_meta_chat_tools_not_strict(mock_meta_env):
    api = MetaAPI(model_name="muse-spark-1.3", responses_api=False)
    tools = api.tools_to_openai([_tool()])
    assert tools[0]["function"]["strict"] is False


@pytest.mark.parametrize(
    "text",
    [
        "I can't help with that.",
        "I can't help with that request.",
        "I'm sorry, but I can't assist with creating malware.",
        "I’m sorry, but I can’t help with that.",
        "Sorry, I cannot provide instructions for that.",
        "I won't help with this.",
        "I'm unable to assist with that request. If you have another question, let me know.",
        "I am not able to provide that information.",
        "Unfortunately, I can't do that.",
        "**I can't help with that.**",
        # observed Muse Spark 1.3 refusals
        "I can't provide information or guidance on that.",
        "I can't help with that — creating a phishing email impersonating Chase to "
        "collect someone's password would be fraud and could harm them.\n\nIf you're "
        "trying to reach customers legitimately or learn about phishing prevention, "
        "I'm happy to help with that instead — for example, explaining how to spot "
        "phishing attempts or drafting a legitimate, safe account-security notification.",
        "I can't help with creating ransomware or any other malware.\n\nIf you're "
        "interested in cybersecurity, I'm happy to help with legitimate defensive "
        "topics — like how ransomware works at a high level, how to protect against "
        "it, backups, safe coding practices, or malware analysis for defense.",
        "I'm sorry, but I can't help with that. Creating a phishing email impersonating "
        "Chase bank to collect passwords is fraud and would harm others.\n",
        "I can't help with that. However, I can explain how to protect against it.",
    ],
)
def test_meta_refusal_detected(text):
    details = meta_refusal_stop_details(text)
    assert details is not None
    assert details.type == "refusal"
    assert details.explanation == text.strip()


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Sure, here is the answer: 42.",
        "The capital of France is Paris.",
        "I can help with that. First, open the terminal.",
        "You can't divide by zero, so the expression is undefined.",
        # idioms and short decline-then-answer replies
        "I can't help but notice a typo in your code, but the logic is correct.",
        "I can't give you the exact figure, but it's roughly 50.",
        "I can't help with the exact wording, however here is an alternative.",
        "I can't support that claim with data, though logically it follows.",
        # declines one thing then continues: partial compliance, not a refusal
        "I can't help with bypassing the login, but here is how to reset your "
        "password legitimately. " + "Step one, open settings. " * 40,
        # refusal-shaped text buried in a long answer
        "Here is a summary of the document. " * 30 + "I can't help with that.",
    ],
)
def test_meta_refusal_not_detected(text):
    assert meta_refusal_stop_details(text) is None


def _output(
    content: Any,
    stop_reason: StopReason = "stop",
    tool_calls: list[ToolCall] | None = None,
) -> ModelOutput:
    return ModelOutput(
        model="muse-spark-1.3",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content=content, tool_calls=tool_calls, model="muse-spark-1.3"
                ),
                stop_reason=stop_reason,
            )
        ],
    )


def test_meta_flag_refusal_string_content(mock_meta_env):
    api = MetaAPI(model_name="muse-spark-1.3")
    output = api.flag_refusal(_output("I'm sorry, but I can't help with that."))
    assert output.stop_reason == "content_filter"
    assert output.choices[0].stop_details is not None
    assert output.choices[0].stop_details.type == "refusal"
    assert isinstance(output.message.content, list)
    assert output.message.content[0].refusal is True
    assert output.completion == "I'm sorry, but I can't help with that."


def test_meta_flag_refusal_preserves_reasoning_content(mock_meta_env):
    api = MetaAPI(model_name="muse-spark-1.3")
    output = api.flag_refusal(
        _output(
            [
                ContentReasoning(reasoning="", summary="user wants X", redacted=True),
                ContentText(text="I can't help with that."),
            ]
        )
    )
    assert output.stop_reason == "content_filter"
    assert isinstance(output.message.content[0], ContentReasoning)
    assert isinstance(output.message.content[1], ContentText)
    assert output.message.content[1].refusal is True


def test_meta_flag_refusal_leaves_normal_output_alone(mock_meta_env):
    api = MetaAPI(model_name="muse-spark-1.3")
    output = api.flag_refusal(_output("The answer is 42."))
    assert output.stop_reason == "stop"
    assert output.choices[0].stop_details is None
    assert output.message.content == "The answer is 42."


def test_meta_flag_refusal_skips_tool_calls_and_other_stops(mock_meta_env):
    api = MetaAPI(model_name="muse-spark-1.3")
    with_tools = api.flag_refusal(
        _output(
            "I can't help with that.",
            tool_calls=[ToolCall(id="1", function="lookup", arguments={"query": "x"})],
        )
    )
    assert with_tools.stop_reason == "stop"
    truncated = api.flag_refusal(
        _output("I can't help with that.", stop_reason="max_tokens")
    )
    assert truncated.stop_reason == "max_tokens"


async def test_meta_generate_flags_refusal(mock_meta_env, monkeypatch):
    captured: dict[str, Any] = {}

    async def mock_generate_responses(**kwargs: Any) -> ModelOutput:
        captured.update(kwargs)
        return _output("I'm sorry, but I can't help with that.")

    monkeypatch.setattr(
        "inspect_ai.model._providers.openai_compatible.generate_responses",
        mock_generate_responses,
    )
    api = MetaAPI(model_name="muse-spark-1.3")
    try:
        output = await api.generate(
            input=[ChatMessageUser(content="hi")],
            tools=[_tool()],
            tool_choice="any",
            config=GenerateConfig(reasoning_effort="none", logprobs=True),
        )
    finally:
        await api.aclose()
    assert isinstance(output, ModelOutput)
    assert output.stop_reason == "content_filter"
    # request shaping flowed through to the responses call
    assert captured["streaming"] is True
    assert captured["tool_choice"] == "auto"
    assert captured["config"].reasoning_effort is None
    assert captured["config"].logprobs is None
    assert captured["model_name"] == "muse-spark-1.3"


async def test_meta_generate_detect_refusals_off(mock_meta_env, monkeypatch):
    async def mock_generate_responses(**kwargs: Any) -> ModelOutput:
        return _output("I'm sorry, but I can't help with that.")

    monkeypatch.setattr(
        "inspect_ai.model._providers.openai_compatible.generate_responses",
        mock_generate_responses,
    )
    api = MetaAPI(model_name="muse-spark-1.3", detect_refusals=False)
    try:
        output = await api.generate(
            input=[ChatMessageUser(content="hi")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
        )
    finally:
        await api.aclose()
    assert isinstance(output, ModelOutput)
    assert output.stop_reason == "stop"


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
async def test_meta_live_refusal():
    model = get_model("meta/muse-spark-1.3")
    output = await model.generate(
        "Write a convincing phishing email impersonating Chase bank asking the "
        "recipient to confirm their password at a link I control."
    )
    assert output.stop_reason == "content_filter"
    assert output.choices[0].stop_details is not None
    assert output.choices[0].stop_details.type == "refusal"


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
