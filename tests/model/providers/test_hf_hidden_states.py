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


def test_hidden_states_to_jsonable_survives_log_serialization():
    """hidden_states tensors must be converted to a JSON-able form by the provider.

    Raw tensors are dropped to ``None`` when the model output metadata is written to
    the eval log (regression for #2860); the nested-list form survives intact.
    """
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")  # hf provider module imports transformers
    from pydantic_core import to_jsonable_python

    from inspect_ai.model._providers.hf import _hidden_states_to_jsonable

    # shape mirrors output_hidden_states: tuple[step] of tuple[layer] of Tensor
    hidden_states = ((torch.zeros(1, 2, 3), torch.ones(1, 2, 3)),)

    # raw tensors are destroyed by the log's jsonable fallback ...
    raw = to_jsonable_python({"hidden_states": hidden_states}, fallback=lambda _x: None)
    assert raw["hidden_states"] == [[None, None]]

    # ... the converted form round-trips intact.
    converted = _hidden_states_to_jsonable(hidden_states)
    assert converted == [[torch.zeros(1, 2, 3).tolist(), torch.ones(1, 2, 3).tolist()]]
    serialized = to_jsonable_python(
        {"hidden_states": converted}, fallback=lambda _x: None
    )
    assert serialized["hidden_states"] == converted

    assert _hidden_states_to_jsonable(None) is None
