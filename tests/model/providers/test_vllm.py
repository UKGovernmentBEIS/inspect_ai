import pytest
from test_helpers.utils import skip_if_github_action

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)


@pytest.fixture
def model():
    return get_model(
        "vllm/EleutherAI/pythia-70m",
        config=GenerateConfig(
            max_tokens=1,
            seed=42,
            temperature=0.7,  # for some reason vllm doesn't generate anything for 0 < temperature < 0.02
            top_p=0.9,
            top_k=None,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            best_of=None,
            num_choices=2,
            top_logprobs=3,
        ),
        device=7,
        # this allows us to run base models with the chat message scaffolding:
        chat_template="{% for message in messages %}{{ message.content }}{% endfor %}",
    )


@pytest.mark.asyncio
@skip_if_github_action
async def test_hf_api(model) -> None:
    message = ChatMessageUser(content="Lorem ipsum dolor")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1
    assert len(response.choices) == 2
    assert len(response.choices[0].logprobs.content) == 1
    assert len(response.choices[0].logprobs.content[0].top_logprobs) == 3


@pytest.mark.asyncio
@skip_if_github_action
async def test_hf_api_fails(model) -> None:
    temp_before = model.config.temperature
    try:
        model.config.temperature = 0.0

        message = ChatMessageUser(content="Lorem ipsum dolor")
        with pytest.raises(Exception):
            await model.generate(input=[message])
    finally:
        model.config.temperature = temp_before
