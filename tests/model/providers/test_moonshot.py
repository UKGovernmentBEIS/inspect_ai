import pytest
from test_helpers.utils import skip_if_no_moonshot

from inspect_ai._util.content import ContentReasoning
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    get_model,
)


@pytest.fixture
def mock_moonshot_env(monkeypatch):
    """Mock required Moonshot environment variables."""
    monkeypatch.setenv("MOONSHOT_API_KEY", "test-key")


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


def test_moonshot_kimi_k3_drops_fixed_sampling_params(
    mock_moonshot_env, _warn_once_messages
):
    """Kimi K3 uses fixed sampling — sampling params must be omitted, with a warning."""
    from inspect_ai.model._providers.moonshot import MoonshotAPI

    api = MoonshotAPI(model_name="kimi-k3")
    params = api.completion_params(
        config=GenerateConfig(
            temperature=0.7,
            top_p=0.9,
            frequency_penalty=0.5,
            presence_penalty=0.5,
            max_tokens=100,
        ),
        tools=False,
    )
    assert "temperature" not in params
    assert "top_p" not in params
    assert "frequency_penalty" not in params
    assert "presence_penalty" not in params
    assert params["max_tokens"] == 100
    for param in ("temperature", "top_p", "frequency_penalty", "presence_penalty"):
        assert any(param in m and "kimi-k3" in m for m in _warn_once_messages), (
            f"expected a warning for dropped {param}"
        )


def test_moonshot_kimi_k3_no_warning_when_params_unset(
    mock_moonshot_env, _warn_once_messages
):
    """No warning should be emitted when the user never set the fixed params."""
    from inspect_ai.model._providers.moonshot import MoonshotAPI

    api = MoonshotAPI(model_name="kimi-k3")
    api.completion_params(config=GenerateConfig(max_tokens=100), tools=False)
    assert not any("fixed sampling" in m for m in _warn_once_messages)


def test_moonshot_kimi_k3_coerces_reasoning_effort(mock_moonshot_env):
    """K3 thinking effort only accepts "max" — other values are coerced silently."""
    from inspect_ai.model._providers.moonshot import MoonshotAPI

    api = MoonshotAPI(model_name="kimi-k3")
    params = api.completion_params(
        config=GenerateConfig(reasoning_effort="high"), tools=False
    )
    assert params["reasoning_effort"] == "max"

    params = api.completion_params(
        config=GenerateConfig(reasoning_effort="max"), tools=False
    )
    assert params["reasoning_effort"] == "max"


def test_moonshot_kimi_k3_coerces_forced_tool_choice(
    mock_moonshot_env, _warn_once_messages
):
    """K3 rejects named tool_choice (incompatible with thinking) — coerce to "any"."""
    from inspect_ai.model._providers.moonshot import MoonshotAPI
    from inspect_ai.tool import ToolFunction

    api = MoonshotAPI(model_name="kimi-k3")
    _, tool_choice, _ = api.resolve_tools(
        tools=[], tool_choice=ToolFunction(name="addition"), config=GenerateConfig()
    )
    assert tool_choice == "any"
    assert any("addition" in m and "kimi-k3" in m for m in _warn_once_messages), (
        "expected a warning for coerced tool_choice"
    )

    # non-forced choices pass through without warning
    _warn_once_messages.clear()
    _, tool_choice, _ = api.resolve_tools(
        tools=[], tool_choice="auto", config=GenerateConfig()
    )
    assert tool_choice == "auto"
    assert not _warn_once_messages


def test_moonshot_thinking_disabled_preserves_forced_tool_choice(mock_moonshot_env):
    """Disabling thinking via extra_body lifts the named tool_choice restriction."""
    from inspect_ai.model._providers.moonshot import MoonshotAPI
    from inspect_ai.tool import ToolFunction

    api = MoonshotAPI(model_name="kimi-k2.5")
    _, tool_choice, _ = api.resolve_tools(
        tools=[],
        tool_choice=ToolFunction(name="addition"),
        config=GenerateConfig(extra_body={"thinking": {"type": "disabled"}}),
    )
    assert tool_choice == ToolFunction(name="addition")


def test_moonshot_forwards_model_args(mock_moonshot_env):
    """Custom model args must reach the AsyncOpenAI client constructor."""
    from inspect_ai.model._providers.moonshot import MoonshotAPI

    api = MoonshotAPI(model_name="kimi-k3", default_headers={"X-Test": "yes"})
    assert api.client.default_headers.get("X-Test") == "yes"


def test_moonshot_kimi_k2_5_drops_fixed_sampling_params(mock_moonshot_env):
    """All Kimi thinking models use fixed sampling by default, not just K3."""
    from inspect_ai.model._providers.moonshot import MoonshotAPI

    api = MoonshotAPI(model_name="kimi-k2.5")
    params = api.completion_params(
        config=GenerateConfig(temperature=0.7, top_p=0.9),
        tools=False,
    )
    assert "temperature" not in params
    assert "top_p" not in params


def test_moonshot_thinking_disabled_preserves_sampling_params(mock_moonshot_env):
    """Disabling thinking via extra_body lifts the fixed-sampling restriction."""
    from inspect_ai.model._providers.moonshot import MoonshotAPI

    api = MoonshotAPI(model_name="kimi-k2.5")
    params = api.completion_params(
        config=GenerateConfig(
            temperature=0.7, extra_body={"thinking": {"type": "disabled"}}
        ),
        tools=False,
    )
    assert params["temperature"] == 0.7


