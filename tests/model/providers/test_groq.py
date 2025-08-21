import pytest
from test_helpers.utils import skip_if_no_groq

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    ResponseSchema,
    get_model,
)
from inspect_ai.util import JSONSchema


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


@pytest.mark.anyio
@skip_if_no_groq
async def test_groq_api_with_response_schema() -> None:
    model = get_model(
        "openai/gpt-oss-20b",
        config=GenerateConfig(
            frequency_penalty=0.0,
            stop_seqs=None,
            max_tokens=50,
            presence_penalty=0.0,
            seed=None,
            temperature=0.0,
            top_p=1.0,
            response_schema=ResponseSchema(
                name="noun_phrase_schema",
                json_schema=JSONSchema(
                    type="object", properties={"noun_phrase": {"type": "string"}}
                ),
                description="Noun Phrase",
                strict=True,
            ),
        ),
    )

    message = ChatMessageUser(content="This is a test string. What are you?")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1
