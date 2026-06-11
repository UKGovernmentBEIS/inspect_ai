"""Tests for the Azure OpenAI next-generation v1 API (no dated api-version).

These are offline client-construction tests (no Azure credentials or network
access required).
"""

import pytest
from openai import AsyncAzureOpenAI, AsyncOpenAI

from inspect_ai.model._providers.openai import OpenAIAPI
from inspect_ai.model._providers.util.azure_hosting import (
    azure_v1_base_url,
    azure_v1_token_key,
    is_azure_v1_api_version,
)

AZURE_ENDPOINT = "https://example-resource.openai.azure.com"


@pytest.fixture
def azure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZUREAI_OPENAI_API_KEY", "test-api-key")
    monkeypatch.setenv("AZUREAI_OPENAI_BASE_URL", AZURE_ENDPOINT)
    monkeypatch.delenv("AZUREAI_OPENAI_API_VERSION", raising=False)
    monkeypatch.delenv("OPENAI_API_VERSION", raising=False)


def azure_api(**model_args) -> OpenAIAPI:
    return OpenAIAPI(model_name="azure/gpt-4o-mini", **model_args)


def test_azure_dated_api_version_unchanged(azure_env) -> None:
    """Default behavior (dated api-version + AsyncAzureOpenAI) is preserved."""
    api = azure_api()
    assert isinstance(api.client, AsyncAzureOpenAI)
    assert api.api_version == "2025-03-01-preview"


def test_azure_explicit_dated_api_version_unchanged(azure_env) -> None:
    api = azure_api(api_version="2024-10-21")
    assert isinstance(api.client, AsyncAzureOpenAI)
    assert api.api_version == "2024-10-21"


@pytest.mark.parametrize("api_version", ["v1", "preview", "latest", "V1"])
def test_azure_v1_api_version_uses_plain_client(azure_env, api_version) -> None:
    """v1 sentinels select the plain OpenAI client against /openai/v1/."""
    api = azure_api(api_version=api_version)
    assert isinstance(api.client, AsyncOpenAI)
    assert not isinstance(api.client, AsyncAzureOpenAI)
    assert str(api.client.base_url) == f"{AZURE_ENDPOINT}/openai/v1/"
    assert api.client.api_key == "test-api-key"


def test_azure_v1_api_version_via_env(
    azure_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AZUREAI_OPENAI_API_VERSION", "v1")
    api = azure_api()
    assert isinstance(api.client, AsyncOpenAI)
    assert not isinstance(api.client, AsyncAzureOpenAI)
    assert str(api.client.base_url) == f"{AZURE_ENDPOINT}/openai/v1/"


def test_azure_v1_base_url_not_doubled(
    azure_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An endpoint that already includes /openai/v1 is left intact."""
    monkeypatch.setenv("AZUREAI_OPENAI_BASE_URL", f"{AZURE_ENDPOINT}/openai/v1/")
    api = azure_api(api_version="v1")
    assert str(api.client.base_url) == f"{AZURE_ENDPOINT}/openai/v1/"


async def test_azure_v1_managed_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no API key, the token provider becomes an async api_key callable."""
    monkeypatch.delenv("AZUREAI_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AZUREAI_OPENAI_BASE_URL", AZURE_ENDPOINT)
    monkeypatch.setattr(
        "inspect_ai.model._providers.openai.resolve_azure_token_provider",
        lambda provider_name: (lambda: "entra-token"),
    )
    api = azure_api(api_version="v1")
    assert isinstance(api.client, AsyncOpenAI)
    # a callable api_key is stored by the SDK as its api key provider
    # (the api_key property remains "" until the first refresh)
    api_key_provider = api.client._api_key_provider
    assert callable(api_key_provider)
    assert await api_key_provider() == "entra-token"


def test_is_azure_v1_api_version() -> None:
    assert is_azure_v1_api_version("v1")
    assert is_azure_v1_api_version("preview")
    assert is_azure_v1_api_version("latest")
    assert is_azure_v1_api_version("V1")
    assert not is_azure_v1_api_version("2025-03-01-preview")
    assert not is_azure_v1_api_version(None)


def test_azure_v1_base_url() -> None:
    assert azure_v1_base_url(AZURE_ENDPOINT) == f"{AZURE_ENDPOINT}/openai/v1/"
    assert azure_v1_base_url(f"{AZURE_ENDPOINT}/") == f"{AZURE_ENDPOINT}/openai/v1/"
    assert (
        azure_v1_base_url(f"{AZURE_ENDPOINT}/openai/v1")
        == f"{AZURE_ENDPOINT}/openai/v1/"
    )
    assert (
        azure_v1_base_url(f"{AZURE_ENDPOINT}/openai/v1/")
        == f"{AZURE_ENDPOINT}/openai/v1/"
    )


async def test_azure_v1_token_key() -> None:
    token_key = azure_v1_token_key(lambda: "tok")
    assert await token_key() == "tok"
