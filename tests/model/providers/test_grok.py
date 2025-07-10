import pytest
from test_helpers.utils import skip_if_no_grok

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)


@pytest.mark.anyio
@skip_if_no_grok
async def test_grok_api() -> None:
    model = get_model(
        "grok/grok-3-mini",
        config=GenerateConfig(
            stop_seqs=None,
            seed=None,
            temperature=0.0,
            top_p=1.0,
        ),
    )

    message = ChatMessageUser(content="This is a test string. What are you?")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1
