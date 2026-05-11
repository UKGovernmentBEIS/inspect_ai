"""Tests for Bedrock Nova maxTokens handling per reasoning effort.

Regression test for https://github.com/UKGovernmentBEIS/inspect_ai/issues/3767

AWS Nova Converse API only requires maxTokens to be unset when reasoning effort
is "high". For "low" and "medium", maxTokens is a normal supported parameter
and previously the code was silently dropping the user's max_tokens for ALL
reasoning effort levels.
"""

from __future__ import annotations

import pytest

pytest.importorskip("aiobotocore")
pytest.importorskip("botocore")

from inspect_ai.model._generate_config import GenerateConfig  # noqa: E402
from inspect_ai.model._providers.bedrock import BedrockAPI  # noqa: E402


def _make_nova_api() -> BedrockAPI:
    """Build a BedrockAPI bound to a Nova model without instantiating a session."""
    api = BedrockAPI.__new__(BedrockAPI)
    api.model_name = "amazon.nova-lite-v1:0"
    return api


def _make_claude_api() -> BedrockAPI:
    """Build a BedrockAPI bound to a Claude model."""
    api = BedrockAPI.__new__(BedrockAPI)
    api.model_name = "anthropic.claude-3-sonnet-20240229-v1:0"
    return api


def _nova_high_effort_reasoning(api: BedrockAPI, config: GenerateConfig) -> bool:
    """Mirror the gate used in BedrockAPI.generate() for testability."""
    reasoning_cfg = api.reasoning_config(config)
    return (
        api.is_nova()
        and reasoning_cfg.get("reasoningConfig", {}).get("maxReasoningEffort") == "high"
    )


def test_nova_low_effort_keeps_max_tokens():
    """reasoning_effort='low' on Nova should NOT trigger the maxTokens=None path."""
    api = _make_nova_api()
    config = GenerateConfig(reasoning_effort="low", max_tokens=2048)
    assert _nova_high_effort_reasoning(api, config) is False


def test_nova_medium_effort_keeps_max_tokens():
    """reasoning_effort='medium' on Nova should NOT trigger the maxTokens=None path."""
    api = _make_nova_api()
    config = GenerateConfig(reasoning_effort="medium", max_tokens=2048)
    assert _nova_high_effort_reasoning(api, config) is False


def test_nova_high_effort_drops_max_tokens():
    """reasoning_effort='high' on Nova IS the only case that should drop maxTokens."""
    api = _make_nova_api()
    config = GenerateConfig(reasoning_effort="high", max_tokens=2048)
    assert _nova_high_effort_reasoning(api, config) is True


def test_nova_no_reasoning_keeps_max_tokens():
    """No reasoning_effort on Nova means no reasoningConfig at all → keep maxTokens."""
    api = _make_nova_api()
    config = GenerateConfig(max_tokens=2048)
    assert _nova_high_effort_reasoning(api, config) is False


def test_claude_high_effort_keeps_max_tokens():
    """Claude is not Nova, so the Nova-specific high-effort path never fires."""
    api = _make_claude_api()
    config = GenerateConfig(reasoning_effort="high", max_tokens=2048)
    assert _nova_high_effort_reasoning(api, config) is False
