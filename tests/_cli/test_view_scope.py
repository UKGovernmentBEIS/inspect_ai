from __future__ import annotations

from typing import Any

from click.testing import CliRunner

import inspect_ai._cli.view as view_cli


def test_scoped_authorization_option_is_forwarded(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}

    def fake_view(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(view_cli, "view", fake_view)
    monkeypatch.setattr(view_cli, "process_common_options", lambda _options: None)

    result = CliRunner().invoke(
        view_cli.view_command,
        ["--scoped-authorization"],
        env={"INSPECT_VIEW_AUTHORIZATION_TOKEN": "secret"},
        standalone_mode=False,
    )

    assert result.exit_code == 0, result.output
    assert captured["authorization"] == "secret"
    assert captured["scoped_authorization"] is True
