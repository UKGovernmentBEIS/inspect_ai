import pytest

from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._providers.openai_compatible import OpenAICompatibleAPI


def test_openai_compatible_use_max_completion_tokens_rewrites_max_tokens():
    api = OpenAICompatibleAPI(
        model_name="acme/custom-model",
        base_url="http://localhost:9999/v1",
        api_key="test-key",
        use_max_completion_tokens=True,
    )

    params = api.completion_params(GenerateConfig(max_tokens=123), tools=False)

    assert "max_tokens" not in params
    assert params["max_completion_tokens"] == 123


def test_openai_compatible_use_max_completion_tokens_requires_bool():
    with pytest.raises(ValueError, match="use_max_completion_tokens must be a bool"):
        OpenAICompatibleAPI(
            model_name="acme/custom-model",
            base_url="http://localhost:9999/v1",
            api_key="test-key",
            use_max_completion_tokens="true",
        )
