from typing import Protocol, runtime_checkable

from .._metric import Score


@runtime_checkable
class ScoreReducer(Protocol):
    def __call__(self, scores: list[Score]) -> Score:
        """Reduce a set of scores to a single score.

        Args:
          scores: List of scores.
        """
        ...

    @property
    def __name__(self) -> str: ...


ScoreReducers = str | ScoreReducer | list[str] | list[ScoreReducer]
r"""One or more score reducers."""
