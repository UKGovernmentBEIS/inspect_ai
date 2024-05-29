import pytest
from test_helpers.utils import skip_if_no_anthropic

from inspect_ai.model import GenerateConfig, get_model


@pytest.mark.asyncio
@skip_if_no_anthropic
async def test_anthropic_api() -> None:
    model = get_model(
        "anthropic/claude-2.1",
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

    message = "This is a test string. What are you?"
    response = await model.generate(input=message)
    assert len(response.completion) >= 1
