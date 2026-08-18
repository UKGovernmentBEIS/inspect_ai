from typing import cast

import pytest
from openai import (
    AsyncBedrockOpenAI,
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
)
from test_helpers.utils import skip_if_no_openai_bedrock

from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.model._providers.openai import OpenAIAPI

# Errors that indicate a model isn't enabled/available for the tester's account
# or region (as opposed to a real integration failure). Bedrock gates frontier
# models like gpt-5.5 per account, so we skip rather than fail on these.
MODEL_UNAVAILABLE_ERRORS = (AuthenticationError, PermissionDeniedError, NotFoundError)

# Bedrock auth/region env vars that must be cleared so tests don't pick up a
# developer's real environment.
BEDROCK_ENV_VARS = [
    "BEDROCK_OPENAI_API_KEY",
    "AWS_BEARER_TOKEN_BEDROCK",
    "BEDROCK_OPENAI_BASE_URL",
    "AWS_BEDROCK_BASE_URL",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
]


@pytest.fixture
def clean_bedrock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in BEDROCK_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def bedrock_api(model_name: str = "openai/bedrock/gpt-5.5", **kwargs) -> OpenAIAPI:
    # memoize=False so each test gets a fresh instance that re-reads the
    # monkeypatched environment rather than a cached one
    return cast(OpenAIAPI, get_model(model_name, memoize=False, **kwargs).api)


def test_bedrock_prefix_parsing(clean_bedrock_env: None) -> None:
    api = bedrock_api(api_key="test-key")
    assert api.service == "bedrock"
    assert api.is_bedrock() is True
    assert api.service_model_name() == "gpt-5.5"
    # the openai. prefix is added only at the API boundary
    assert api.api_model_name() == "openai.gpt-5.5"
    # canonical name (for model-info lookup) keeps the plain name
    assert api.canonical_name() == "openai/gpt-5.5"


def test_bedrock_region_default(clean_bedrock_env: None) -> None:
    # with nothing set, region defaults to us-east-2 (the only region offering
    # these models today)
    api = bedrock_api(api_key="test-key")
    assert api.aws_region == "us-east-2"
    assert "us-east-2" in str(api.client.base_url)


def test_bedrock_base_url_path_frontier(clean_bedrock_env: None) -> None:
    # frontier models (gpt-5.x, codex) are served on the /openai/v1 path
    api = bedrock_api("openai/bedrock/gpt-5.5", api_key="test-key")
    base_url = str(api.client.base_url).rstrip("/")
    assert base_url == "https://bedrock-mantle.us-east-2.api.aws/openai/v1"


def test_bedrock_base_url_path_open_weight(clean_bedrock_env: None) -> None:
    # open-weight models (e.g. gpt-oss) are served on the /v1 path
    api = bedrock_api("openai/bedrock/gpt-oss-120b", api_key="test-key")
    base_url = str(api.client.base_url).rstrip("/")
    assert base_url == "https://bedrock-mantle.us-east-2.api.aws/v1"
    assert "/openai/v1" not in base_url


def test_bedrock_region_env_override(
    clean_bedrock_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    api = bedrock_api(api_key="test-key")
    assert api.aws_region == "us-west-2"


def test_bedrock_aws_region_model_arg(clean_bedrock_env: None) -> None:
    # the aws_region model arg wins and must not leak into model_args (which
    # would otherwise be double-passed to AsyncBedrockOpenAI)
    api = bedrock_api(api_key="test-key", aws_region="eu-west-1")
    assert api.aws_region == "eu-west-1"
    assert "aws_region" not in api.model_args


def test_bedrock_static_key_inspect_var(
    clean_bedrock_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BEDROCK_OPENAI_API_KEY", "inspect-key")
    api = bedrock_api()
    assert api.api_key == "inspect-key"
    assert api.token_provider is None


def test_bedrock_static_key_aws_var_fallback(
    clean_bedrock_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # AWS-standard name resolves when the Inspect-convention name is unset
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "aws-key")
    api = bedrock_api()
    assert api.api_key == "aws-key"
    assert api.token_provider is None


def test_bedrock_token_provider_path(clean_bedrock_env: None) -> None:
    # no static key anywhere -> fall through to the AWS credential-chain token
    # provider (mutually exclusive with api_key)
    api = bedrock_api()
    assert not api.api_key
    assert callable(api.token_provider)


def test_bedrock_client_type(clean_bedrock_env: None) -> None:
    api = bedrock_api(api_key="test-key")
    assert isinstance(api.client, AsyncBedrockOpenAI)


def test_bedrock_responses_api_default(clean_bedrock_env: None) -> None:
    # family detection runs on the plain name, so gpt-5.5 prefers the
    # Responses API (which Bedrock supports)
    api = bedrock_api(api_key="test-key")
    assert api.responses_api is True


def test_bedrock_disables_remote_mcp(clean_bedrock_env: None) -> None:
    api = bedrock_api(api_key="test-key")
    assert api.supports_remote_mcp() is False


@pytest.mark.parametrize("env_var", ["BEDROCK_OPENAI_BASE_URL", "AWS_BEDROCK_BASE_URL"])
def test_bedrock_base_url_env(
    clean_bedrock_env: None, monkeypatch: pytest.MonkeyPatch, env_var: str
) -> None:
    # both the Inspect-convention and AWS-standard base URL env vars are honored
    monkeypatch.setenv(env_var, "https://custom.example.com/openai/v1")
    api = bedrock_api(api_key="test-key")
    assert "custom.example.com" in str(api.client.base_url)


@pytest.mark.anyio
@skip_if_no_openai_bedrock
async def test_bedrock_generate_open_weight() -> None:
    # gpt-oss-120b: served on the /v1 path, broadly available across regions, so
    # use the tester's own region resolution. We assert on output token usage
    # rather than completion text because gpt-oss can route its entire response
    # through a reasoning channel, leaving completion text empty on success.
    model = get_model(
        "openai/bedrock/gpt-oss-120b", config=GenerateConfig(max_tokens=200)
    )
    response = await model.generate(input="Say hello in three words.")
    assert response.usage is not None
    assert response.usage.output_tokens > 0


@pytest.mark.anyio
@skip_if_no_openai_bedrock
async def test_bedrock_generate_frontier() -> None:
    # gpt-5.5: served on the /openai/v1 path via the Responses API. gpt-5.5 is
    # only available in us-east-2, and access is gated per account, so skip (not
    # fail) if the tester's account/region can't invoke it.
    model = get_model(
        "openai/bedrock/gpt-5.5",
        config=GenerateConfig(max_tokens=200),
        aws_region="us-east-2",
    )
    try:
        response = await model.generate(input="Say hello in three words.")
    except MODEL_UNAVAILABLE_ERRORS as ex:
        pytest.skip(f"gpt-5.5 not available for this account/region: {ex}")
    assert response.usage is not None
    assert response.usage.output_tokens > 0
