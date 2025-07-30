import pytest
from inspect_ai.model import get_model, GenerateConfig
from test_helpers.utils import (
    skip_if_github_action,
    skip_if_no_accelerate,
    skip_if_no_transformers,
)

@pytest.fixture
def model():
    #specify hidden_states=True in generation config
    gen_config = GenerateConfig(hidden_states=True)
    return get_model( model="hf/EleutherAI/pythia-70m", device="auto", config=gen_config)

@pytest.mark.asyncio
@skip_if_no_transformers
@skip_if_github_action
@skip_if_no_accelerate
async def test_hf_hidden_states(model)->None:

    outputs = await model.generate("hello activations!")

    output_text = outputs.choices[0].message.content
    assert len(output_text) > 0
    assert outputs.metadata is not None
    hidden_states = outputs.metadata["hidden_states"]
    num_tokens = len(hidden_states)
    assert num_tokens>0
    num_layers =len(hidden_states[0])
    assert num_layers==7
    #first_layer_first_token_shape = hidden_states[0][0].shape
