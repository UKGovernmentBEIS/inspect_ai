import pytest
from test_helpers.utils import skip_if_github_action
from transformers import PreTrainedModel  # type: ignore

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)


@pytest.fixture
def model() -> PreTrainedModel:
    return get_model(
        "hf/EleutherAI/pythia-70m",
        config=GenerateConfig(
            max_tokens=1,
            seed=42,
            temperature=0.01,
        ),
        # this allows us to run base models with the chat message scaffolding:
        chat_template="{% for message in messages %}{{ message.content }}{% endfor %}",
    )


@pytest.mark.asyncio
@skip_if_github_action
async def test_hf_api(model: PreTrainedModel) -> None:
    message = ChatMessageUser(content="Lorem ipsum dolor")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1


@pytest.mark.asyncio
@skip_if_github_action
async def test_hf_api_fails(model: PreTrainedModel) -> None:
    temp_before = model.config.temperature
    try:
        model.config.temperature = 0.0

        message = ChatMessageUser(content="Lorem ipsum dolor")
        with pytest.raises(Exception):
            await model.generate(input=[message])
    finally:
        model.config.temperature = temp_before
