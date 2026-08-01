import pytest
from test_helpers.utils import skip_if_no_abliteration

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)


@pytest.fixture
def mock_abliteration_env(monkeypatch):
    """Mock required Abliteration environment variables."""
    monkeypatch.setenv("ABLIT_KEY", "test-key")
    monkeypatch.delenv("ABLITERATION_BASE_URL", raising=False)


def test_abliteration_defaults(mock_abliteration_env):
    from inspect_ai.model._providers.abliteration import AbliterationAPI

    api = AbliterationAPI(model_name="huihui-ai/Llama-3.2-3B-Instruct-abliterated")
    assert api.api_key == "test-key"
    assert api.base_url == "https://api.abliteration.ai/v1"
    assert api.service_model_name() == "huihui-ai/Llama-3.2-3B-Instruct-abliterated"


def test_abliteration_base_url_env_override(mock_abliteration_env, monkeypatch):
    from inspect_ai.model._providers.abliteration import AbliterationAPI

    monkeypatch.setenv("ABLITERATION_BASE_URL", "https://example.com/v1")
    api = AbliterationAPI(model_name="huihui-ai/Llama-3.2-3B-Instruct-abliterated")
    assert api.base_url == "https://example.com/v1"


def test_abliteration_missing_api_key(monkeypatch):
    from inspect_ai.model._providers.abliteration import AbliterationAPI

    monkeypatch.delenv("ABLIT_KEY", raising=False)
    with pytest.raises(Exception, match="ABLIT_KEY"):
        AbliterationAPI(model_name="huihui-ai/Llama-3.2-3B-Instruct-abliterated")


@skip_if_no_abliteration
async def test_abliteration_compatible() -> None:
    model = get_model(
        "abliteration/huihui-ai/Llama-3.2-3B-Instruct-abliterated",
        config=GenerateConfig(max_tokens=50, temperature=0.0),
    )
    message = ChatMessageUser(content="What is an LLM")
    res = await model.generate(input=[message])
    assert len(res.completion) >= 1
