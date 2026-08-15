from pydantic import BaseModel
from test_helpers.utils import skip_if_no_groq

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    ResponseSchema,
    get_model,
)
from inspect_ai.model._providers.groq import chat_tool_choice
from inspect_ai.tool import ToolFunction
from inspect_ai.util import json_schema


@skip_if_no_groq
async def test_core_groq_api() -> None:
    model = get_model(
        "groq/openai/gpt-oss-20b",
        config=GenerateConfig(
            temperature=0.0,
            top_p=1.0,
        ),
    )

    message = ChatMessageUser(content="This is a test string. What are you?")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1


def test_chat_tool_choice_any_maps_to_required() -> None:
    # Inspect's tool_choice "any" means "use at least one tool" (force a tool call). Groq is
    # OpenAI-compatible, where the value that forces a call is "required" ("auto" lets the
    # model skip the tool), matching the openai/azureai/bedrock/mistral providers.
    assert chat_tool_choice("any") == "required"


def test_chat_tool_choice_other_values_pass_through() -> None:
    assert chat_tool_choice("auto") == "auto"
    assert chat_tool_choice("none") == "none"
    assert chat_tool_choice(ToolFunction(name="my_tool")) == {
        "type": "function",
        "function": {"name": "my_tool"},
    }


class NounPhrase(BaseModel):
    noun_phrase: str


@skip_if_no_groq
async def test_groq_api_with_response_schema() -> None:
    model = get_model(
        "groq/openai/gpt-oss-20b",
        config=GenerateConfig(
            response_schema=ResponseSchema(
                name="noun_phrase_schema",
                json_schema=json_schema(NounPhrase),
                description="Noun Phrase",
                strict=True,
            ),
        ),
    )

    message = ChatMessageUser(content="This is a test string. What are you?")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1
