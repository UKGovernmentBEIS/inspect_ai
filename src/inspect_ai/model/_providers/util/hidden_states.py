from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from torch import Tensor


def hidden_states_to_jsonable(
    hidden_states: tuple[tuple[Tensor]] | None,
    sample_index: int | None = None,
) -> list[list[Any]] | None:
    """Materialize generation hidden states as JSON-serializable nested lists.

    ``output_hidden_states`` yields tensors, which are not JSON-serializable and are
    dropped to ``None`` when model output metadata is written to the eval log. Convert
    them to nested lists (preserving the ``[step][layer]`` structure) so the requested
    activations survive serialization instead of being lost.

    When the layer tensors carry a leading batch dimension (as in batched HF
    generation), pass ``sample_index`` to select a single sample: each layer tensor is
    indexed on that dimension before conversion, so a sample records only its own
    activations rather than the entire batch's.
    """
    if hidden_states is None:
        return None
    if sample_index is None:
        return [[layer.tolist() for layer in step] for step in hidden_states]
    return [[layer[sample_index].tolist() for layer in step] for step in hidden_states]