def test_moonshot_legacy_model_preserves_sampling_params(mock_moonshot_env):
    """Legacy moonshot-v1 models accept sampling params as usual."""
    from inspect_ai.model._providers.moonshot import MoonshotAPI

    api = MoonshotAPI(model_name="moonshot-v1-8k")
    params = api.completion_params(
        config=GenerateConfig(temperature=0.7, top_p=0.9),
        tools=False,
    )
    assert params["temperature"] == 0.7
    assert params["top_p"] == 0.9


def test_moonshot_context_overflow_maps_to_model_length(mock_moonshot_env):
    """Moonshot's token-limit 400 (no error code) must map to stop_reason model_length."""
    import httpx
    from openai import APIStatusError

    from inspect_ai.model._model_output import ModelOutput
    from inspect_ai.model._providers.moonshot import MoonshotAPI

    api = MoonshotAPI(model_name="kimi-k3")
    response = httpx.Response(
        status_code=400,
        request=httpx.Request("POST", "https://api.moonshot.ai/v1/chat/completions"),
    )
    message = (
        "Invalid request: Your request exceeded model token limit: "
        "262144 (requested: 425573)"
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


def test_moonshot_base_url_default(mock_moonshot_env):
    from inspect_ai.model._providers.moonshot import MoonshotAPI

    api = MoonshotAPI(model_name="kimi-k3")
    assert api.base_url == "https://api.moonshot.ai/v1"


def test_moonshot_retries_503_as_rate_limit(mock_moonshot_env) -> None:
    """503 must be retried as a rate limit (scales down adaptive concurrency)."""
    import httpx
    from openai import InternalServerError

    from inspect_ai.model._model import RetryDecision
    from inspect_ai.model._providers.moonshot import MoonshotAPI

    api = MoonshotAPI(model_name="kimi-k3")

    def sdk_error(status_code: int, headers: dict[str, str] | None = None):
        response = httpx.Response(
            status_code=status_code,
            headers=headers,
            request=httpx.Request(
                "POST", "https://api.moonshot.ai/v1/chat/completions"
            ),
        )
        return InternalServerError("Server Error", response=response, body=None)

    # SDK-shaped 503 (honoring Retry-After when the server provides one)
    decision = api.should_retry(sdk_error(503, headers={"retry-after": "7"}))
    assert isinstance(decision, RetryDecision)
    assert decision.retry
    assert decision.kind == "rate_limit"
    assert decision.retry_after == 7

    # non-SDK exception shape carrying a 503 status code
    class ServiceUnavailableError(Exception):
        status_code = 503

    decision = api.should_retry(ServiceUnavailableError())
    assert isinstance(decision, RetryDecision)
    assert decision.retry
    assert decision.kind == "rate_limit"

    # other 5xx still classify as transient via the base
    decision = api.should_retry(sdk_error(500))
    assert isinstance(decision, RetryDecision)
    assert decision.retry
    assert decision.kind == "transient"

    # non-retryable statuses still don't retry
    class NotFoundError(Exception):
        status_code = 404

    assert not api.should_retry(NotFoundError())


async def test_moonshot_fills_empty_assistant_content(mock_moonshot_env):
    """The API rejects assistant messages with empty content — fill with NO_CONTENT."""
    from inspect_ai._util.constants import NO_CONTENT
    from inspect_ai.model._providers.moonshot import MoonshotAPI

    api = MoonshotAPI(model_name="kimi-k3")
    messages = await api.messages_to_openai(
        [
            ChatMessageUser(content="Say hello."),
            ChatMessageAssistant(content=""),
            ChatMessageAssistant(content="Hello!"),
        ]
    )
    assert messages[1]["content"] == NO_CONTENT
    assert messages[2]["content"] == "Hello!"


@skip_if_no_moonshot
async def test_moonshot_compatible() -> None:
    # K3 thinking is always on, so the token budget must cover reasoning
    # before any completion text is emitted.
    model = get_model(
        "moonshot/kimi-k3",
        config=GenerateConfig(max_tokens=2048),
    )
    message = ChatMessageUser(content="Hello Kimi!")
    res = await model.generate(input=[message])
    assert len(res.completion) >= 1


@skip_if_no_moonshot
async def test_moonshot_kimi_k3_fixed_sampling_live() -> None:
    """Unsupported params must be stripped/coerced before hitting the API (K3 rejects them)."""
    model = get_model(
        "moonshot/kimi-k3",
        config=GenerateConfig(
            temperature=0.7,
            top_p=0.9,
            frequency_penalty=0.5,
            presence_penalty=0.5,
            reasoning_effort="high",
            max_tokens=2048,
        ),
    )
    message = ChatMessageUser(content="Hello Kimi!")
    res = await model.generate(input=[message])
    assert res.choices


@skip_if_no_moonshot
async def test_moonshot_empty_assistant_message() -> None:
    """Replaying an empty assistant message must not 400 (filled with NO_CONTENT)."""
    model = get_model("moonshot/kimi-k3", config=GenerateConfig(max_tokens=2048))
    res = await model.generate(
        input=[
            ChatMessageUser(content="Say hello."),
            ChatMessageAssistant(content=""),
            ChatMessageUser(content="Please continue."),
        ]
    )
    assert len(res.completion) >= 1


@skip_if_no_moonshot
async def test_moonshot_kimi_k3_reasoning_content() -> None:
    """K3 thinking is always on; reasoning_content must surface as ContentReasoning."""
    model = get_model(
        "moonshot/kimi-k3",
        config=GenerateConfig(reasoning_effort="max", max_tokens=8192),
    )
    message = ChatMessageUser(content="Solve 3*x^3-5*x=1")
    res = await model.generate(input=[message])
    assert "<think>" not in res.completion
    content = res.choices[0].message.content
    assert isinstance(content, list)
    assert any(isinstance(c, ContentReasoning) for c in content)
