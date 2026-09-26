"""Tests for Bedrock Claude max_tokens defaults.

Regression test for https://github.com/UKGovernmentBEIS/inspect_ai/issues/5569

Claude 4 and later models fell through to DEFAULT_MAX_TOKENS (2048), which
cuts agentic tool calls in half, while the anthropic provider defaults the
same models to 32000.
"""

from __future__ import annotations

import pytest

pytest.importorskip("aiobotocore")
pytest.importorskip("botocore")

from inspect_ai._util.constants import DEFAULT_MAX_TOKENS  # noqa: E402
from inspect_ai.model._providers.bedrock import BedrockAPI  # noqa: E402


def _make_bedrock_api(model_name: str) -> BedrockAPI:
    """Build a BedrockAPI bound to a model without instantiating a session."""
    api = BedrockAPI.__new__(BedrockAPI)
    api.model_name = model_name
    return api


@pytest.mark.parametrize(
    "model_name",
    [
        "anthropic.claude-opus-4-7-20260101-v1:0",
        "anthropic.claude-sonnet-4-5-20250929-v1:0",
        "anthropic.claude-haiku-4-5-20251001-v1:0",
        # Cross-region inference profile prefix.
        "eu.anthropic.claude-opus-4-7-20260101-v1:0",
    ],
)
def test_claude_4_plus_default_matches_anthropic_provider(model_name: str) -> None:
    assert _make_bedrock_api(model_name).max_tokens() == 32000


@pytest.mark.parametrize(
    "model_name,expected",
    [
        # Claude 3 keeps the existing 4096 default.
        ("anthropic.claude-3-sonnet-20240229-v1:0", 4096),
        ("anthropic.claude-3-5-sonnet-20241022-v2:0", 4096),
        # Non-Claude families are unchanged.
        ("meta.llama3-70b-instruct-v1:0", 2048),
        ("meta.llama3-8b-instruct-v1:0", 2048),
        ("mistral.mistral-large-2402-v1:0", 8192),
        ("amazon.nova-lite-v1:0", DEFAULT_MAX_TOKENS),
    ],
)
def test_other_families_keep_their_defaults(model_name: str, expected: int) -> None:
    assert _make_bedrock_api(model_name).max_tokens() == expected
