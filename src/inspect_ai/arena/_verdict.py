from dataclasses import dataclass
from typing import Any, Literal

Winner = Literal["a", "b", "tie"]


@dataclass
class JudgeVerdict:
    """Outcome of a single pairwise judgment.

    `winner` is positional (`"a"` or `"b"`) because the `Judge` sees only two
    anonymized responses. The `pairwise_scorer` is responsible for mapping
    positions back to contestant names when assembling the `Score`.
    """

    winner: Winner
    explanation: str | None = None
    metadata: dict[str, Any] | None = None
