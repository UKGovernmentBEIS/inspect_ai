from typing import Callable, TypeVar

T = TypeVar("T")


def remove_last_match_and_after(
    lst: list[T], predicate: Callable[[T], bool]
) -> list[T]:
    last_match_index = max((i for i, x in enumerate(lst) if predicate(x)), default=-1)
    return lst[: last_match_index + 1]
