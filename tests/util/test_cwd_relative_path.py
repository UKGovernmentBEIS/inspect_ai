"""Tests for cwd_relative_path() and pretty_path()."""

import os

from inspect_ai._util.path import chdir, cwd_relative_path, pretty_path


def test_none_returns_none() -> None:
    assert cwd_relative_path(None) is None
    assert cwd_relative_path(None, walk_up=True) is None


def test_empty_string_returns_str_not_none() -> None:
    # The `str -> str` overload promises a str for any str input, including "".
    assert cwd_relative_path("") == ""
    assert cwd_relative_path("", walk_up=True) == ""


def test_path_under_cwd_is_made_relative(tmp_path) -> None:
    with chdir(str(tmp_path)):
        absolute = os.path.join(str(tmp_path), "sub", "task.py")
        assert cwd_relative_path(absolute) == "sub/task.py"


def test_path_outside_cwd_returned_unchanged_without_walk_up(tmp_path) -> None:
    sibling = tmp_path.parent / "elsewhere" / "task.py"
    with chdir(str(tmp_path)):
        assert cwd_relative_path(str(sibling)) == str(sibling)


def test_pretty_path_empty_string_returns_str() -> None:
    result = pretty_path("")
    assert isinstance(result, str)
