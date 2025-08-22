import pytest
from pydantic import BaseModel
from test_helpers.utils import skip_if_no_groq

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    ResponseSchema,
    get_model,
)
from inspect_ai.util import json_schema


@pytest.mark.anyio
@skip_if_no_groq
async def test_groq_api() -> None:
    model = get_model(
        "groq/llama3-70b-8192",
        config=GenerateConfig(
            frequency_penalty=0.0,
            stop_seqs=None,
            max_tokens=50,
            presence_penalty=0.0,
            seed=None,
            temperature=0.0,
            top_p=1.0,
        ),
    )

    message = ChatMessageUser(content="This is a test string. What are you?")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1


class NounPhrase(BaseModel):
    noun_phrase: str


@pytest.mark.anyio
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
