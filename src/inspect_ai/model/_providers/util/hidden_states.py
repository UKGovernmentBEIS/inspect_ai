from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from torch import Tensor  # type: ignore


def hidden_states_to_jsonable(
    hidden_states: tuple[tuple[Tensor, ...], ...] | None,
    sample_index: int,
) -> list[list[Any]] | None:
    """Materialize one sample's generation hidden states as JSON-serializable lists.

    ``output_hidden_states`` yields tensors, which are not JSON-serializable and are
    dropped to ``None`` when model output metadata is written to the eval log. Convert
    them to nested lists (preserving the ``[step][layer]`` structure) so the requested
    activations survive serialization instead of being lost.

    Layer tensors carry a leading batch dimension, so ``sample_index`` selects the
    sample to record: each layer tensor is indexed on that dimension before
    conversion, so a sample records only its own activations rather than the entire
    batch's. Callers that generate one sample at a time pass ``0``.
    """
    if hidden_states is None:
        return None
    return [[layer[sample_index].tolist() for layer in step] for step in hidden_states]
