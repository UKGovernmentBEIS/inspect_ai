from __future__ import annotations

from typing import TYPE_CHECKING, Mapping, Sequence, TypeAlias

if TYPE_CHECKING:
    from inspect_scout import Scanner, Transcript

    from ._scorer import Scorer


Scorers: TypeAlias = (
    "Scorer" | "Scanner[Transcript]" | Sequence["Scorer" | "Scanner[Transcript]"]
)
"""Set of scorers."""

NamedScorers: TypeAlias = Scorers | Mapping[str, "Scorer" | "Scanner[Transcript]"]
"""Either a set of scorers or a dict of scorers keyed by score name."""
