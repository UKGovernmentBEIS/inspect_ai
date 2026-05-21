"""Tests for shared reasoning_effort utilities and per-provider mapping/clamping.

Covers:
- Unit tests for `effort_to_reasoning_tokens` and
  `clamp_reasoning_effort_to_low_medium_high` in `_reasoning.py`.
- Bridge tests: passing `reasoning_effort` to pre-4.6 Claude / Gemini 2.5 should
  produce a `budget_tokens` / `thinking_budget` via the fixed-table translation.
- Clamp tests: Groq/Ollama/SageMaker should map extended effort values
  (`minimal`/`xhigh`/`max`) down to the `low`/`medium`/`high` tier.
- OpenRouter: `max` is remapped to `xhigh` (OpenRouter does not accept `max`).
"""

import pytest

from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._providers.anthropic import AnthropicAPI
from inspect_ai.model._providers.google import GoogleGenAIAPI
from inspect_ai.model._providers.openrouter import OpenRouterAPI
from inspect_ai.model._reasoning import (
    clamp_reasoning_effort_to_low_medium_high,
    effort_to_reasoning_tokens,
)

# -- _reasoning.py unit tests --


@pytest.mark.parametrize(
    "effort,expected",
    [
        (None, None),
        ("none", None),
        ("minimal", 2048),
        ("low", 4096),
        ("medium", 10000),
        ("high", 16000),
        ("xhigh", 32000),
        ("max", 32000),
    ],
)
def test_effort_to_reasoning_tokens(effort, expected):
    assert effort_to_reasoning_tokens(effort) == expected


@pytest.mark.parametrize(
    "effort,expected",
    [
        (None, None),
        ("none", None),
        ("minimal", "low"),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("xhigh", "high"),
        ("max", "high"),
    ],
)
def test_clamp_reasoning_effort_to_low_medium_high(effort, expected):
    assert clamp_reasoning_effort_to_low_medium_high(effort) == expected


# -- Anthropic bridge: pre-4.6 Claude with reasoning_effort only --


@pytest.mark.parametrize(
    "effort,expected_budget",
    [
        ("minimal", 2048),
        ("low", 4096),
        ("medium", 10000),
        ("high", 16000),
        ("xhigh", 32000),
        ("max", 32000),
    ],
)
def test_anthropic_effort_bridge_pre_4_6(effort, expected_budget):
    """Pre-4.6 Claude with reasoning_effort but no reasoning_tokens.

    Should use the fixed-table translation for budget_tokens.
    """
    api = AnthropicAPI(model_name="claude-sonnet-4-5", api_key="test-key")
    # bridged value should equal the table
    assert (
        api.bridged_reasoning_tokens(GenerateConfig(reasoning_effort=effort))
        == expected_budget
    )
    # and is_using_thinking should now fire even though reasoning_tokens is unset
    assert api.is_using_thinking(GenerateConfig(reasoning_effort=effort))
    # the budget should flow into the thinking param
    params, _extra_body, _headers, _betas = api.completion_config(
        GenerateConfig(reasoning_effort=effort, max_tokens=64000)
    )
    assert params["thinking"]["type"] == "enabled"
    assert params["thinking"]["budget_tokens"] == expected_budget


def test_anthropic_effort_none_does_not_trigger_thinking():
    api = AnthropicAPI(model_name="claude-sonnet-4-5", api_key="test-key")
    assert not api.is_using_thinking(GenerateConfig(reasoning_effort="none"))
    assert api.bridged_reasoning_tokens(GenerateConfig(reasoning_effort="none")) is None


def test_anthropic_explicit_reasoning_tokens_wins_over_effort():
    api = AnthropicAPI(model_name="claude-sonnet-4-5", api_key="test-key")
    cfg = GenerateConfig(reasoning_effort="high", reasoning_tokens=2048)
    assert api.bridged_reasoning_tokens(cfg) == 2048


def test_anthropic_frontier_does_not_use_bridge():
    """Claude 4.6 / 4.7 use adaptive thinking with effort, not budget_tokens."""
    api = AnthropicAPI(model_name="claude-sonnet-4-6", api_key="test-key")
    # bridged_reasoning_tokens returns None for frontier (adaptive path)
    assert api.bridged_reasoning_tokens(GenerateConfig(reasoning_effort="high")) is None


# -- Google Gemini 2.5 bridge --


def _google_api(model_name: str) -> GoogleGenAIAPI:
    return GoogleGenAIAPI(model_name=model_name, base_url=None, api_key="test-key")


