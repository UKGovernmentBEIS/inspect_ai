import pytest
from test_helpers.utils import (
    skip_if_github_action,
    skip_if_no_openai,
    skip_if_no_together,
)

from inspect_ai.model import ChatMessageUser, GenerateConfig, ModelOutput, get_model


async def generate_with_logprobs(model_name, **model_kwargs) -> ModelOutput:
    model = get_model(
        model_name,
        config=GenerateConfig(
            logprobs=True, top_logprobs=2, temperature=0.001, max_tokens=50
        ),
        **model_kwargs,
    )

    message = ChatMessageUser(content="Hello.")
    return await model.generate(input=[message])


@pytest.mark.asyncio
@skip_if_no_openai
async def test_openai_logprobs() -> None:
    response = await generate_with_logprobs("openai/gpt-3.5-turbo")
    assert response.choices[0].logprobs is not None
    assert response.choices[0].logprobs.content[0].top_logprobs is not None
    assert len(response.choices[0].logprobs.content[0].top_logprobs) == 2


@pytest.mark.asyncio
@skip_if_no_together
async def test_together_logprobs() -> None:
    response = await generate_with_logprobs("together/lmsys/vicuna-13b-v1.5")
    assert (
        response.choices[0].logprobs is not None
        and response.choices[0].logprobs.content[0].top_logprobs
        is None  # together only ever returns top-1, so top_logprobs should always be None
    )


@pytest.mark.asyncio
@skip_if_github_action
async def test_hf_logprobs() -> None:
    response = await generate_with_logprobs(
        "hf/EleutherAI/pythia-70m",
        chat_template="{% for message in messages %}{{ message.content }}{% endfor %}",
    )
    assert (
        response.choices[0].logprobs
        and response.choices[0].logprobs.content[0].top_logprobs is not None
    )
    assert len(response.choices[0].logprobs.content[0].top_logprobs) == 2
