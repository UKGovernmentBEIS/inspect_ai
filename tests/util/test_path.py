from inspect_ai._util.path import cwd_relative_path


def test_cwd_relative_path_empty_string() -> None:
    assert cwd_relative_path("") == ""
    assert cwd_relative_path("", walk_up=True) == ""


def test_cwd_relative_path_none() -> None:
    assert cwd_relative_path(None) is None