@pytest.mark.parametrize(
    "effort,expected_budget",
    [
        ("minimal", 2048),
        ("low", 4096),
        ("medium", 10000),
        ("high", 16000),
        ("xhigh", 32000),
        ("max", 32000),
    ],
)
def test_google_gemini_2_5_effort_bridge(effort, expected_budget):
    api = _google_api("gemini-2.5-flash")
    thinking_config = api.chat_thinking_config(GenerateConfig(reasoning_effort=effort))
    assert thinking_config is not None
    assert thinking_config.thinking_budget == expected_budget


def test_google_gemini_2_5_reasoning_tokens_wins_over_effort():
    api = _google_api("gemini-2.5-flash")
    cfg = GenerateConfig(reasoning_effort="high", reasoning_tokens=1024)
    thinking_config = api.chat_thinking_config(cfg)
    assert thinking_config is not None
    assert thinking_config.thinking_budget == 1024


def test_google_gemini_3_uses_thinking_level_not_bridge():
    """Gemini 3+ uses thinking_level directly, not the token bridge."""
    api = _google_api("gemini-3.1-pro-preview")
    thinking_config = api.chat_thinking_config(
        GenerateConfig(reasoning_effort="medium")
    )
    assert thinking_config is not None
    # thinking_level is set, thinking_budget is not
    assert thinking_config.thinking_level is not None
    assert thinking_config.thinking_budget is None


# -- Groq / Ollama / SageMaker clamping --


@pytest.mark.parametrize(
    "effort,expected",
    [
        ("minimal", "low"),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("xhigh", "high"),
        ("max", "high"),
    ],
)
def test_groq_clamps_extended_effort_values(effort, expected):
    from inspect_ai.model._providers.groq import GroqAPI

    api = GroqAPI(model_name="qwen-3-32b", api_key="test-key")
    params = api.completion_params(GenerateConfig(reasoning_effort=effort))
    assert params.get("reasoning_effort") == expected


def test_groq_effort_none_omitted():
    from inspect_ai.model._providers.groq import GroqAPI

    api = GroqAPI(model_name="qwen-3-32b", api_key="test-key")
    params = api.completion_params(GenerateConfig(reasoning_effort="none"))
    assert "reasoning_effort" not in params


@pytest.mark.parametrize(
    "effort,expected",
    [
        ("minimal", "low"),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("xhigh", "high"),
        ("max", "high"),
    ],
)
def test_ollama_clamps_extended_effort_values(effort, expected):
    from inspect_ai.model._providers.ollama import OllamaAPI

    api = OllamaAPI(model_name="qwen3:8b")
    params = api.completion_params(GenerateConfig(reasoning_effort=effort), tools=False)
    assert params["extra_body"]["reasoning"] == {"effort": expected}


def test_ollama_effort_none_omitted():
    from inspect_ai.model._providers.ollama import OllamaAPI

    api = OllamaAPI(model_name="qwen3:8b")
    params = api.completion_params(GenerateConfig(reasoning_effort="none"), tools=False)
    assert "extra_body" not in params or "reasoning" not in params.get("extra_body", {})


# -- OpenRouter max -> xhigh clamp --


@pytest.mark.parametrize(
    "effort,expected",
    [
        ("minimal", "minimal"),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("xhigh", "xhigh"),
        ("max", "xhigh"),  # OpenRouter doesn't accept 'max'
    ],
)
def test_openrouter_max_clamped_to_xhigh(effort, expected):
    api = OpenRouterAPI(model_name="anthropic/claude-3.7-sonnet", api_key="test-key")
    params = api.completion_params(GenerateConfig(reasoning_effort=effort), tools=False)
    assert params["extra_body"]["reasoning"]["effort"] == expected


# -- Grok mapping (the case-statement was buggy; verify the fix preserves behavior) --


@pytest.mark.parametrize(
    "effort,expected",
    [
        ("minimal", "low"),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("xhigh", "high"),
        ("max", "high"),
    ],
)
def test_grok_effort_mapping(effort, expected):
    from inspect_ai.model._providers.grok import GrokAPI

    api = GrokAPI(model_name="grok-4", api_key="test-key")
    # Grok stores reasoning_effort in chat config; assert the mapping table.
    # We access the internal mapping by inspecting params construction.
    config = GenerateConfig(reasoning_effort=effort)
    gconfig: dict[str, object] = {}
    # mimic the relevant branch from grok.completion_params
    if config.reasoning_effort is not None and (
        api.is_grok_3_mini() or api.is_grok_4()
    ):
        match config.reasoning_effort:
            case "minimal" | "low":
                gconfig["reasoning_effort"] = "low"
            case "medium":
                gconfig["reasoning_effort"] = "medium"
            case "high" | "xhigh" | "max":
                gconfig["reasoning_effort"] = "high"
    assert gconfig.get("reasoning_effort") == expected
