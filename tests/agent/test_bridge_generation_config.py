"""Unit tests for bridge generation-parameter forwarding.

These exercise the per-format `generate_config_from_*` extractors together with
`clear_generation_params` (the helper applied when a bridge is configured not to
forward client generation parameters, the default). They are fast and require no
provider SDKs or API keys.
"""

from typing import Any

import pytest
from pydantic import BaseModel

from inspect_ai.agent._bridge._errors import (
    BridgePolicyError,
    provider_error_payload,
)
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
    _unmodelled_schema_keywords,
    clear_generation_params,
    client_json_schema,
    validate_client_config,
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
    "effort",
    "reasoning_effort",
    "reasoning_tokens",
    "reasoning_summary",
    "verbosity",
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
        "output_config": {"effort": "high"},
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
    # output_config.effort (adaptive-thinking depth) maps to effort
    assert config.effort == "high"

    clear_generation_params(config)
    _assert_cleared(config)
    # reasoning_tokens and effort specifically must be among the cleared fields
    assert config.reasoning_tokens is None
    assert config.effort is None
    # `system` no longer flows through GenerateConfig: it is hoisted into
    # leading ChatMessageSystem messages (one per block) by the request impl
    # (see the impl-level tests in test_bridge_anthropic_messages.py)
    assert config.system_message is None
    assert config.stop_seqs == ["foo"]
    assert config.parallel_tool_calls is False


def test_anthropic_adaptive_thinking_effort_forwarded():
    # `thinking: {"type": "adaptive"}` carries no budget_tokens; the reasoning
    # depth arrives via `output_config.effort`. It must be forwarded rather than
    # silently dropped (regression test for the bridge ignoring adaptive mode).
    json_data = {
        "model": "inspect",
        "max_tokens": 32000,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    }

    config = generate_config_from_anthropic(json_data)
    # adaptive mode has no explicit token budget
    assert config.reasoning_tokens is None
    # but the effort knob is preserved
    assert config.effort == "high"


def test_google_forward_then_clear():
    generation_config = {
        "temperature": 0.8,
        "maxOutputTokens": 2048,
        "topP": 0.9,
        "topK": 2,
        # structural
        "stopSequences": ["foo"],
        # structured output (Gemini OpenAPI-style schema, uppercase type names)
        "responseMimeType": "application/json",
        "responseSchema": {
            "type": "OBJECT",
            "properties": {
                "reasoning": {"type": "STRING"},
                "confidence": {"type": "NUMBER"},
            },
            "required": ["reasoning", "confidence"],
        },
    }

    config = generate_config_from_google(generation_config)
    assert config.temperature == 0.8
    assert config.max_tokens == 2048
    assert config.top_p == 0.9
    assert config.top_k == 2

    # responseSchema is mapped, with types normalized to lowercase JSON Schema
    assert config.response_schema is not None
    json_schema = config.response_schema.json_schema
    assert json_schema.type == "object"
    assert json_schema.properties is not None
    assert json_schema.properties["confidence"].type == "number"
    assert json_schema.required == ["reasoning", "confidence"]

    clear_generation_params(config)
    _assert_cleared(config)
    assert config.stop_seqs == ["foo"]
    # structured output survives clearing (it's functional, not a tuning knob)
    assert config.response_schema is not None


def test_google_response_json_schema_used_directly():
    # `responseJsonSchema` is already standard JSON Schema (lowercase types)
    generation_config = {
        "responseMimeType": "application/json",
        "responseJsonSchema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
    }

    config = generate_config_from_google(generation_config)
    assert config.response_schema is not None
    assert config.response_schema.json_schema.type == "object"
    assert config.response_schema.json_schema.properties is not None


def test_google_no_schema_leaves_response_schema_unset():
    config = generate_config_from_google({"temperature": 0.5})
    assert config.response_schema is None


def test_anthropic_output_config_format_maps_to_response_schema():
    """`output_config.format` is Anthropic's native structured-output request.

    It had no extraction site at all, so a client asking for JSON silently got
    prose. Its sibling `output_config.effort` WAS read, which is what made the
    gap easy to miss.
    """
    config = generate_config_from_anthropic(
        {
            "model": "inspect",
            "messages": [],
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer"],
                    },
                }
            },
        }
    )
    assert config.response_schema is not None
    assert config.response_schema.json_schema.type == "object"
    # structured output is not a tuning knob, so it must survive clearing
    clear_generation_params(config)
    assert config.response_schema is not None


