from inspect_ai._cli.view import resolve_view_log_dirs


def test_resolve_view_log_dirs_repeated_flag() -> None:
    assert resolve_view_log_dirs(("~/logs", "s3://b/logs"), env=None) == [
        "~/logs",
        "s3://b/logs",
    ]


def test_resolve_view_log_dirs_comma_env_when_no_flag() -> None:
    assert resolve_view_log_dirs((), env="~/logs,s3://b/logs") == [
        "~/logs",
        "s3://b/logs",
    ]


def test_resolve_view_log_dirs_flag_overrides_env() -> None:
    assert resolve_view_log_dirs(("~/only",), env="~/ignored") == ["~/only"]


def test_resolve_view_log_dirs_default_when_empty() -> None:
    assert resolve_view_log_dirs((), env=None) == ["./logs"]
