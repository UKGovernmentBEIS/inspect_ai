import pytest
from test_helpers.utils import skip_if_no_moonshot

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)


@pytest.fixture
def mock_moonshot_env(monkeypatch):
    """Mock required Moonshot environment variables."""
    monkeypatch.setenv("MOONSHOT_API_KEY", "test-key")


def test_moonshot_kimi_k3_drops_fixed_sampling_params(mock_moonshot_env):
    """Kimi K3 uses fixed sampling — sampling params must be omitted."""
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