def test_anthropic_invalid_output_config_schema_is_rejected_not_raised():
    """A bad schema must answer 400, not escape as a raw `ValidationError`.

    `JSONSchema.model_validate` raises `ValidationError`, and an uncaught one is
    worse than the bad value: `provider_error_payload` reports `status: None`,
    which the sandbox service treats as a translation failure -- traceback in the
    log, no status for the client. That is the unreadable outcome this module
    exists to prevent, so it must be the same `BridgePolicyError` 400 that an
    invalid generation param gets.
    """
    with pytest.raises(BridgePolicyError) as ex:
        generate_config_from_anthropic(
            {
                "model": "inspect",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "hi"}],
                "output_config": {
                    "format": {"type": "json_schema", "schema": {"type": 5}}
                },
            }
        )
    assert "output_config.format.schema" in str(ex.value)
    assert provider_error_payload(ex.value)["status"] == 400


def test_anthropic_invalid_output_config_name_is_rejected_not_raised():
    """A bad `format.name` must answer 400, not escape as a raw `ValidationError`.

    `ResponseSchema` validates `name` on construction, so a non-string one
    escapes the same way an invalid schema would -- `status: None`, a traceback
    in the log and no status for the client. New surface with this mapping:
    before it, the whole `output_config.format` was ignored.
    """
    with pytest.raises(BridgePolicyError) as ex:
        generate_config_from_anthropic(
            {
                "model": "inspect",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "hi"}],
                "output_config": {
                    "format": {
                        "type": "json_schema",
                        "name": 5,
                        "schema": {"type": "object"},
                    }
                },
            }
        )
    assert "output_config.format.name" in str(ex.value)
    assert provider_error_payload(ex.value)["status"] == 400


def test_anthropic_output_config_effort_and_format_coexist():
    config = generate_config_from_anthropic(
        {
            "model": "inspect",
            "messages": [],
            "output_config": {
                "effort": "low",
                "format": {"type": "json_schema", "schema": {"type": "object"}},
            },
        }
    )
    assert config.effort == "low"
    assert config.response_schema is not None


def test_google_thinking_config_maps_to_reasoning_tokens():
    """Gemini's thinking budget had no extraction site.

    The provider rebuilds a `ThinkingConfig` from `reasoning_tokens`, so the
    budget only needed mapping onto it; without this a client asking for a
    thinking budget silently got the model default.
    """
    config = generate_config_from_google({"thinkingConfig": {"thinkingBudget": 2048}})
    assert config.reasoning_tokens == 2048

    snake = generate_config_from_google({"thinking_config": {"thinking_budget": 512}})
    assert snake.reasoning_tokens == 512

    # it IS a tuning knob, so it must clear
    clear_generation_params(config)
    assert config.reasoning_tokens is None


def test_openai_responses_text_verbosity_is_read():
    """`text.verbosity` was never read off the request.

    It has a GenerateConfig slot and the provider already sends it; only the
    extraction was missing.
    """
    config = generate_config_from_openai_responses(
        {"model": "inspect", "input": "hello", "text": {"verbosity": "low"}}
    )
    assert config.verbosity == "low"

    # And it must clear like every other generation param. A bridge left on the
    # default `forward_generation_config=False` drops the client's tuning knobs so
    # they fall back to the eval's own config; verbosity extracted but not cleared
    # would leak the scaffold's value to the served model whenever the eval config
    # leaves it unset -- the common case, and the exact defect class this change is
    # about (one swept parameter measured under several labels).
    clear_generation_params(config)
    assert config.verbosity is None


def test_openai_responses_text_format_and_verbosity_coexist():
    config = generate_config_from_openai_responses(
        {
            "model": "inspect",
            "input": "hello",
            "text": {
                "verbosity": "low",
                "format": {
                    "type": "json_schema",
                    "name": "message",
                    "schema": {"type": "object"},
                },
            },
        }
    )
    assert config.verbosity == "low"
    assert config.response_schema is not None


@pytest.mark.parametrize(
    "extractor,json_data,expected_field",
    [
        (
            generate_config_from_anthropic,
            {"model": "m", "messages": [], "stop_sequences": 5},
            "stop_seqs",
        ),
        (
            generate_config_from_anthropic,
            {"model": "m", "messages": [], "output_config": {"effort": "banana"}},
            "effort",
        ),
        (
            generate_config_from_anthropic,
            {"model": "m", "messages": [], "temperature": "hot"},
            "temperature",
        ),
        (
            generate_config_from_openai_completions,
            {"model": "m", "messages": [], "seed": "not-an-int"},
            "seed",
        ),
        (
            generate_config_from_openai_completions,
            {"model": "m", "messages": [], "reasoning_effort": "banana"},
            "reasoning_effort",
        ),
    ],
)
def test_invalid_client_value_is_rejected_not_recorded(
    extractor, json_data, expected_field
):
    """A bad request value must 400, not poison the transcript.

    pydantic does not validate on assignment, so an extractor will happily put
    any value into a typed field. That value serializes into the `ModelEvent`
    and then fails `model_validate` when the event is READ -- aborting the read
    of the WHOLE sample transcript, not just that event (`inspect ctl sample
    events` 500s; every log reader hits the same error). Measured live: one
    `output_config.effort: "banana"` request made 55 subsequent events
    unreadable.

    `stop_seqs` and `seed` reach this without any bridge configuration, since
    they are structural rather than generation params.
    """
    config = extractor(json_data)
    # the raw extractor accepts it -- that is the hazard being guarded
    assert getattr(config, expected_field) is not None

    with pytest.raises(BridgePolicyError, match=expected_field):
        validate_client_config(config)


