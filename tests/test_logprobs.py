import pytest
from utils import skip_if_no_openai, skip_if_no_together

from inspect_ai.model import ChatMessageUser, GenerateConfig, ModelOutput, get_model


async def generate_with_logprobs(model_name) -> ModelOutput:
    model = get_model(
        model_name,
        config=GenerateConfig(logprobs=True, top_logprobs=2),
    )

    message = ChatMessageUser(content="Hello.")
    return await model.generate(input=[message])


@pytest.mark.asyncio
@skip_if_no_openai
async def test_openai_logprobs() -> None:
    response = await generate_with_logprobs("openai/gpt-3.5-turbo")
    assert response.choices[0].logprobs is not None
    assert len(response.choices[0].logprobs["content"][0]["top_logprobs"]) == 2


@pytest.mark.asyncio
@skip_if_no_together
async def test_together_logprobs() -> None:
    response = await generate_with_logprobs("together/lmsys/vicuna-13b-v1.5")
    assert (
        response.choices[0].logprobs
        and response.choices[0].logprobs["token_ids"] is not None
    )
