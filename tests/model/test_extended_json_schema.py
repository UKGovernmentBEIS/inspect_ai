"""Test that extended JSON Schema fields are accepted by model provider APIs.

Validates that pattern, minLength, maxLength, minimum, maximum, and examples
fields work in both tool parameters and response schemas.
"""

from pydantic import BaseModel, Field
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_bedrock,
    skip_if_no_google,
    skip_if_no_grok,
    skip_if_no_groq,
    skip_if_no_mistral,
    skip_if_no_openai,
    skip_if_no_together,
)

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    ResponseSchema,
    get_model,
)
from inspect_ai.tool import ToolInfo, ToolParam, ToolParams
from inspect_ai.util import json_schema

# Tool with extended JSON Schema constraint fields
CONSTRAINED_TOOL = ToolInfo(
    name="register_user",
    description="Register a new user with a username and age.",
    parameters=ToolParams(
        properties={
            "username": ToolParam(
                type="string",
                description="The username.",
                pattern=r"^[a-zA-Z0-9_]+$",
                minLength=3,
                maxLength=20,
                examples=["alice", "bob_123"],
            ),
            "age": ToolParam(
                type="integer",
                description="The user's age.",
                minimum=0,
                maximum=150,
            ),
        },
        required=["username", "age"],
    ),
)

INPUT_TOOL = [
    ChatMessageUser(content="Register a user named alice who is 30 years old.")
]
INPUT_SCHEMA = [ChatMessageUser(content="Create a user profile for alice, age 30.")]


# Pydantic model with field constraints for response schema testing
class UserProfile(BaseModel):
    username: str = Field(min_length=3, max_length=20, pattern=r"^[a-zA-Z0-9_]+$")
    age: int = Field(ge=0, le=150)


RESPONSE_SCHEMA = ResponseSchema(
    name="user_profile",
    json_schema=json_schema(UserProfile),
)


def _response_config() -> GenerateConfig:
    return GenerateConfig(response_schema=RESPONSE_SCHEMA)


# -- OpenAI ------------------------------------------------------------------


@skip_if_no_openai
async def test_openai_extended_tool_schema():
    model = get_model("openai/gpt-4o-mini")
    result = await model.generate(input=INPUT_TOOL, tools=[CONSTRAINED_TOOL])
    assert result.completion is not None


@skip_if_no_openai
async def test_openai_extended_response_schema():
    model = get_model("openai/gpt-4o-mini")
    result = await model.generate(input=INPUT_SCHEMA, config=_response_config())
    assert result.completion is not None


# -- Anthropic ----------------------------------------------------------------


@skip_if_no_anthropic
async def test_anthropic_extended_tool_schema():
    model = get_model("anthropic/claude-sonnet-4-5")
    result = await model.generate(input=INPUT_TOOL, tools=[CONSTRAINED_TOOL])
    assert result.completion is not None


@skip_if_no_anthropic
async def test_anthropic_extended_response_schema():
    model = get_model("anthropic/claude-sonnet-4-5")
    result = await model.generate(input=INPUT_SCHEMA, config=_response_config())
    assert result.completion is not None


# -- Google -------------------------------------------------------------------


@skip_if_no_google
async def test_google_extended_tool_schema():
    model = get_model("google/gemini-2.0-flash")
    result = await model.generate(input=INPUT_TOOL, tools=[CONSTRAINED_TOOL])
    assert result.completion is not None


@skip_if_no_google
async def test_google_extended_response_schema():
    model = get_model("google/gemini-2.0-flash")
    result = await model.generate(input=INPUT_SCHEMA, config=_response_config())
    assert result.completion is not None


# -- Mistral ------------------------------------------------------------------


@skip_if_no_mistral
async def test_mistral_extended_tool_schema():
    model = get_model("mistral/mistral-large-latest")
    result = await model.generate(input=INPUT_TOOL, tools=[CONSTRAINED_TOOL])
    assert result.completion is not None


@skip_if_no_mistral
async def test_mistral_extended_response_schema():
    model = get_model("mistral/mistral-large-latest")
    result = await model.generate(input=INPUT_SCHEMA, config=_response_config())
    assert result.completion is not None


# -- Groq --------------------------------------------------------------------


@skip_if_no_groq
async def test_groq_extended_tool_schema():
    model = get_model("groq/llama-3.3-70b-versatile")
    result = await model.generate(input=INPUT_TOOL, tools=[CONSTRAINED_TOOL])
    assert result.completion is not None


@skip_if_no_groq
async def test_groq_extended_response_schema():
    model = get_model("groq/openai/gpt-oss-20b")
    result = await model.generate(input=INPUT_SCHEMA, config=_response_config())
    assert result.completion is not None


# -- Grok ---------------------------------------------------------------------


@skip_if_no_grok
async def test_grok_extended_tool_schema():
    model = get_model("grok/grok-4-fast-reasoning")
    result = await model.generate(input=INPUT_TOOL, tools=[CONSTRAINED_TOOL])
    assert result.completion is not None


@skip_if_no_grok
async def test_grok_extended_response_schema():
    model = get_model("grok/grok-4-fast-reasoning")
    result = await model.generate(input=INPUT_SCHEMA, config=_response_config())
    assert result.completion is not None


# -- Together -----------------------------------------------------------------


@skip_if_no_together
async def test_together_extended_tool_schema():
    model = get_model("together/MiniMaxAI/MiniMax-M2.5")
    result = await model.generate(input=INPUT_TOOL, tools=[CONSTRAINED_TOOL])
    assert result.completion is not None


@skip_if_no_together
async def test_together_extended_response_schema():
    model = get_model("together/MiniMaxAI/MiniMax-M2.5")
    result = await model.generate(input=INPUT_SCHEMA, config=_response_config())
    assert result.completion is not None


# -- Bedrock ------------------------------------------------------------------


@skip_if_no_bedrock
async def test_bedrock_extended_tool_schema():
    model = get_model("bedrock/amazon.nova-lite-v1:0")
    result = await model.generate(input=INPUT_TOOL, tools=[CONSTRAINED_TOOL])
    assert result.completion is not None