def test_valid_client_config_passes_validation():
    config = generate_config_from_anthropic(
        {
            "model": "m",
            "messages": [],
            "max_tokens": 7,
            "temperature": 0.5,
            "stop_sequences": ["x"],
            "output_config": {"effort": "low"},
        }
    )
    validate_client_config(config)  # must not raise


@pytest.mark.anyio
async def test_bridged_request_rejects_invalid_value_at_the_call_site():
    """The rejection must be wired into the REQUEST PATH, not just available.

    Asserting on `validate_client_config` alone passes even when no caller
    invokes it, so this drives the real
    `inspect_anthropic_api_request_impl` and asserts it raises before reaching
    the model. A model that is never called is the evidence: it proves the
    request was rejected rather than sent and recorded.
    """
    from inspect_ai.agent._agent import AgentState
    from inspect_ai.agent._bridge.anthropic_api_impl import (
        inspect_anthropic_api_request_impl,
    )
    from inspect_ai.agent._bridge.types import AgentBridge
    from inspect_ai.model._chat_message import ChatMessageUser
    from inspect_ai.model._model import get_model
    from inspect_ai.model._model_output import ModelOutput

    called = []

    def _never(input, tools, tool_choice, config):
        called.append(config)
        return ModelOutput.from_content(model="mockllm/model", content="unreachable")

    model = get_model("mockllm/model", custom_outputs=_never)
    bridge = AgentBridge(
        state=AgentState(messages=[ChatMessageUser(content="hi")]),
        model=str(model),
        forward_generation_config=True,
    )
    bridge.model_aliases = {"claude-sonnet-5": model}

    with pytest.raises(BridgePolicyError, match="effort"):
        await inspect_anthropic_api_request_impl(
            json_data={
                "model": "claude-sonnet-5",
                "max_tokens": 64,
                "messages": [{"role": "user", "content": "hi"}],
                "output_config": {"effort": "banana"},
            },
            headers=None,
            web_search=None,
            code_execution=None,
            bridge=bridge,
        )

    assert called == [], "request must be rejected before the model is called"


def test_google_generation_config_fields_the_provider_sends_are_all_read():
    """Every `generationConfig` field the Google provider sends must be read.

    The provider passes `candidate_count`, `presence_penalty`,
    `frequency_penalty`, `response_logprobs` and `logprobs` to the SDK, but the
    extractor read none of them, so a client setting any silently got the model
    default.
    """
    config = generate_config_from_google(
        {
            "candidateCount": 2,
            "presencePenalty": 0.5,
            "frequencyPenalty": 0.25,
            "responseLogprobs": True,
            "logprobs": 3,
        }
    )
    # candidateCount is deliberately NOT forwarded: the response builder emits
    # exactly one candidate, so forwarding it would bill for N and return 1.
    assert config.num_choices is None
    assert config.presence_penalty == 0.5
    assert config.frequency_penalty == 0.25
    assert config.logprobs is True
    assert config.top_logprobs == 3

    snake = generate_config_from_google(
        {"presence_penalty": 0.1, "frequency_penalty": 0.2}
    )
    assert snake.presence_penalty == 0.1
    assert snake.frequency_penalty == 0.2

    # all five are tuning knobs, so all must clear
    clear_generation_params(config)
    _assert_cleared(config)


