import pytest
from test_helpers.utils import (
    skip_if_github_action,
    skip_if_no_accelerate,
    skip_if_no_transformers,
)

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)


@pytest.fixture
def model():
    return get_model(
        "hf/EleutherAI/pythia-70m",
        config=GenerateConfig(
            max_tokens=1,
            seed=42,
            temperature=0.01,
        ),
        # this allows us to run base models with the chat message scaffolding:
        chat_template="{% for message in messages %}{{ message.content }}{% endfor %}",
        tokenizer_call_args={"truncation": True, "max_length": 2},
    )


@pytest.fixture
def model_with_stop_seqs():
    DEFAULT_CHAT_TEMPLATE = (
        "{% for message in messages %}{{ message.content }}{% endfor %}"
    )
    model = get_model(
        "hf/EleutherAI/pythia-70m",
        config=GenerateConfig(
            max_tokens=5,
            seed=42,
            temperature=0.001,
            stop_seqs=["w3"],
        ),
        # this allows us to run base models with the chat message scaffolding:
        chat_template=DEFAULT_CHAT_TEMPLATE,
        tokenizer_call_args={"truncation": True, "max_length": 10},
    )
    # Chat template is not propagated by default from get_model to the model's tokenizer.
    model.api.tokenizer.chat_template = DEFAULT_CHAT_TEMPLATE
    return model


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_transformers
@skip_if_no_accelerate
async def test_hf_api(model) -> None:
    message = ChatMessageUser(content="Lorem ipsum dolor")
    response = await model.generate(input=[message])
    assert response.usage.input_tokens == 2
    assert len(response.completion) >= 1


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_transformers
@skip_if_no_accelerate
async def test_hf_api_with_stop_seqs(model_with_stop_seqs) -> None:
    # This generates "https://www.w3.org" with pythia-70m greedy decoding
    message = ChatMessageUser(content="https://")
    response = await model_with_stop_seqs.generate(input=[message])
    assert response.completion == "www.w3"


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_transformers
async def test_hf_api_fails(model) -> None:
    temp_before = model.config.temperature
    try:
        model.config.temperature = 0.0

        message = ChatMessageUser(content="Lorem ipsum dolor")
        with pytest.raises(Exception):
            await model.generate(input=[message])
    finally:
        model.config.temperature = temp_before
