from typing import Callable, TypeVar

T = TypeVar("T")


def remove_last_match_and_after(
    lst: list[T], predicate: Callable[[T], bool]
) -> list[T]:
    """Return the prefix of `lst` through (and including) the last element matching `predicate`.

    Elements after the last match are dropped. If no element matches, returns
    an empty list.
    """
    last_match_index = max((i for i, x in enumerate(lst) if predicate(x)), default=-1)
    return lst[: last_match_index + 1]


def find_last_match(lst: list[T], predicate: Callable[[T], bool]) -> int | None:
    """Return the index of the last element of `lst` matching `predicate`, or `None`."""
    for i in range(len(lst) - 1, -1, -1):
        if predicate(lst[i]):
            return i
    return None