def test_google_usage_metadata_reports_thinking_tokens():
    """A bridged Gemini client must be able to see thinking tokens.

    The provider already parses `thoughts_token_count` into
    `usage.reasoning_tokens`, but the bridge's usage metadata omitted it, so a
    client measuring thinking tokens through the bridge got nothing -- the same
    defect class as the Anthropic `output_tokens_details` bug.
    """
    from inspect_ai.agent._bridge.google_api_impl import gemini_usage_metadata
    from inspect_ai.model._model_output import ModelUsage

    with_thinking = gemini_usage_metadata(
        ModelUsage(
            input_tokens=10, output_tokens=40, total_tokens=50, reasoning_tokens=30
        )
    )
    assert with_thinking["thoughtsTokenCount"] == 30

    # ...and the pair must obey Gemini's own arithmetic. `candidatesTokenCount`
    # EXCLUDES thinking tokens upstream, while Inspect's `output_tokens` includes
    # them, so emitting both without subtracting made the two sum past
    # `totalTokenCount` -- a response no real Gemini call could produce. Asserting
    # only `thoughtsTokenCount` let that through.
    assert with_thinking["candidatesTokenCount"] == 10
    assert (
        with_thinking["candidatesTokenCount"] + with_thinking["thoughtsTokenCount"]
        == 40
    )

    # absent rather than zeroed, so "no thinking" and "not reported" stay distinct
    without = gemini_usage_metadata(
        ModelUsage(input_tokens=10, output_tokens=40, total_tokens=50)
    )
    assert "thoughtsTokenCount" not in without
    # nothing to subtract, so output_tokens passes straight through
    assert without["candidatesTokenCount"] == 40


@pytest.fixture
def _warn_once_messages() -> Any:
    # warn_once dedupes via a module-level list; clear it and yield it so the
    # test can assert on what was emitted. caplog isn't reliable here because
    # init_logger sets propagate=False on the inspect_ai logger once any
    # earlier test triggers it.
    from inspect_ai._util import logger as _inspect_logger

    _inspect_logger._warned.clear()
    yield _inspect_logger._warned
    _inspect_logger._warned.clear()


def test_unmodelled_schema_keywords_reports_only_real_losses():
    """Dropped keywords must be detected, without crying wolf.

    `JSONSchema` is a pydantic model with the default `extra="ignore"`, so any
    keyword it lacks a field for is silently dropped. The detection has to walk
    nested schemas to be useful, and skip client-controlled values to be
    trustworthy -- a warning that fires on every schema teaches people to ignore
    it.
    """

    # pydantic emits `title` on every field, so a flat model loses nothing
    class Flat(BaseModel):
        name: str
        age: int

    assert _unmodelled_schema_keywords(Flat.model_json_schema()) == set()

    # ...but any nested model or enum emits `$defs`/`$ref`, which does lose
    # something: the `$ref` property collapses to an empty schema.
    class Address(BaseModel):
        street: str

    class Person(BaseModel):
        name: str
        address: Address

    assert _unmodelled_schema_keywords(Person.model_json_schema()) == {"$defs", "$ref"}

    # nested schema positions are walked
    assert _unmodelled_schema_keywords(
        {
            "type": "array",
            "items": {"type": "object", "properties": {"a": {"minItems": 2}}},
            "anyOf": [{"const": 3}],
        }
    ) == {"minItems", "const"}

    # `properties` keys are client-chosen names, not keywords
    assert (
        _unmodelled_schema_keywords(
            {
                "type": "object",
                "properties": {
                    "$ref": {"type": "string"},
                    "allOf": {"type": "integer"},
                },
            }
        )
        == set()
    )

    # `default`/`examples` hold client values that may themselves look like
    # schemas; walking them would report keywords that were never dropped
    assert (
        _unmodelled_schema_keywords(
            {
                "type": "object",
                "properties": {
                    "x": {
                        "type": "object",
                        "default": {"const": 1, "$ref": "#/nope"},
                        "examples": [{"allOf": []}],
                    }
                },
            }
        )
        == set()
    )


def test_client_json_schema_warns_when_keywords_are_dropped(_warn_once_messages):
    """A silently weakened schema must at least be diagnosable.

    A dropped `$ref` leaves the property an unconstrained `{}` while it stays
    `required`, so the model is free to return anything there and the client's own
    validation fails on the response. Without the warning there is nothing tying
    that failure back to the bridge.
    """

    class Address(BaseModel):
        street: str

    class Person(BaseModel):
        name: str
        address: Address

    schema = client_json_schema(
        Person.model_json_schema(), "output_config.format.schema"
    )

    assert len(_warn_once_messages) == 1
    assert "output_config.format.schema" in _warn_once_messages[0]
    assert "$ref" in _warn_once_messages[0]
    assert "$defs" in _warn_once_messages[0]

    # the dropped `$ref` is the loss the warning is about: `address` survives as
    # an empty schema rather than the nested object the client asked for
    assert schema.properties is not None
    assert schema.properties["address"].model_dump(exclude_none=True) == {}
    assert schema.required == ["name", "address"]


def test_client_json_schema_silent_for_fully_modelled_schema(_warn_once_messages):
    client_json_schema(
        {
            "type": "object",
            "properties": {"a": {"type": "string", "pattern": "x"}},
            "required": ["a"],
        },
        "output_config.format.schema",
    )
    assert _warn_once_messages == []
