import pytest
from test_helpers.tasks import minimal_task
from test_helpers.utils import skip_if_no_azureai

from inspect_ai import eval_async
from inspect_ai.model import GenerateConfig, Model, get_model
from inspect_ai.model._providers.azureai import (
    AZURE_API_KEY,
    AZUREAI_API_KEY,
    AzureAIAPI,
)


def test_explicit_api_key_takes_precedence_over_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(AZURE_API_KEY, "legacy-env-key")
    monkeypatch.setenv(AZUREAI_API_KEY, "env-key")

    api = AzureAIAPI(
        model_name="test-model",
        base_url="https://example.com/models",
        api_key="explicit-key",
    )

    assert api.api_key == "explicit-key"
    assert api.token_provider is None


def test_azureai_api_key_is_offered_to_override_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str]] = []

    def override_api_key(env_var_name: str, value: str) -> str:
        seen.append((env_var_name, value))
        return "overridden-key"

    monkeypatch.delenv(AZURE_API_KEY, raising=False)
    monkeypatch.setenv(AZUREAI_API_KEY, "source-key")
    monkeypatch.setattr(
        "inspect_ai.hooks._hooks.override_api_key",
        override_api_key,
    )

    api = AzureAIAPI(
        model_name="test-model",
        base_url="https://example.com/models",
    )

    assert seen == [(AZUREAI_API_KEY, "source-key")]
    assert api.api_key == "overridden-key"


@pytest.mark.anyio
@skip_if_no_azureai
async def test_azureai_api() -> None:
    model = get_azureai_model()
    message = "This is a test string. What are you?"
    response = await model.generate(input=message)
    assert len(response.completion) >= 1


@pytest.mark.anyio
@skip_if_no_azureai
async def test_azureai_api_repeat_eval() -> None:
    model = get_azureai_model()
    _ = await eval_async(tasks=minimal_task, model=model)
    eval_log = await eval_async(tasks=minimal_task, model=model)
    assert eval_log[0].error is None, "Error on running consecutive evaluations"


def get_azureai_model() -> Model:
    return get_model(
        model="azureai/Llama-3.3-70B-Instruct",
        azure=True,
        config=GenerateConfig(
            frequency_penalty=0.0,
            stop_seqs=None,
            max_tokens=2,
            presence_penalty=0.0,
            seed=None,
            temperature=0.0,
            top_p=1.0,
        ),
    )
