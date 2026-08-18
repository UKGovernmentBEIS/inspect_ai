"""Tests for GrokAPI model-name feature detection, focused on is_latest().

is_latest() recognizes xAI predeployment/codename models (names matching no
known family) as the current frontier, mirroring the OpenAI provider's
is_latest_model() and the Anthropic provider's is_claude_latest(). Codenames
fall through is_at_least_grok_4() so they get frontier behavior (native web
search, reasoning_effort), and input_tokens_name() aliases unknown grok-4-or-
later names to the current frontier so the context window resolves correctly.
"""

import pytest

from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.model._model_info import get_model_input_tokens
from inspect_ai.model._providers.grok import GrokAPI


def _api(model_name: str) -> GrokAPI:
    return GrokAPI(model_name=model_name, api_key="test-key")


# Known families must NOT be treated as latest.
KNOWN_MODELS = [
    "grok-2-1212",
    "grok-3",
    "grok-3-mini",
    "grok-4",
    "grok-4-fast-reasoning",
    "grok-4-1-fast-reasoning",
    "grok-4.20",
    "grok-4.3",
    "grok-4.5",
    "grok-4.6",
    "grok-5",
]

NON_GENERATIVE_MODELS = [
    "grok-2-image-1212",
    "grok-imagine-v0.9",
    "text-embedding-3",
    "tts-1",
]

# Codename / predeployment names matching no known family.
CODENAME_MODELS = [
    "sherlock-think",
    "foo-bar-22",
    "jellyfish",
    "summit-2026",
]


@pytest.mark.parametrize("model_name", KNOWN_MODELS + NON_GENERATIVE_MODELS)
def test_known_models_not_latest(model_name: str) -> None:
    assert _api(model_name).is_latest() is False


@pytest.mark.parametrize("model_name", CODENAME_MODELS)
def test_codename_models_are_latest(model_name: str) -> None:
    api = _api(model_name)
    assert api.is_latest() is True
    # frontier behavior follows from is_at_least_grok_4() (native web search,
    # reasoning_effort), while the grok-2-only request params stay off
    assert api.is_at_least_grok_4() is True
    assert api.is_grok_4_original() is False
    assert api.is_grok_2() is False


@pytest.mark.parametrize("model_name", CODENAME_MODELS + ["grok-5", "grok-4.6"])
def test_frontier_models_send_reasoning_effort(model_name: str) -> None:
    params = _api(model_name)._grok_params(GenerateConfig(reasoning_effort="high"))
    assert params["reasoning_effort"] == "high"


@pytest.mark.parametrize("model_name", ["grok-4", "grok-4-latest", "grok-4-0709"])
def test_original_grok_4_omits_reasoning_effort(model_name: str) -> None:
    params = _api(model_name)._grok_params(GenerateConfig(reasoning_effort="high"))
    assert "reasoning_effort" not in params


@pytest.mark.parametrize("model_name", CODENAME_MODELS + ["grok-5"])
def test_unknown_models_alias_to_frontier_context_window(model_name: str) -> None:
    # input_tokens_name() aliases to the current frontier so the context window
    # resolves instead of coming back empty
    assert _api(model_name).input_tokens_name() == "grok/grok-4.6"


@pytest.mark.parametrize(
    "model_name", ["grok-4.5", "grok-4.6", "grok-3", "grok-3-mini"]
)
def test_known_model_input_tokens_name_unchanged(model_name: str) -> None:
    assert _api(model_name).input_tokens_name() == f"grok/{model_name}"


def test_older_families_not_aliased_to_frontier() -> None:
    # grok-2 is absent from the model-info database; aliasing it to the
    # frontier would overstate its context window
    assert _api("grok-2-1212").input_tokens_name() == "grok/grok-2-1212"


def test_codename_context_window_resolves() -> None:
    model = get_model("grok/sherlock-think", api_key="test-key")
    assert get_model_input_tokens(model) == 500000
