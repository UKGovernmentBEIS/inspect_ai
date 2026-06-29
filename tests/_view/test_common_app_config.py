import os

from inspect_ai._view.common import LogDirInfo, get_app_config


def test_get_app_config_includes_resolved_and_aliased_log_dirs() -> None:
    home = os.path.expanduser("~")
    config = get_app_config(log_dirs=[f"{home}/logs", "s3://bucket/logs"])
    assert config.log_dirs == [
        LogDirInfo(log_dir=f"{home}/logs", aliased="~/logs"),
        LogDirInfo(log_dir="s3://bucket/logs", aliased="s3://bucket/logs"),
    ]


def test_get_app_config_defaults_to_empty_log_dirs() -> None:
    config = get_app_config()
    assert config.log_dirs == []
