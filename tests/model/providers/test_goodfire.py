import pytest
from test_helpers.utils import skip_if_no_goodfire

from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import get_model


@pytest.mark.anyio
@skip_if_no_goodfire
async def test_goodfire_api() -> None:
    """Test the Goodfire API provider."""
    model = get_model(
        "goodfire/meta-llama/Meta-Llama-3.1-8B-Instruct",
        config=GenerateConfig(
            max_tokens=50,  # Match other tests
        ),
    )

    message = ChatMessageUser(content="What is 2+2?")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1
