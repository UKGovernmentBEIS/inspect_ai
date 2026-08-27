import pytest
from test_helpers.utils import skip_if_no_deepseek

from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    get_model,
)


@pytest.fixture
def mock_deepseek_env(monkeypatch):
    """Mock required DeepSeek environment variables."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")


@pytest.fixture
def _warn_once_messages():
    # warn_once dedupes via a module-level list; clear it and yield it so the
    # test can assert on what was emitted. caplog isn't reliable here because
    # init_logger sets propagate=False on the inspect_ai logger once any
    # earlier test triggers it.
    from inspect_ai._util import logger as _inspect_logger

    _inspect_logger._warned.clear()
    yield _inspect_logger._warned
    _inspect_logger._warned.clear()


def test_deepseek_base_url_default(mock_deepseek_env):
    from inspect_ai.model._providers.deepseek import DeepSeekAPI

    api = DeepSeekAPI(model_name="deepseek-v4-pro")
    assert api.base_url == "https://api.deepseek.com"


def test_deepseek_canonical_name(mock_deepseek_env):
    from inspect_ai.model._providers.deepseek import DeepSeekAPI

    api = DeepSeekAPI(model_name="deepseek-v4-pro")
    assert api.canonical_name() == "deepseek/deepseek-v4-pro"


def test_deepseek_reasoning_effort_mapping(mock_deepseek_env):
    """Documented effort values pass through; others map to the nearest one."""
    from inspect_ai.model._providers.deepseek import DeepSeekAPI

    api = DeepSeekAPI(model_name="deepseek-v4-pro")
    for effort, expected in (
        ("minimal", "low"),
        ("low", "low"),
        ("medium", "high"),
        ("high", "high"),
        ("xhigh", "max"),
        ("max", "max"),
    ):
        params = api.completion_params(
            config=GenerateConfig(reasoning_effort=effort), tools=False
        )
        assert params["reasoning_effort"] == expected


def test_deepseek_reasoning_effort_none_disables_thinking(mock_deepseek_env):
    """DeepSeek disables thinking via the thinking parameter, not an effort value."""
    from inspect_ai.model._providers.deepseek import DeepSeekAPI

    api = DeepSeekAPI(model_name="deepseek-v4-pro")
    params = api.completion_params(
        config=GenerateConfig(reasoning_effort="none"), tools=False
    )
    assert "reasoning_effort" not in params
    assert params["extra_body"]["thinking"] == {"type": "disabled"}


def test_deepseek_reasoning_effort_none_respects_user_thinking(mock_deepseek_env):
    """A user-supplied thinking value in extra_body must win over the default."""
    from inspect_ai.model._providers.deepseek import DeepSeekAPI

    api = DeepSeekAPI(model_name="deepseek-v4-pro")
    params = api.completion_params(
        config=GenerateConfig(
            reasoning_effort="none",
            extra_body={"thinking": {"type": "enabled"}},
        ),
        tools=False,
    )
    assert "reasoning_effort" not in params
    assert params["extra_body"]["thinking"] == {"type": "enabled"}


def test_deepseek_no_reasoning_effort_omits_param(mock_deepseek_env):
    """When reasoning_effort is unset nothing is sent (thinking defaults server-side)."""
    from inspect_ai.model._providers.deepseek import DeepSeekAPI

    api = DeepSeekAPI(model_name="deepseek-v4-pro")
    params = api.completion_params(config=GenerateConfig(max_tokens=100), tools=False)
    assert "reasoning_effort" not in params
    assert "extra_body" not in params


def test_deepseek_coerces_forced_tool_choice(mock_deepseek_env, _warn_once_messages):
    """Thinking mode 400s on forced tool_choice — coerce to "auto" with a warning."""
    from inspect_ai.model._providers.deepseek import DeepSeekAPI
    from inspect_ai.tool import ToolFunction

    api = DeepSeekAPI(model_name="deepseek-v4-flash")
    for forced in (ToolFunction(name="addition"), "any"):
        _, tool_choice, _ = api.resolve_tools(
            tools=[], tool_choice=forced, config=GenerateConfig()
        )
        assert tool_choice == "auto"
    assert any("addition" in m for m in _warn_once_messages), (
        "expected a warning for coerced tool_choice"
    )

    # non-forced choices pass through
    for choice in ("auto", "none"):
        _, tool_choice, _ = api.resolve_tools(
            tools=[], tool_choice=choice, config=GenerateConfig()
        )
        assert tool_choice == choice


def test_deepseek_thinking_disabled_preserves_forced_tool_choice(mock_deepseek_env):
    """Disabling thinking lifts the forced-tool_choice restriction."""
    from inspect_ai.model._providers.deepseek import DeepSeekAPI
    from inspect_ai.tool import ToolFunction

    api = DeepSeekAPI(model_name="deepseek-v4-flash")
    for config in (
        GenerateConfig(reasoning_effort="none"),
        GenerateConfig(extra_body={"thinking": {"type": "disabled"}}),
    ):
        _, tool_choice, _ = api.resolve_tools(
            tools=[], tool_choice=ToolFunction(name="addition"), config=config
        )
        assert tool_choice == ToolFunction(name="addition")


async def test_deepseek_replays_reasoning_content(mock_deepseek_env):
    """V4 requires reasoning_content on assistant messages in tool-call history."""
    from inspect_ai.model._providers.deepseek import DeepSeekAPI

    api = DeepSeekAPI(model_name="deepseek-v4-pro")
    messages = await api.messages_to_openai(
        [
            ChatMessageUser(content="Solve 3*x^3-5*x=1"),
            ChatMessageAssistant(
                content=[
                    ContentReasoning(
                        reasoning="considered options", internal="reasoning_content"
                    ),
                    ContentText(text="Let me use a tool."),
                ]
            ),
        ]
    )
    payload = messages[1]
    assert payload["reasoning_content"] == "considered options"


def test_deepseek_context_overflow_maps_to_model_length(mock_deepseek_env):
    """DeepSeek's token-limit 400 (generic error code) must map to model_length."""
    import httpx
    from openai import APIStatusError

    from inspect_ai.model._model_output import ModelOutput
    from inspect_ai.model._providers.deepseek import DeepSeekAPI

    api = DeepSeekAPI(model_name="deepseek-v4-flash")
    response = httpx.Response(
        status_code=400,
        request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"),
    )
    message = (
        "This model's maximum context length is 1048576 tokens. However, "
        "you requested 1283793 tokens (1283793 in the messages, 0 in the "
        "completion). Please reduce the length of the messages or completion."
    )
    ex = APIStatusError(
        message,
        response=response,
        body={"error": {"message": message, "type": "invalid_request_error"}},
    )
    output = api.handle_bad_request(ex)
    assert isinstance(output, ModelOutput)
    assert output.stop_reason == "model_length"

    # other 400s still pass through as errors
    other = APIStatusError(
        "some other error",
        response=response,
        body={"error": {"message": "some other error"}},
    )
    assert isinstance(api.handle_bad_request(other), Exception)


