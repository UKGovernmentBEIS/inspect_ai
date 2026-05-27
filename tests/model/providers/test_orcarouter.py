"""Tests for the OrcaRouter provider."""

from typing import Any

import pytest

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._openai import OpenAIResponseError
from inspect_ai.model._providers.orcarouter import (
    OrcaRouterAPI,
    OrcaRouterError,
)


def _make_api(
    model_name: str = "orcarouter/openai/gpt-4o-mini", **kwargs: Any
) -> OrcaRouterAPI:
    return OrcaRouterAPI(model_name=model_name, api_key="test-key", **kwargs)


def test_default_base_url_and_api_key() -> None:
    api = _make_api()
    assert api.base_url == "https://api.orcarouter.ai/v1"
    assert api.api_key == "test-key"
    assert api.service == "OrcaRouter"


def test_models_arg_accepted_as_list() -> None:
    api = _make_api(models=["openai/gpt-4o", "anthropic/claude-opus-4.7"])
    assert api.models == ["openai/gpt-4o", "anthropic/claude-opus-4.7"]


def test_models_arg_must_be_list() -> None:
    with pytest.raises(PrerequisiteError):
        _make_api(models="not-a-list")


def test_completion_params_injects_fallback_models() -> None:
    api = _make_api(models=["openai/gpt-4o", "anthropic/claude-opus-4.7"])
    params = api.completion_params(GenerateConfig(), tools=False)
    assert params["extra_body"]["models"] == [
        "openai/gpt-4o",
        "anthropic/claude-opus-4.7",
    ]
    assert params["extra_body"]["route"] == "fallback"


def test_completion_params_no_extra_body_without_models() -> None:
    api = _make_api()
    params = api.completion_params(GenerateConfig(), tools=False)
    assert "extra_body" not in params or "models" not in params.get("extra_body", {})


def test_default_attribution_headers() -> None:
    api = _make_api()
    assert api.referer == "https://inspect.aisi.org.uk/"
    assert api.app_title == "Inspect AI"


def test_custom_attribution_headers() -> None:
    api = _make_api(referer="https://my-org.example/", app_title="My Eval Harness")
    assert api.referer == "https://my-org.example/"
    assert api.app_title == "My Eval Harness"


def test_on_response_raises_rate_limit_on_429() -> None:
    api = _make_api()
    with pytest.raises(OpenAIResponseError) as info:
        api.on_response({"error": {"code": 429, "message": "slow down"}})
    assert "rate_limit_exceeded" in str(info.value.code)


@pytest.mark.parametrize("code", [408, 500, 502, 504])
def test_on_response_raises_server_error_on_5xx(code: int) -> None:
    api = _make_api()
    with pytest.raises(OpenAIResponseError) as info:
        api.on_response({"error": {"code": code, "message": "boom"}})
    assert info.value.code == "server_error"


def test_on_response_raises_orcarouter_error_on_other_codes() -> None:
    api = _make_api()
    with pytest.raises(OrcaRouterError):
        api.on_response({"error": {"code": 400, "message": "bad request"}})


def test_on_response_raises_server_error_on_empty_choices() -> None:
    api = _make_api()
    with pytest.raises(OpenAIResponseError) as info:
        api.on_response({})
    assert info.value.code == "server_error"


def test_on_response_passes_on_success() -> None:
    api = _make_api()
    # no error + non-empty choices → no raise
    api.on_response({"choices": [{"index": 0}]})
