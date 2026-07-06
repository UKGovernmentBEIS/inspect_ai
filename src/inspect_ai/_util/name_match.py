from collections.abc import Callable, Sequence
from typing import TypeVar

T = TypeVar("T")


def match_name_prefix(
    items: Sequence[T], query: str, name: Callable[[T], str]
) -> list[T]:
    """Match items by name at the name's start or after a ``/``, exact-wins.

    The shared selector rule for user-supplied name queries (CLI task names,
    ``ctl limits --model``): ``query`` matches an item whose name starts with
    it or whose final path segment starts with it (so ``gpqa`` matches
    ``inspect_evals/gpqa_diamond``, and ``gpt-4`` matches ``openai/gpt-4``).
    An exact full-name or leaf match narrows the result to just the exact
    matches, so ``gpt-4`` resolves cleanly to ``openai/gpt-4`` even when
    ``openai/gpt-4-turbo`` is also present.

    Args:
        items: Candidates to match.
        query: The user-supplied name (or prefix) to match against.
        name: Projects an item to the name it should be matched by.
    """

    def leaf(n: str) -> str:
        return n.rsplit("/", 1)[-1]

    prefix = [
        item
        for item in items
        if name(item).startswith(query) or leaf(name(item)).startswith(query)
    ]
    exact = [
        item for item in prefix if name(item) == query or leaf(name(item)) == query
    ]
    return exact or prefix
