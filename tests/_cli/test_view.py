from typing import Any

import click
from click.testing import CliRunner

import inspect_ai._cli.view as view_cli
from inspect_ai._view.network import ViewerNetworkPolicyError


def test_view_network_options_are_forwarded(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_view(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(view_cli, "view", fake_view)
    monkeypatch.setattr(view_cli, "process_common_options", lambda _options: None)

    result = CliRunner().invoke(
        view_cli.view_command,
        [
            "--trusted-origin",
            "http://my-inspect:7575",
            "--trusted-origin",
            "https://inspect.example",
            "--trusted-host",
            "health.internal:7575",
            "--unsafe-allow-unauthenticated",
        ],
        standalone_mode=False,
    )

    assert result.exit_code == 0, result.output
    assert captured["trusted_origins"] == (
        "http://my-inspect:7575",
        "https://inspect.example",
    )
    assert captured["trusted_hosts"] == ("health.internal:7575",)
    assert captured["unsafe_allow_unauthenticated"] is True


def test_view_authorization_environment_is_forwarded(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_view(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(view_cli, "view", fake_view)
    monkeypatch.setattr(view_cli, "process_common_options", lambda _options: None)

    result = CliRunner().invoke(
        view_cli.view_command,
        [],
        env={"INSPECT_VIEW_AUTHORIZATION_TOKEN": "secret"},
        standalone_mode=False,
    )

    assert result.exit_code == 0, result.output
    assert captured["authorization"] == "secret"
    assert captured["log_level"] == "HTTP"


def test_view_policy_errors_are_usage_errors(monkeypatch: Any) -> None:
    def fake_view(**_kwargs: Any) -> None:
        raise ViewerNetworkPolicyError("unsafe viewer configuration")

    monkeypatch.setattr(view_cli, "view", fake_view)
    monkeypatch.setattr(view_cli, "process_common_options", lambda _options: None)

    result = CliRunner().invoke(
        view_cli.view_command,
        [],
        standalone_mode=False,
    )

    assert isinstance(result.exception, click.UsageError)
    assert "unsafe viewer configuration" in str(result.exception)