def test_deepseek_forwards_model_args(mock_deepseek_env):
    """Custom model args must reach the AsyncOpenAI client constructor."""
    from inspect_ai.model._providers.deepseek import DeepSeekAPI

    api = DeepSeekAPI(model_name="deepseek-v4-pro", default_headers={"X-Test": "yes"})
    assert api.client.default_headers.get("X-Test") == "yes"


@skip_if_no_deepseek
async def test_deepseek_compatible() -> None:
    # thinking is on by default, so the token budget must cover reasoning
    # before any completion text is emitted.
    model = get_model(
        "deepseek/deepseek-v4-flash",
        config=GenerateConfig(max_tokens=2048),
    )
    message = ChatMessageUser(content="Hello DeepSeek!")
    res = await model.generate(input=[message])
    assert len(res.completion) >= 1


@skip_if_no_deepseek
async def test_deepseek_reasoning_content() -> None:
    """Thinking is on by default; reasoning_content must surface as ContentReasoning."""
    model = get_model(
        "deepseek/deepseek-v4-flash",
        config=GenerateConfig(reasoning_effort="high", max_tokens=8192),
    )
    message = ChatMessageUser(content="Solve 3*x^3-5*x=1")
    res = await model.generate(input=[message])
    assert "<think>" not in res.completion
    content = res.choices[0].message.content
    assert isinstance(content, list)
    assert any(isinstance(c, ContentReasoning) for c in content)


@skip_if_no_deepseek
async def test_deepseek_disable_thinking() -> None:
    """reasoning_effort='none' must disable thinking rather than 400."""
    model = get_model(
        "deepseek/deepseek-v4-flash",
        config=GenerateConfig(reasoning_effort="none", max_tokens=2048),
    )
    res = await model.generate(input=[ChatMessageUser(content="Say hello.")])
    assert len(res.completion) >= 1
    content = res.choices[0].message.content
    if isinstance(content, list):
        assert not any(isinstance(c, ContentReasoning) for c in content)


@skip_if_no_deepseek
async def test_deepseek_tool_loop_replays_reasoning() -> None:
    """The API 400s if assistant reasoning_content is missing from tool-call history."""
    from inspect_ai.model import ChatMessage, execute_tools
    from inspect_ai.tool import tool

    @tool
    def addition():
        async def execute(x: int, y: int):
            """
            Add two numbers.

            Args:
                x: First number to add.
                y: Second number to add.
            """
            return x + y

        return execute

    model = get_model(
        "deepseek/deepseek-v4-flash", config=GenerateConfig(max_tokens=8192)
    )
    messages: list[ChatMessage] = [
        ChatMessageUser(content="Use the addition tool to compute 1 + 1.")
    ]
    res = await model.generate(input=messages, tools=[addition()])
    assert res.message.tool_calls
    messages.append(res.message)
    result = await execute_tools(messages, [addition()])
    messages.extend(result.messages)
    res = await model.generate(input=messages, tools=[addition()])
    assert "2" in res.completion
