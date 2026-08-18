"""Tests for Bedrock structured output (`response_schema`).

Claude on Bedrock honours `output_config.format` (the Converse-API analogue
of the native Anthropic provider's `output_format`). These tests pin that the
provider emits it into `additionalModelRequestFields` for Claude, and that
non-Claude models fall back gracefully instead of sending an unsupported field.
"""

from __future__ import annotations

from typing import Optional

import pytest

pytest.importorskip("aiobotocore")
pytest.importorskip("botocore")

from pydantic import BaseModel  # noqa: E402
from test_helpers.utils import skip_if_no_bedrock  # noqa: E402

from inspect_ai.model import (  # noqa: E402
    ChatMessageUser,
    ResponseSchema,
    get_model,
)
from inspect_ai.model._generate_config import GenerateConfig  # noqa: E402
from inspect_ai.model._providers.bedrock import BedrockAPI  # noqa: E402
from inspect_ai.util import json_schema  # noqa: E402


class _Person(BaseModel):
    name: str
    age: int


class _PersonOptional(BaseModel):
    name: str
    nickname: Optional[str] = None  # renders as anyOf:[string, null]


def _make_claude_api() -> BedrockAPI:
    """Build a BedrockAPI bound to a Claude model without a session."""
    api = BedrockAPI.__new__(BedrockAPI)
    api.model_name = "anthropic.claude-3-sonnet-20240229-v1:0"
    return api


def _make_nova_api() -> BedrockAPI:
    """Build a BedrockAPI bound to a Nova model without a session."""
    api = BedrockAPI.__new__(BedrockAPI)
    api.model_name = "amazon.nova-lite-v1:0"
    return api


def _person_schema() -> ResponseSchema:
    return ResponseSchema(name="person", json_schema=json_schema(_Person))


def test_claude_response_schema_emits_output_config_format():
    """Claude → response_schema becomes output_config.format (json_schema)."""
    api = _make_claude_api()
    config = GenerateConfig(response_schema=_person_schema())
    fields = api._additional_model_request_fields(config, False)
    fmt = fields["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["properties"].keys() == {"name", "age"}


def test_claude_response_schema_sets_additional_properties_false():
    """Bedrock requires additionalProperties:false on objects in the schema."""
    api = _make_claude_api()
    config = GenerateConfig(response_schema=_person_schema())
    fields = api._additional_model_request_fields(config, False)
    assert fields["output_config"]["format"]["schema"]["additionalProperties"] is False


def test_claude_response_schema_emitted_even_when_sampling_forbidden():
    """Structured output is not a sampling param; adaptive-thinking models keep it."""
    api = _make_claude_api()
    config = GenerateConfig(response_schema=_person_schema())
    fields = api._additional_model_request_fields(config, True)
    assert "format" in fields["output_config"]


def test_non_claude_response_schema_is_not_emitted():
    """Nova doesn't support output_config.format → don't send it."""
    api = _make_nova_api()
    config = GenerateConfig(response_schema=_person_schema())
    fields = api._additional_model_request_fields(config, False)
    assert "output_config" not in fields


def test_no_response_schema_no_output_config():
    """Regression guard: absent response_schema must not add output_config."""
    api = _make_claude_api()
    fields = api._additional_model_request_fields(GenerateConfig(), False)
    assert "output_config" not in fields


def test_optional_field_keeps_additional_properties_on_objects_only():
    """Optional fields render as anyOf; Bedrock rejects additionalProperties there."""
    api = _make_claude_api()
    config = GenerateConfig(
        response_schema=ResponseSchema(
            name="person", json_schema=json_schema(_PersonOptional)
        )
    )
    fields = api._additional_model_request_fields(config, False)
    schema = fields["output_config"]["format"]["schema"]
    assert schema["additionalProperties"] is False  # object node: locked
    assert (
        "additionalProperties" not in schema["properties"]["nickname"]
    )  # anyOf: clean


@pytest.mark.anyio
@skip_if_no_bedrock
async def test_bedrock_generate_with_response_schema() -> None:
    """End-to-end: Claude on Bedrock returns output conforming to the schema."""
    model = get_model(
        "bedrock/us.anthropic.claude-sonnet-4-6",
        config=GenerateConfig(
            response_schema=ResponseSchema(
                name="person",
                json_schema=json_schema(_Person),
            ),
        ),
    )
    message = ChatMessageUser(content="Invent a person and give their name and age.")
    response = await model.generate(input=[message])
    # Output must parse against the requested schema.
    _Person.model_validate_json(response.completion)
