import pytest
from test_helpers.utils import skip_if_no_openai

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)


@pytest.mark.asyncio
@skip_if_no_openai
async def test_openai_api() -> None:
    model = get_model(
        "openai/gpt-3.5-turbo",
        config=GenerateConfig(
            frequency_penalty=0.0,
            stop_seqs=None,
            max_tokens=50,
            presence_penalty=0.0,
            logit_bias=dict([(42, 10), (43, -10)]),
            seed=None,
            temperature=0.0,
            top_p=1.0,
        ),
    )

    message = ChatMessageUser(content="This is a test string. What are you?")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1
