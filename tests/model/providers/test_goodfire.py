import pytest

from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._providers.goodfire import GoodfireAPI


@pytest.mark.asyncio
async def test_goodfire_api() -> None:
    """Test the Goodfire API provider."""
    model = GoodfireAPI(
        "meta-llama/Meta-Llama-3.1-8B-Instruct",  # Using exact model name from SUPPORTED_MODELS
        config=GenerateConfig(
            max_tokens=50,  # Match other tests
        ),
    )

    message = ChatMessageUser(content="What is 2+2?")
    response = await model.generate(input=[message], tools=[], tool_choice="none")
    assert len(response.completion) >= 1
