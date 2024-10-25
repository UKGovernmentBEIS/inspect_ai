import pytest
from test_helpers.utils import (
    skip_if_github_action,
    skip_if_no_grok,
    skip_if_no_openai,
    skip_if_no_together,
    skip_if_no_vllm,
)

from inspect_ai.model import GenerateConfig, get_model


async def generate(model_name):
    model = get_model(model_name)
    return await model.generate(input="Hello.", config=GenerateConfig(num_choices=3))


async def check_num_choices(model_name):
    model = get_model(model_name)
    response = await model.generate(
        input="Hello.", config=GenerateConfig(num_choices=3)
    )
    assert len(response.choices) == 3


@pytest.mark.asyncio
@skip_if_no_openai
async def test_openai_num_choices() -> None:
    await check_num_choices("openai/gpt-3.5-turbo")


@skip_if_no_grok
async def test_grok_num_choices() -> None:
    await check_num_choices("grok/grok-beta")


@pytest.mark.asyncio
@skip_if_no_together
async def test_together_num_choices() -> None:
    await check_num_choices("together/google/gemma-2b-it")


@pytest.mark.asyncio
@skip_if_github_action
@skip_if_no_vllm
async def test_vllm_num_choices() -> None:
    await check_num_choices("vllm/EleutherAI/pythia-70m")


# @pytest.mark.asyncio
# @skip_if_no_azureai
# async def test_azureai_num_choices() -> None:
#     await check_num_choices(None)
