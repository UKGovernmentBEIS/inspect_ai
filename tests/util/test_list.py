from inspect_ai._util.list import find_last_match, remove_last_match_and_after

# remove_last_match_and_after keeps everything up to and INCLUDING the last
# matching element, and drops anything strictly after it. The current name
# implies the opposite; these tests lock in the actual behaviour.
# See #4017


def test_remove_last_match_keeps_through_last_match_at_end() -> None:
    assert remove_last_match_and_after([1, 2, "a"], lambda x: isinstance(x, str)) == [
        1,
        2,
        "a",
    ]


def test_remove_last_match_drops_trailing_non_matches_after_last_match() -> None:
    # "a" and "b" both match; "b" is the last match. Trailing ints after
    # "b" are dropped, but the int between "a" and "b" is kept.
    assert remove_last_match_and_after(
        ["a", 1, "b", 2, 3], lambda x: isinstance(x, str)
    ) == ["a", 1, "b"]


def test_remove_last_match_only_match_at_index_zero() -> None:
    assert remove_last_match_and_after(["a", 1, 2], lambda x: isinstance(x, str)) == [
        "a"
    ]


def test_remove_last_match_no_match_returns_empty() -> None:
    assert remove_last_match_and_after([1, 2, 3], lambda x: isinstance(x, str)) == []


def test_remove_last_match_empty_list_returns_empty() -> None:
    assert remove_last_match_and_after([], lambda x: isinstance(x, str)) == []


def test_remove_last_match_single_element_match() -> None:
    assert remove_last_match_and_after(["a"], lambda x: isinstance(x, str)) == ["a"]


def test_remove_last_match_single_element_no_match() -> None:
    assert remove_last_match_and_after([1], lambda x: isinstance(x, str)) == []


def test_find_last_match_returns_index_of_last_match() -> None:
    assert find_last_match(["a", 1, "b", 2], lambda x: isinstance(x, str)) == 2


def test_find_last_match_single_match() -> None:
    assert find_last_match([1, "a", 2], lambda x: isinstance(x, str)) == 1


def test_find_last_match_match_at_index_zero() -> None:
    assert find_last_match(["a", 1, 2], lambda x: isinstance(x, str)) == 0


def test_find_last_match_no_match_returns_none() -> None:
    assert find_last_match([1, 2, 3], lambda x: isinstance(x, str)) is None


def test_find_last_match_empty_list_returns_none() -> None:
    assert find_last_match([], lambda x: isinstance(x, str)) is None
