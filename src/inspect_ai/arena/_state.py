from pydantic import Field

from inspect_ai.util import StoreModel


class ArenaState(StoreModel):
    """Per-sample state for arena evaluation.

    Populated by `arena_solver` (one entry per contestant) and consumed by
    `pairwise_scorer` to generate the set of pairs for judging.
    """

    responses: dict[str, str] = Field(default_factory=dict)
    """Map of contestant name to generated response."""

    failed: list[str] = Field(default_factory=list)
    """Contestants that raised during generation for this sample."""
