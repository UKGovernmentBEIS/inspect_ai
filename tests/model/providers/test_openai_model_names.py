"""Tests for OpenAIAPI model-name feature detection, focused on is_latest().

is_latest() recognizes OpenAI predeployment/codename models (names matching no
known family) as the current frontier, mirroring the Anthropic provider's
is_claude_latest(). Folding it into is_gpt_5()/is_gpt_5_plus() means a codename
gets full frontier behavior (responses API, reasoning options, etc.).
"""

import pytest

from inspect_ai.model._openai import is_latest_model
from inspect_ai.model._providers.openai import OpenAIAPI


def _api(model_name: str) -> OpenAIAPI:
    return OpenAIAPI(model_name=model_name, api_key="test-key")


# Known families and non-generative models must NOT be treated as latest.
KNOWN_MODELS = [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1",
    "chatgpt-4o-latest",
    "gpt-oss-120b",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5.5",
    "gpt-5-chat",
    "o1",
    "o1-preview",
    "o3-mini",
    "o4-mini",
    "o3-deep-research",
    "codex-mini",
]

NON_GENERATIVE_MODELS = [
    "text-embedding-3-large",
    "whisper-1",
    "dall-e-3",
    "tts-1",
    "omni-moderation-latest",
    "gpt-image-1",
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


@pytest.mark.parametrize("model_name", CODENAME_MODELS)
def test_codename_models_are_latest(model_name: str) -> None:
    api = _api(model_name)
    assert api.is_latest() is True
    # folded into the GPT-5 predicates ("gpt-5 or greater")
    assert api.is_gpt_5() is True
    assert api.is_gpt_5_plus() is True
    # frontier behavior follows automatically
    assert api.has_reasoning_options() is True
    assert api.responses_api is True
    # codename has no "-pro"/"-chat" substring
    assert api.is_gpt_5_pro() is False
    assert api.is_gpt_5_chat() is False


@pytest.mark.parametrize("model_name", CODENAME_MODELS)
def test_codename_aliases_to_frontier_context_window(model_name: str) -> None:
    # input_tokens_name() aliases to the current frontier so the context window
    # resolves correctly instead of falling back to the 128K default.
    assert _api(model_name).input_tokens_name() == "openai/gpt-5.5"


def test_known_model_input_tokens_name_unchanged() -> None:
    assert _api("gpt-4o").input_tokens_name() == "openai/gpt-4o"


def test_latest_scoped_to_direct_openai() -> None:
    # azure/bedrock-hosted models use customer deployment names / fixed catalogs,
    # so the residual detector must not fire for them.
    api = _api("foo-bar-22")
    assert api.is_latest() is True
    api.service = "azure"
    assert api.is_latest() is False
    api.service = "bedrock"
    assert api.is_latest() is False


def test_is_latest_model_helper_handles_bedrock_prefix() -> None:
    # api_model_name() prepends "openai." for bedrock; the string helper strips it
    assert is_latest_model("openai.foo-bar-22") is True
    assert is_latest_model("openai.gpt-5.5") is False
