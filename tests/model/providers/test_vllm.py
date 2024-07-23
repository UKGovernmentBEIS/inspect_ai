import pytest
from test_helpers.utils import skip_if_github_action, skip_if_no_vllm

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)


@pytest.mark.asyncio
@skip_if_github_action
@skip_if_no_vllm
async def test_vllm_api() -> None:
    model = get_model(
        "vllm/EleutherAI/pythia-70m",
        config=GenerateConfig(
            max_tokens=1,
            seed=42,
            temperature=0.7,
            top_p=0.9,
            top_k=None,
            frequency_penalty=0.0,
            presence_penalty=0.0,
        ),
        device=0,
        # this allows us to run base models with the chat message scaffolding:
        chat_template="{% for message in messages %}{{ message.content }}{% endfor %}",
    )
    message = ChatMessageUser(content="Lorem ipsum dolor")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1
