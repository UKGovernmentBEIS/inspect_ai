from __future__ import annotations

from typing import TYPE_CHECKING, Sequence, TypeAlias

if TYPE_CHECKING:
    from inspect_scout import Scanner, Transcript

    from ._scorer import Scorer


Scorers: TypeAlias = (
    "Scorer"
    | "Scanner[Transcript]"
    | Sequence[
        "Scorer" | "Scanner[Transcript]" | tuple[str, "Scorer" | "Scanner[Transcript]"]
    ]
    | dict[str, "Scorer" | "Scanner[Transcript]"]
)
"""Set of scorers.

Scorers may optionally be named — either with a `dict` of `{name: scorer}`
or with `(name, scorer)` tuples within a sequence. Named forms are
supported by `score()` / `score_async()` (where the name becomes the
score name); `Task(scorer=...)` accepts only unnamed forms.
"""
