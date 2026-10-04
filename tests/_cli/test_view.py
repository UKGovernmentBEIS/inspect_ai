from typing import Any

import click
import pytest
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


@pytest.fixture
def captured_trust(monkeypatch: Any) -> dict[str, dict[str, Any]]:
    """Capture what `inspect view` hands to the viewer, bundler and embedder."""
    calls: dict[str, dict[str, Any]] = {}
    for name in ["view", "bundle_log_dir", "embed_log_dir"]:
        monkeypatch.setattr(
            view_cli,
            name,
            lambda _name=name, **kwargs: calls.__setitem__(_name, kwargs),
        )
    monkeypatch.setattr(view_cli, "process_common_options", lambda _options: None)
    monkeypatch.delenv("INSPECT_VIEW_TRUST_CONTENT", raising=False)
    return calls


@pytest.mark.parametrize(
    "args, env, expected",
    [
        ([], None, None),
        (["--no-trust-content"], None, False),
        (["--trust-content"], None, True),
        ([], "false", False),
        ([], "true", True),
        (["--trust-content"], "false", True),
    ],
)
@pytest.mark.parametrize("command", [[], ["start"]])
def test_view_trust_content(
    captured_trust: dict[str, dict[str, Any]],
    command: list[str],
    args: list[str],
    env: str | None,
    expected: bool | None,
) -> None:
    result = CliRunner().invoke(
        view_cli.view_command,
        command + args,
        env={"INSPECT_VIEW_TRUST_CONTENT": env} if env is not None else {},
    )
    assert result.exit_code == 0, result.output
    assert captured_trust["view"]["trust_content"] is expected


@pytest.mark.parametrize(
    "args, expected",
    [
        (["--no-trust-content", "start"], False),
        # The subcommand's own value wins over one given before it.
        (["--no-trust-content", "start", "--trust-content"], True),
    ],
)
def test_view_trust_content_before_start(
    captured_trust: dict[str, dict[str, Any]], args: list[str], expected: bool
) -> None:
    result = CliRunner().invoke(view_cli.view_command, args)
    assert result.exit_code == 0, result.output
    assert captured_trust["view"]["trust_content"] is expected


@pytest.mark.parametrize(
    "args",
    [
        ["--no-trust-content", "bundle", "--output-dir", "out"],
        ["--trust-content", "embed"],
    ],
)
def test_view_trust_content_rejected_for_bundle_and_embed(
    captured_trust: dict[str, dict[str, Any]], args: list[str]
) -> None:
    """Static viewers rely on each log's setting, so the option would be a no-op."""
    result = CliRunner().invoke(view_cli.view_command, args)
    assert result.exit_code == 2
    assert "does not apply" in result.output
    assert captured_trust == {}


@pytest.mark.parametrize(
    "args, called",
    [
        (["bundle", "--output-dir", "out"], "bundle_log_dir"),
        (["embed"], "embed_log_dir"),
    ],
)
def test_view_trust_content_environment_allowed_for_bundle_and_embed(
    captured_trust: dict[str, dict[str, Any]], args: list[str], called: str
) -> None:
    result = CliRunner().invoke(
        view_cli.view_command, args, env={"INSPECT_VIEW_TRUST_CONTENT": "false"}
    )
    assert result.exit_code == 0, result.output
    assert called in captured_trust


def test_view_trust_content_rejects_invalid_environment(
    captured_trust: dict[str, dict[str, Any]],
) -> None:
    result = CliRunner().invoke(
        view_cli.view_command, [], env={"INSPECT_VIEW_TRUST_CONTENT": "maybe"}
    )
    assert result.exit_code == 2
    assert "view" not in captured_trust
