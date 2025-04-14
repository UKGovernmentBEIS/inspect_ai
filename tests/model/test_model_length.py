from pathlib import Path
from typing import Any

import pytest
from test_helpers.utils import skip_if_no_openai

from inspect_ai.model import get_model

GATSBY = Path(__file__).parent / "gatsby.txt"
GATSBY_TOKENS = 69062

# model context window sizes
# from: https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json
GPT_4O = "openai/gpt-4o"

MODELS = {GPT_4O: 128000}


async def check_model_length(model: str, **model_args: Any) -> None:
    # context window for model
    model_tokens = MODELS.get(model, None)
    assert model_tokens

    # create message that exceeds context window
    with open(GATSBY, "r") as f:
        gatsby = f.read()
        message = gatsby
    for _ in range(0, (model_tokens // GATSBY_TOKENS) + 1):
        message = f"{message}\n\n{gatsby}"

    # run inference
    output = await get_model(model, **model_args).generate(
        f"Please summarize this:\n\n{message}"
    )
    assert output.stop_reason == "model_length"


@pytest.mark.asyncio
@pytest.mark.slow
@skip_if_no_openai
async def test_model_length_openai():
    await check_model_length(GPT_4O)


@pytest.mark.asyncio
@pytest.mark.slow
@skip_if_no_openai
async def test_model_length_openai_responses():
    await check_model_length(GPT_4O, responses_api=True)
