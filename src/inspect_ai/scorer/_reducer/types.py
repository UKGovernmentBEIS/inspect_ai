from typing import Any, Protocol, runtime_checkable

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


ScoreReducers = (
    str | ScoreReducer | list[str] | list[ScoreReducer] | list[dict[str, Any]]
)
r"""One or more score reducers.

A list of dicts with `name` and `args` keys (as recorded in a log's
`eval.config.runtime_reducer_args`) rebuilds reducers with their full
argument set; a list of strings uses the `<name>_<k>` shorthand with all
other arguments at their defaults.
"""
