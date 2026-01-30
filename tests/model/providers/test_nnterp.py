import pytest
from test_helpers.utils import skip_if_no_nnterp

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)


@pytest.fixture
def model():
    return get_model(
        "nnterp/openai-community/gpt2",
        config=GenerateConfig(
            max_tokens=5,
            temperature=0.01,
        ),
    )


@pytest.fixture
def model_with_logprobs():
    return get_model(
        "nnterp/openai-community/gpt2",
        config=GenerateConfig(
            max_tokens=5,
            temperature=0.01,
            logprobs=True,
            top_logprobs=3,
        ),
    )


@pytest.mark.anyio
@skip_if_no_nnterp
async def test_nnterp_api(model) -> None:
    """Test basic NNterp provider functionality."""
    message = ChatMessageUser(content="Hello world")
    response = await model.generate(input=[message])
    assert response.usage is not None
    assert response.usage.input_tokens > 0
    assert len(response.completion) >= 1


@pytest.mark.anyio
@skip_if_no_nnterp
async def test_nnterp_api_with_logprobs(model_with_logprobs) -> None:
    """Test NNterp provider with logprobs enabled."""
    message = ChatMessageUser(content="Hello world")
    response = await model_with_logprobs.generate(input=[message])

    # Verify logprobs are returned
    assert response.choices[0].logprobs is not None
    assert response.choices[0].logprobs.content is not None
    assert len(response.choices[0].logprobs.content) > 0

    # Verify logprob structure
    first_logprob = response.choices[0].logprobs.content[0]
    assert first_logprob.token is not None
    assert first_logprob.logprob is not None
    assert first_logprob.top_logprobs is not None
    assert len(first_logprob.top_logprobs) == 3  # We requested top 3


@pytest.mark.anyio
@skip_if_no_nnterp
async def test_nnterp_multiple_messages() -> None:
    """Test NNterp provider with multiple chat messages."""
    from inspect_ai.model import ChatMessageSystem

    model = get_model(
        "nnterp/openai-community/gpt2",
        config=GenerateConfig(max_tokens=5, temperature=0.01),
    )

    messages: list[ChatMessageSystem | ChatMessageUser] = [
        ChatMessageSystem(content="You are a helpful assistant."),
        ChatMessageUser(content="Hello"),
    ]

    response = await model.generate(input=messages)
    assert len(response.completion) >= 1
    assert response.choices[0].message.content is not None


@pytest.mark.anyio
@skip_if_no_nnterp
async def test_nnterp_api_with_hidden_states() -> None:
    """Test NNterp provider with hidden states extraction enabled."""
    model = get_model(
        "nnterp/openai-community/gpt2",
        config=GenerateConfig(max_tokens=3, temperature=0.01),
        hidden_states=True,
    )

    message = ChatMessageUser(content="Hello")
    response = await model.generate(input=[message])

    # Verify hidden states are returned in metadata
    assert response.metadata is not None
    assert "hidden_states" in response.metadata
    hidden_states = response.metadata["hidden_states"]

    # hidden_states should be a tuple of (num_tokens, num_layers, ...)
    assert len(hidden_states) > 0  # At least one token generated
    # Each token should have hidden states for each layer
    first_token_hidden_states = hidden_states[0]
    assert len(first_token_hidden_states) > 0  # Should have multiple layers
