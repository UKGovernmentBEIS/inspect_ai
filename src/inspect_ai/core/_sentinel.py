from typing import Annotated, Literal, TypeAlias

from pydantic import Field, FiniteFloat

SentinelAction: TypeAlias = Literal[
    "continue", "modify", "reject", "terminate", "escalate"
]
"""What a sentinel protocol can decide about the step it examined."""

SentinelSuspicion: TypeAlias = (
    FiniteFloat | Annotated[dict[str, FiniteFloat], Field(min_length=1)]
)
"""How suspicious a step is: one finite score, or a non-empty dict of scores for several dimensions."""
