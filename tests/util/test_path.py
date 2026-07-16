"""Tests for inspect_ai._util.path.cwd_relative_path.

Covers the str -> str and None -> None overload contracts, including
the regression case for issue 4451 where empty-string input was
incorrectly routed to the None branch.
"""

import os
from pathlib import PurePath

from inspect_ai._util.path import cwd_relative_path


def test_cwd_relative_path_none_returns_none():
    """None input returns None (per overload)."""
    assert cwd_relative_path(None) is None


def test_cwd_relative_path_empty_string_returns_empty_string_issue_4451():
    """Empty string input returns empty string (per str overload).

    Regression test for issue 4451: previously the `if file:` truthiness
    check routed empty string to the None branch, returning None and
    violating the `str -> str` overload contract.
    """
    assert cwd_relative_path("") == ""


def test_cwd_relative_path_absolute_in_cwd_returns_relative_posix():
    """Absolute path inside cwd returns POSIX-formatted relative path."""
    cwd = os.getcwd()
    abs_path = os.path.join(cwd, "foo", "bar")
    expected = PurePath(abs_path).relative_to(PurePath(cwd)).as_posix()
    assert cwd_relative_path(abs_path) == expected


def test_cwd_relative_path_relative_input_returns_input():
    """Already-relative path returns input unchanged."""
    assert cwd_relative_path("foo/bar") == "foo/bar"


def test_cwd_relative_path_none_with_walk_up_returns_none():
    """None input still returns None when walk_up=True."""
    assert cwd_relative_path(None, walk_up=True) is None


def test_cwd_relative_path_empty_with_walk_up_returns_empty_issue_4451():
    """Empty string still returns empty string when walk_up=True."""
    assert cwd_relative_path("", walk_up=True) == ""
