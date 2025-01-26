import pytest
from test_helpers.utils import skip_if_no_goodfire

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)


@pytest.mark.asyncio
@skip_if_no_goodfire
async def test_goodfire_api() -> None:
    model = get_model(
        "meta-llama/Meta-Llama-3.1-8B-Instruct",  # Using exact model name from SUPPORTED_MODELS
        config=GenerateConfig(
            max_tokens=50,
            temperature=0.0,
            top_p=1.0,
        ),
    )

    message = ChatMessageUser(content="What is 2+2?")
    response = await model.generate(input=[message], tools=[], tool_choice="none")
    assert len(response.completion) >= 1 