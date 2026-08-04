from typing import Callable, TypeVar

T = TypeVar("T")


def remove_last_match_and_after(
    lst: list[T], predicate: Callable[[T], bool]
) -> list[T]:
    last_match_index = find_last_match(lst, predicate)
    if last_match_index is not None:
        return lst[: last_match_index + 1]
    return lst


def find_last_match(lst: list[T], predicate: Callable[[T], bool]) -> int | None:
    for i in range(len(lst) - 1, -1, -1):
        if predicate(lst[i]):
            return i
    return None
