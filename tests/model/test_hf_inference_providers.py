import pytest
from test_helpers.utils import (
    skip_if_no_hf_token,
    skip_if_no_openai_package,
    skip_if_trio,
)

from inspect_ai.model import GenerateConfig, get_model


@pytest.mark.anyio
@skip_if_no_openai_package
@skip_if_trio
@skip_if_no_hf_token
async def test_hf_inference_providers_model_creation():
    """Test that HF Inference Providers models can be created."""
    model = get_model("hf-inference-providers/openai/gpt-oss-20b")

    # Verify the model was created successfully
    assert model is not None
    assert model.api.model_name == "openai/gpt-oss-20b"


@pytest.mark.anyio
@skip_if_no_openai_package
@skip_if_trio
@skip_if_no_hf_token
async def test_hf_inference_providers_with_config():
    """Test HF Inference Providers model with custom config."""
    config = GenerateConfig(temperature=0.7, max_tokens=100)
    model = get_model("hf-inference-providers/openai/gpt-oss-20b", config=config)

    assert model is not None
    assert model.api.model_name == "openai/gpt-oss-20b"


@pytest.mark.anyio
@skip_if_no_openai_package
@skip_if_trio
@skip_if_no_hf_token
async def test_hf_inference_providers_caching():
    """Test that HF Inference Providers models are cached properly."""
    model1 = get_model("hf-inference-providers/openai/gpt-oss-20b")
    model2 = get_model("hf-inference-providers/openai/gpt-oss-20b")

    # Verify we got the same cached instance
    assert model1 is model2


@skip_if_no_openai_package
def test_hf_token_reported_to_override_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The HF_TOKEN variable (not the derived service var) is offered to hooks."""
    from inspect_ai.model._providers.hf_inference_providers import (
        HF_TOKEN,
        HFInferenceProvidersAPI,
    )

    seen: list[tuple[str, str]] = []

    def override_api_key(env_var_name: str, value: str) -> str:
        seen.append((env_var_name, value))
        return "overridden-key"

    monkeypatch.setenv(HF_TOKEN, "source-key")
    monkeypatch.setattr(
        "inspect_ai.hooks._hooks.override_api_key",
        override_api_key,
    )

    api = HFInferenceProvidersAPI(model_name="openai/gpt-oss-20b")

    assert seen[0] == (HF_TOKEN, "source-key")
    assert all(name == HF_TOKEN for name, _ in seen)
    assert api.api_key == "overridden-key"
