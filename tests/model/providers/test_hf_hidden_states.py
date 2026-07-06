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


@skip_if_no_transformers
def test_hidden_states_to_jsonable_slices_batch_and_survives_log() -> None:
    """The provider must record each sample's own activations, as JSON-able lists.

    Two bugs this guards against: raw tensors are dropped to ``None`` when written to
    the eval log (#2860), and an un-sliced batch tensor would leak every sample's
    activations into every sample's log. ``sample_index`` selects one sample from the
    batch dimension and materializes it to lists that survive the canonical log
    serializer intact.
    """
    import torch

    from inspect_ai._util.json import jsonable_python
    from inspect_ai.model._providers.util.hidden_states import (
        hidden_states_to_jsonable,
    )

    # one step, two layers, each Tensor(batch=2, seq=1, hidden=2) with distinct
    # per-sample values so a batch-slicing error would show up in the result
    hidden_states = (
        (
            torch.tensor([[[0.0, 1.0]], [[2.0, 3.0]]]),
            torch.tensor([[[4.0, 5.0]], [[6.0, 7.0]]]),
        ),
    )

    # each sample gets only its own row of the batch (no cross-sample leakage)
    assert hidden_states_to_jsonable(hidden_states, sample_index=0) == [
        [[[0.0, 1.0]], [[4.0, 5.0]]]
    ]
    assert hidden_states_to_jsonable(hidden_states, sample_index=1) == [
        [[[2.0, 3.0]], [[6.0, 7.0]]]
    ]

    # raw tensors would be lost in the log; the converted form survives it intact
    assert jsonable_python({"hidden_states": hidden_states})["hidden_states"] == [
        [None, None]
    ]
    converted = hidden_states_to_jsonable(hidden_states, sample_index=0)
    assert jsonable_python({"hidden_states": converted})["hidden_states"] == converted

    assert hidden_states_to_jsonable(None, sample_index=0) is None
