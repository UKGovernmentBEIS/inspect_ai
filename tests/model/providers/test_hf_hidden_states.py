import pytest
from test_helpers.utils import (
    skip_if_github_action,
    skip_if_no_accelerate,
    skip_if_no_transformers,
)

from inspect_ai.model import GenerateConfig, get_model


@pytest.fixture
def model():
    # specify hidden_states=True in model_args
    return get_model(
        model="hf/EleutherAI/pythia-70m",
        device="auto",
        config=GenerateConfig(max_tokens=2, seed=42, temperature=0.001),
        hidden_states=True,
    )


@pytest.mark.asyncio
@skip_if_no_transformers
@skip_if_github_action
@skip_if_no_accelerate
async def test_hf_hidden_states(model) -> None:
    outputs = await model.generate("hello activations!")

    output_text = outputs.choices[0].message.content
    assert len(output_text) > 0
    assert outputs.metadata is not None
    hidden_states = outputs.metadata["hidden_states"]
    num_tokens = len(hidden_states)
    assert num_tokens > 0
    num_layers = len(hidden_states[0])
    assert num_layers == 7
    # first_layer_first_token_shape = hidden_states[0][0].shape
