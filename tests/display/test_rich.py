import pytest
import rich

import inspect_ai._display.core.rich as display_rich
from inspect_ai._display.core.rich import (
    _dumb_terminal_size_kwargs,
    rich_initialise,
    rich_restore_defaults,
)


def test_dumb_terminal_uses_columns_with_default_height(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("COLUMNS", "10000")
    monkeypatch.delenv("LINES", raising=False)

    assert _dumb_terminal_size_kwargs() == {"width": 10000, "height": 25}


def test_dumb_terminal_uses_lines_when_available(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("LINES", "50")

    assert _dumb_terminal_size_kwargs() == {"width": 200, "height": 50}


def test_terminal_size_override_requires_dumb_term(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("LINES", "50")

    assert _dumb_terminal_size_kwargs() == {}


@pytest.mark.parametrize("replace", [True, False])
def test_restore_keeps_console_changed_between_initialises(
    fresh_display: None, monkeypatch: pytest.MonkeyPatch, replace: bool
) -> None:
    # the textual display initialises the console for each eval, with no
    # restore between evals of the same display type
    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: True)
    rich_initialise("full", plain=False)
    if replace:
        rich.reconfigure(no_color=True)
    else:
        rich.get_console().no_color = True
    rich_initialise("full", plain=False)

    rich_restore_defaults()
    assert rich.get_console().no_color


def test_restore_after_repeated_initialise_removes_display_settings(
    fresh_display: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # outside VS Code, where rich_initialise turns off color
    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: False)
    rich_initialise("full", plain=False)
    rich_initialise("full", plain=False)

    rich_restore_defaults()
    assert not rich.get_console().no_color
