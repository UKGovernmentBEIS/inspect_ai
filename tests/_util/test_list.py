from inspect_ai._util.list import find_last_match, remove_last_match_and_after


def test_remove_last_match_and_after_no_match():
    items = [1, 2, 3]
    result = remove_last_match_and_after(items, lambda x: x > 5)
    assert result == [1, 2, 3]


def test_remove_last_match_and_after_with_match():
    items = [1, 2, 3, 4, 5]
    result = remove_last_match_and_after(items, lambda x: x == 3)
    assert result == [1, 2, 3]


def test_remove_last_match_and_after_multiple_matches():
    items = ["a", "b", "c", "b", "d"]
    result = remove_last_match_and_after(items, lambda x: x == "b")
    assert result == ["a", "b", "c", "b"]


def test_find_last_match():
    items = [10, 20, 30, 20, 40]
    assert find_last_match(items, lambda x: x == 20) == 3
    assert find_last_match(items, lambda x: x == 99) is None
