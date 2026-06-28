import pytest
from test_helpers.utils import skip_if_no_cloudflare, skip_if_no_openai_package

from inspect_ai.model import get_model


@pytest.mark.anyio
@skip_if_no_cloudflare
async def test_cloudflare_api() -> None:
    async with get_model("cf/meta/llama-3.1-8b-instruct-awq") as model:
        message = "This is a test string. What are you?"
        response = await model.generate(input=message)
        assert len(response.completion) >= 1


@skip_if_no_openai_package
def test_cloudflare_token_reported_to_override_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.model._providers.cloudflare import (
        CLOUDFLARE_API_KEY,
        CLOUDFLARE_API_TOKEN,
        CloudFlareAPI,
    )

    seen: list[tuple[str, str]] = []

    def override_api_key(env_var_name: str, value: str) -> str:
        seen.append((env_var_name, value))
        return "overridden-key"

    monkeypatch.delenv(CLOUDFLARE_API_KEY, raising=False)
    monkeypatch.setenv(CLOUDFLARE_API_TOKEN, "source-key")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account-id")
    monkeypatch.setattr(
        "inspect_ai.hooks._hooks.override_api_key",
        override_api_key,
    )

    api = CloudFlareAPI(model_name="meta/llama-3.1-8b-instruct-awq")

    # the key came from CLOUDFLARE_API_TOKEN, so that is the variable the hook
    # must be told about (not the derived CLOUDFLARE_API_KEY)
    assert seen[0] == (CLOUDFLARE_API_TOKEN, "source-key")
    assert all(name == CLOUDFLARE_API_TOKEN for name, _ in seen)
    assert api.api_key == "overridden-key"


@skip_if_no_openai_package
def test_cloudflare_api_key_reported_to_override_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.model._providers.cloudflare import (
        CLOUDFLARE_API_KEY,
        CLOUDFLARE_API_TOKEN,
        CloudFlareAPI,
    )

    seen: list[tuple[str, str]] = []

    def override_api_key(env_var_name: str, value: str) -> str:
        seen.append((env_var_name, value))
        return "overridden-key"

    monkeypatch.delenv(CLOUDFLARE_API_TOKEN, raising=False)
    monkeypatch.setenv(CLOUDFLARE_API_KEY, "source-key")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account-id")
    monkeypatch.setattr(
        "inspect_ai.hooks._hooks.override_api_key",
        override_api_key,
    )

    api = CloudFlareAPI(model_name="meta/llama-3.1-8b-instruct-awq")

    assert seen[0] == (CLOUDFLARE_API_KEY, "source-key")
    assert all(name == CLOUDFLARE_API_KEY for name, _ in seen)
    assert api.api_key == "overridden-key"
