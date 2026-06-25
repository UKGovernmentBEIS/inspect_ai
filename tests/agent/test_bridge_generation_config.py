"""Unit tests for bridge generation-parameter forwarding.

These exercise the per-format `generate_config_from_*` extractors together with
`clear_generation_params` (the helper applied when a bridge is configured not to
forward client generation parameters, the default). They are fast and require no
provider SDKs or API keys.
"""

from inspect_ai.agent._bridge.anthropic_api_impl import generate_config_from_anthropic
from inspect_ai.agent._bridge.completions import (
    generate_config_from_openai_completions,
)
from inspect_ai.agent._bridge.google_api_impl import generate_config_from_google
from inspect_ai.agent._bridge.responses_impl import (
    generate_config_from_openai_responses,
)
from inspect_ai.agent._bridge.util import (
    _GENERATION_PARAM_FIELDS,
    clear_generation_params,
)

# generation-tuning fields that must be dropped when not forwarding.
# Hard-coded (not derived from the implementation's list) so this test fails if
# the helper's field list drifts from what we expect to be cleared.
GENERATION_FIELDS = {
    "max_tokens",
    "temperature",
    "top_p",
    "top_k",
    "frequency_penalty",
    "presence_penalty",
    "num_choices",
    "logprobs",
    "top_logprobs",
    "prompt_logprobs",
    "logit_bias",
    "reasoning_effort",
    "reasoning_tokens",
    "reasoning_summary",
}


def test_generation_param_fields_match_expected():
    # guard against the helper's cleared-field list drifting from this test's
    # expectations in either direction
    assert set(_GENERATION_PARAM_FIELDS) == GENERATION_FIELDS


# structural fields that must always survive clearing
STRUCTURAL_FIELDS = (
    "system_message",
    "stop_seqs",
    "response_schema",
    "parallel_tool_calls",
    "seed",
)


def _assert_cleared(config) -> None:
    for field in GENERATION_FIELDS:
        assert getattr(config, field) is None, f"{field} should be cleared"


def test_openai_completions_forward_then_clear():
    json_data = {
        "model": "inspect",
        "max_tokens": 256,
        "temperature": 0.8,
        "top_p": 0.9,
        "frequency_penalty": 1.0,
        "presence_penalty": 1.5,
        "n": 3,
        "logprobs": True,
        "top_logprobs": 3,
        "logit_bias": {42: 10},
        "reasoning_effort": "low",
        # structural
        "stop": ["foo"],
        "seed": 42,
        "parallel_tool_calls": True,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "message", "schema": {"type": "object"}},
        },
    }

    # raw extraction forwards the generation-tuning params
    config = generate_config_from_openai_completions(json_data)
    assert config.max_tokens == 256
    assert config.temperature == 0.8
    assert config.num_choices == 3
    assert config.logprobs is True
    assert config.reasoning_effort == "low"

    # clearing drops gen-tuning, keeps structural
    clear_generation_params(config)
    _assert_cleared(config)
    assert config.stop_seqs == ["foo"]
    assert config.seed == 42
    assert config.parallel_tool_calls is True
    assert config.response_schema is not None


def test_openai_responses_forward_then_clear():
    json_data = {
        "model": "inspect",
        "instructions": "You are a dope model.",
        "max_output_tokens": 2048,
        "temperature": 0.8,
        "top_p": 0.9,
        "top_logprobs": 3,
        "include": ["message.output_text.logprobs"],
        "reasoning": {"effort": "low", "summary": "auto"},
        # structural
        "parallel_tool_calls": True,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "message",
                "schema": {"type": "object"},
            }
        },
    }

    config = generate_config_from_openai_responses(json_data)
    assert config.max_tokens == 2048
    assert config.temperature == 0.8
    assert config.reasoning_effort == "low"
    assert config.reasoning_summary == "auto"
    assert config.logprobs is True
    assert config.top_logprobs == 3

    clear_generation_params(config)
    _assert_cleared(config)
    assert config.system_message == "You are a dope model."
    assert config.parallel_tool_calls is True
    assert config.response_schema is not None


def test_anthropic_forward_then_clear():
    json_data = {
        "model": "inspect",
        "max_tokens": 4096,
        "temperature": 0.8,
        "top_k": 2,
        "top_p": 0.9,
        "thinking": {"type": "enabled", "budget_tokens": 2048},
        # structural
        "system": "You are a dope model.",
        "stop_sequences": ["foo"],
        "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
    }

    config = generate_config_from_anthropic(json_data)
    assert config.max_tokens == 4096
    assert config.temperature == 0.8
    assert config.top_k == 2
    # anthropic thinking budget maps to reasoning_tokens
    assert config.reasoning_tokens == 2048

    clear_generation_params(config)
    _assert_cleared(config)
    # reasoning_tokens specifically must be among the cleared fields
    assert config.reasoning_tokens is None
    assert config.system_message == "You are a dope model."
    assert config.stop_seqs == ["foo"]
    assert config.parallel_tool_calls is False


def test_google_forward_then_clear():
    generation_config = {
        "temperature": 0.8,
        "maxOutputTokens": 2048,
        "topP": 0.9,
        "topK": 2,
        # structural
        "stopSequences": ["foo"],
    }

    config = generate_config_from_google(generation_config)
    assert config.temperature == 0.8
    assert config.max_tokens == 2048
    assert config.top_p == 0.9
    assert config.top_k == 2

    clear_generation_params(config)
    _assert_cleared(config)
    assert config.stop_seqs == ["foo"]
