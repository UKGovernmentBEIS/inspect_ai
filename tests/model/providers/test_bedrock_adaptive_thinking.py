"""Tests for Bedrock Claude adaptive thinking + output_config emission.

Regression / behaviour tests for
https://github.com/UKGovernmentBEIS/inspect_ai/issues/3765

The Bedrock provider previously emitted
``additionalModelRequestFields={"reasoning_config": {"type": "enabled",
"budget_tokens": N}}`` for Claude. AWS Bedrock and Anthropic native both
expect the wrapper key to be ``"thinking"``; the prior form was silently
ignored. These tests pin the corrected shape and the adaptive-thinking /
4.7-auto-promotion paths.
"""

from __future__ import annotations

import pytest

pytest.importorskip("aiobotocore")
pytest.importorskip("botocore")

from inspect_ai.model._generate_config import GenerateConfig  # noqa: E402
from inspect_ai.model._providers.bedrock import BedrockAPI  # noqa: E402


def _make_api(model_name: str) -> BedrockAPI:
    """Build a BedrockAPI bound to ``model_name`` without instantiating a session.

    Follows the pattern from ``test_bedrock_nova_max_tokens.py``.
    """
    api = BedrockAPI.__new__(BedrockAPI)
    api.model_name = model_name
    return api


# Concrete Bedrock model ids.
CLAUDE_47 = "anthropic.claude-opus-4-7-20260101-v1:0"
CLAUDE_46 = "anthropic.claude-sonnet-4-6-20260101-v1:0"
CLAUDE_45 = "anthropic.claude-sonnet-4-5-20250929-v1:0"
CLAUDE_37 = "anthropic.claude-3-7-sonnet-20250219-v1:0"
CLAUDE_3_SONNET = "anthropic.claude-3-sonnet-20240229-v1:0"
NOVA_LITE = "amazon.nova-lite-v1:0"
GPT_OSS = "openai.gpt-oss-120b-1:0"


# --- adaptive thinking on frontier Claude ---------------------------------


def test_claude_47_reasoning_effort_emits_adaptive_output_config():
    api = _make_api(CLAUDE_47)
    config = GenerateConfig(reasoning_effort="high")
    fields = api.reasoning_config(config)
    assert fields == {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    }


def test_claude_46_reasoning_effort_emits_adaptive():
    api = _make_api(CLAUDE_46)
    config = GenerateConfig(reasoning_effort="medium")
    fields = api.reasoning_config(config)
    assert fields == {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "medium"},
    }


# --- budgeted thinking on pre-4.6 Claude ---------------------------------


def test_claude_45_reasoning_tokens_emits_budget_tokens():
    api = _make_api(CLAUDE_45)
    config = GenerateConfig(reasoning_tokens=4096)
    fields = api.reasoning_config(config)
    assert fields == {
        "thinking": {"type": "enabled", "budget_tokens": 4096},
    }


def test_claude_37_reasoning_tokens_emits_budget_tokens():
    api = _make_api(CLAUDE_37)
    config = GenerateConfig(reasoning_tokens=2048)
    fields = api.reasoning_config(config)
    assert fields == {
        "thinking": {"type": "enabled", "budget_tokens": 2048},
    }


# --- claude 4.7 auto-promotes reasoning_tokens to adaptive ----------------


def test_claude_47_reasoning_tokens_auto_promoted_to_adaptive():
    """4.7+ deprecates manual budget_tokens thinking; promote to adaptive."""
    api = _make_api(CLAUDE_47)
    config = GenerateConfig(reasoning_tokens=4096)
    fields = api.reasoning_config(config)
    assert fields == {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    }


# --- effort emission (independent of thinking) ----------------------------


def test_claude_effort_emits_output_config_on_frontier():
    api = _make_api(CLAUDE_47)
    config = GenerateConfig(effort="high")
    fields = api.reasoning_config(config)
    assert fields == {"output_config": {"effort": "high"}}


def test_claude_effort_max_demoted_pre_46():
    api = _make_api(CLAUDE_45)
    config = GenerateConfig(effort="max")
    fields = api.reasoning_config(config)
    assert fields == {"output_config": {"effort": "high"}}


def test_claude_effort_xhigh_demoted_pre_47():
    api = _make_api(CLAUDE_46)
    config = GenerateConfig(effort="xhigh")
    fields = api.reasoning_config(config)
    assert fields == {"output_config": {"effort": "high"}}


def test_claude_effort_xhigh_preserved_on_47():
    api = _make_api(CLAUDE_47)
    config = GenerateConfig(effort="xhigh")
    fields = api.reasoning_config(config)
    assert fields == {"output_config": {"effort": "xhigh"}}


# --- empty / no-config paths ---------------------------------------------


def test_claude_no_config_returns_empty_fields():
    api = _make_api(CLAUDE_47)
    config = GenerateConfig()
    fields = api.reasoning_config(config)
    assert fields == {}


def test_claude_3_sonnet_no_thinking_for_non_thinking_model():
    """Claude 3 is not a thinking model — must not emit a thinking block."""
    api = _make_api(CLAUDE_3_SONNET)
    config = GenerateConfig(reasoning_effort="high")
    fields = api.reasoning_config(config)
    assert "thinking" not in fields


# --- regressions on other branches ---------------------------------------


def test_nova_unaffected():
    api = _make_api(NOVA_LITE)
    config = GenerateConfig(reasoning_effort="medium")
    fields = api.reasoning_config(config)
    assert fields == {
        "reasoningConfig": {"type": "enabled", "maxReasoningEffort": "medium"},
    }


