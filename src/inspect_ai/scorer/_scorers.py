from __future__ import annotations

from typing import TYPE_CHECKING, Sequence, TypeAlias

if TYPE_CHECKING:
    from inspect_scout import Scanner, Transcript

    from ._scorer import Scorer


Scorers: TypeAlias = (
    "Scorer" | "Scanner[Transcript]" | Sequence["Scorer" | "Scanner[Transcript]"]
)
"""Set of scorers."""
