"""Tests for GoogleGenAIAPI model-name feature detection, focused on is_latest().

is_latest() recognizes Google predeployment/codename models (names matching no
known family) as the current frontier, mirroring the OpenAI provider's
is_latest_model() and the Anthropic provider's is_claude_latest(). Folding it
into is_gemini() means a codename gets full frontier behavior (thinking config,
native tools), and input_tokens_name() aliases unknown names to the current
frontier so the context window (compaction) resolves correctly.
"""

import pytest

from inspect_ai.model import get_model
from inspect_ai.model._model_info import get_model_input_tokens
from inspect_ai.model._providers.google import GoogleGenAIAPI


def _api(model_name: str) -> GoogleGenAIAPI:
    return GoogleGenAIAPI(model_name=model_name, base_url=None, api_key="test-key")


# Known families and non-generative models must NOT be treated as latest.
KNOWN_MODELS = [
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-3-pro",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
]

NON_GENERATIVE_MODELS = [
    "text-embedding-004",
    "imagen-3.0-generate-002",
    "veo-2.0",
    "gemma-3-27b-it",
    "learnlm-2.0-flash",
]

# Codename / predeployment names matching no known family.
CODENAME_MODELS = [
    "foo-bar-22",
    "jellyfish",
    "bluejay-preview",
    "summit-2026",
]


@pytest.mark.parametrize("model_name", KNOWN_MODELS + NON_GENERATIVE_MODELS)
def test_known_models_not_latest(model_name: str) -> None:
    assert _api(model_name).is_latest() is False


@pytest.mark.parametrize("model_name", NON_GENERATIVE_MODELS)
def test_non_generative_models_not_gemini(model_name: str) -> None:
    assert _api(model_name).is_gemini() is False


@pytest.mark.parametrize("model_name", CODENAME_MODELS)
def test_codename_models_are_latest(model_name: str) -> None:
    api = _api(model_name)
    assert api.is_latest() is True
    # folded into is_gemini(), so frontier behavior follows transitively
    # (thinking config, native web search / code execution, mixed tools)
    assert api.is_gemini() is True
    assert api.is_gemini_3_plus() is True
    assert api.is_gemini_thinking() is True
    # codename has no "-pro"/"flash" substring
    assert api.is_gemini_thinking_only() is False
    assert api.is_gemini_3_flash() is False


def test_pro_codename_is_thinking_only() -> None:
    assert _api("orion-pro-preview").is_gemini_thinking_only() is True


def test_flash_codename_supports_minimal_thinking() -> None:
    assert _api("nimbus-flash-preview").is_gemini_3_flash() is True


@pytest.mark.parametrize("model_name", CODENAME_MODELS)
def test_codename_aliases_to_frontier_context_window(model_name: str) -> None:
    # input_tokens_name() aliases to the current frontier so the context window
    # resolves correctly instead of falling back to the 128K default.
    assert _api(model_name).input_tokens_name() == "google/gemini-3.5-flash"


@pytest.mark.parametrize("model_name", KNOWN_MODELS)
def test_known_model_input_tokens_name_unchanged(model_name: str) -> None:
    assert _api(model_name).input_tokens_name() == f"google/{model_name}"


def test_future_gemini_version_aliases_to_frontier() -> None:
    # a gemini-named model not yet in the model-info database gets frontier
    # treatment via is_gemini_3_plus() and the DB-miss alias (but is not a
    # "latest" codename)
    api = _api("gemini-4-pro")
    assert api.is_latest() is False
    assert api.is_gemini_3_plus() is True
    assert api.input_tokens_name() == "google/gemini-3.5-flash"


def test_latest_scoped_to_dev_endpoint() -> None:
    # vertex custom endpoints/deployments have arbitrary names that say
    # nothing about the model behind them
    api = GoogleGenAIAPI(
        model_name="vertex/some-partner-endpoint",
        base_url=None,
        api_key="test-key",
        project="test-project",
        location="us-central1",
    )
    assert api.is_latest() is False
    assert api.is_gemini() is False


def test_codename_context_window_resolves() -> None:
    model = get_model("google/foo-bar-22", api_key="test-key")
    assert get_model_input_tokens(model) == 1048576