def test_gpt_oss_unaffected():
    api = _make_api(GPT_OSS)
    config = GenerateConfig(reasoning_effort="low")
    fields = api.reasoning_config(config)
    assert fields == {"reasoning_effort": "low"}


# --- reasoning_effort + reasoning_tokens precedence -----------------------


def test_claude_46_reasoning_effort_wins_over_reasoning_tokens():
    """When both are set on a frontier model, adaptive wins (matches anthropic.py)."""
    api = _make_api(CLAUDE_46)
    config = GenerateConfig(reasoning_effort="high", reasoning_tokens=8192)
    fields = api.reasoning_config(config)
    assert fields == {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    }


# --- helper methods ------------------------------------------------------


def test_is_using_thinking_false_on_claude_3():
    api = _make_api(CLAUDE_3_SONNET)
    assert (
        api.is_using_thinking(
            GenerateConfig(reasoning_effort="high", reasoning_tokens=4096)
        )
        is False
    )


def test_is_using_thinking_true_on_4_5_with_reasoning_tokens():
    api = _make_api(CLAUDE_45)
    assert api.is_using_thinking(GenerateConfig(reasoning_tokens=4096)) is True


def test_is_claude_4_6_or_later():
    assert _make_api(CLAUDE_47).is_claude_4_6_or_later() is True
    assert _make_api(CLAUDE_46).is_claude_4_6_or_later() is True
    assert _make_api(CLAUDE_45).is_claude_4_6_or_later() is False
    assert _make_api(CLAUDE_3_SONNET).is_claude_4_6_or_later() is False
    assert _make_api(NOVA_LITE).is_claude_4_6_or_later() is False


# --- review findings: currently-failing regression tests -------------------
#
# Bug 1: generate() merges `_additional_model_request_fields()` (which carries
# `output_config.format` for response_schema) with `reasoning_config()` via a
# shallow dict union, so a reasoning-produced `output_config` silently drops
# the structured-output format.
#
# Bug 2: Claude 4.0 Bedrock ids have no minor version (e.g.
# `anthropic.claude-opus-4-20250514-v1:0`), so the "unrecognised future minor"
# fallback in `is_claude_4_6_or_later` / `is_claude_4_7_or_later` misclassifies
# them as 4.6+/4.7+. Adaptive thinking on these models returns a 400 from
# Bedrock (they are budget_tokens-only per the AWS extended-thinking docs).

from pydantic import BaseModel  # noqa: E402

from inspect_ai.model import ResponseSchema  # noqa: E402
from inspect_ai.util import json_schema  # noqa: E402

CLAUDE_40_OPUS = "anthropic.claude-opus-4-20250514-v1:0"
CLAUDE_40_SONNET = "anthropic.claude-sonnet-4-20250514-v1:0"


class _Person(BaseModel):
    name: str
    age: int


def _merged_request_fields(api: BedrockAPI, config: GenerateConfig) -> dict:
    """Reproduce the additionalModelRequestFields merge in BedrockAPI.generate()."""
    return api._additional_model_request_fields(config, False) | api.reasoning_config(
        config
    )


def test_response_schema_preserved_with_reasoning_effort():
    api = _make_api(CLAUDE_46)
    config = GenerateConfig(
        reasoning_effort="high",
        response_schema=ResponseSchema(name="person", json_schema=json_schema(_Person)),
    )
    fields = _merged_request_fields(api, config)
    assert fields["output_config"]["effort"] == "high"
    assert "format" in fields["output_config"], (
        "structured-output format clobbered by reasoning output_config"
    )


def test_response_schema_preserved_with_effort():
    api = _make_api(CLAUDE_47)
    config = GenerateConfig(
        effort="medium",
        response_schema=ResponseSchema(name="person", json_schema=json_schema(_Person)),
    )
    fields = _merged_request_fields(api, config)
    assert fields["output_config"]["effort"] == "medium"
    assert "format" in fields["output_config"], (
        "structured-output format clobbered by reasoning output_config"
    )


def test_claude_40_dated_ids_not_classified_as_4_6_or_later():
    assert _make_api(CLAUDE_40_OPUS).is_claude_4_6_or_later() is False
    assert _make_api(CLAUDE_40_SONNET).is_claude_4_6_or_later() is False


def test_claude_40_dated_ids_not_classified_as_4_7_or_later():
    assert _make_api(CLAUDE_40_OPUS).is_claude_4_7_or_later() is False
    assert _make_api(CLAUDE_40_SONNET).is_claude_4_7_or_later() is False


def test_claude_40_reasoning_effort_does_not_emit_adaptive():
    """Claude 4.0 is budget_tokens-only; adaptive thinking 400s on Bedrock."""
    fields = _make_api(CLAUDE_40_OPUS).reasoning_config(
        GenerateConfig(reasoning_effort="high")
    )
    assert fields.get("thinking", {}).get("type") != "adaptive"


def test_claude_40_reasoning_tokens_not_promoted_to_adaptive():
    """Claude 4.0 is budget_tokens-only; must not be auto-promoted like 4.7+."""
    fields = _make_api(CLAUDE_40_OPUS).reasoning_config(
        GenerateConfig(reasoning_tokens=4096)
    )
    assert fields == {"thinking": {"type": "enabled", "budget_tokens": 4096}}
