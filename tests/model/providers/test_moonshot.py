import pytest
from test_helpers.utils import skip_if_no_moonshot

from inspect_ai._util.content import ContentReasoning
from inspect_ai.model import (
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


def test_moonshot_kimi_k3_coerces_reasoning_effort(
    mock_moonshot_env, _warn_once_messages
):
    """K3 thinking effort only accepts "max" — other values are coerced, with a warning."""
    from inspect_ai.model._providers.moonshot import MoonshotAPI

    api = MoonshotAPI(model_name="kimi-k3")
    params = api.completion_params(
        config=GenerateConfig(reasoning_effort="high"), tools=False
    )
    assert params["reasoning_effort"] == "max"
    assert any("reasoning_effort" in m and "kimi-k3" in m for m in _warn_once_messages)

    # "max" passes through without warning
    _warn_once_messages.clear()
    params = api.completion_params(
        config=GenerateConfig(reasoning_effort="max"), tools=False
    )
    assert params["reasoning_effort"] == "max"
    assert not _warn_once_messages


def test_moonshot_forwards_model_args(mock_moonshot_env):
    """Custom model args must reach the AsyncOpenAI client constructor."""
    from inspect_ai.model._providers.moonshot import MoonshotAPI

    api = MoonshotAPI(model_name="kimi-k3", default_headers={"X-Test": "yes"})
    assert api.client.default_headers.get("X-Test") == "yes"


def test_moonshot_non_k3_preserves_sampling_params(mock_moonshot_env):
    """Non-K3 Kimi models accept sampling params as usual."""
    from inspect_ai.model._providers.moonshot import MoonshotAPI

    api = MoonshotAPI(model_name="kimi-k2.5")
    params = api.completion_params(
        config=GenerateConfig(temperature=0.7, top_p=0.9),
        tools=False,
    )
    assert params["temperature"] == 0.7
    assert params["top_p"] == 0.9


def test_moonshot_base_url_default(mock_moonshot_env):
    from inspect_ai.model._providers.moonshot import MoonshotAPI

    api = MoonshotAPI(model_name="kimi-k3")
    assert api.base_url == "https://api.moonshot.ai/v1"


@skip_if_no_moonshot
async def test_moonshot_compatible() -> None:
    model = get_model(
        "moonshot/kimi-k3",
        config=GenerateConfig(max_tokens=50),
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
