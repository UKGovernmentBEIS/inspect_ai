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
    rich.get_console().no_color = False
    rich_initialise("full", plain=False)
    rich_initialise("full", plain=False)

    rich_restore_defaults()
    assert not rich.get_console().no_color


@pytest.mark.parametrize("changed", [True, False])
def test_textual_input_screen_shows_prompt_inside_capture(
    fresh_display: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    changed: bool,
) -> None:
    from contextlib import nullcontext
    from types import SimpleNamespace
    from typing import Any, cast

    from inspect_ai._display.textual.app import TextualTaskScreen

    # after a display type change a caller's capture is kept (e.g. a change to
    # "full" inside `console.capture()`); without one it behaves as before
    monkeypatch.setattr(display_rich, "_reconfigure_in_place", changed)
    app = cast(Any, SimpleNamespace(suspend_app=nullcontext))
    console = rich.get_console()
    with console.capture() as capture:
        console.print("before the screen")
        screen = TextualTaskScreen[None](app)
        with screen.input_screen(record_event=False) as screen_console:
            screen_console.print("prompt")
            assert ("prompt" in capsys.readouterr().out) == changed
        console.print("after the screen")

    assert "before the screen" in capture.get()
    assert "after the screen" in capture.get()
    assert ("prompt" in capture.get()) != changed


@pytest.mark.parametrize("record_event", [True, False])
@pytest.mark.parametrize("changed", [True, False])
def test_textual_input_screen_keeps_recording(
    fresh_display: None,
    monkeypatch: pytest.MonkeyPatch,
    changed: bool,
    record_event: bool,
) -> None:
    from contextlib import nullcontext
    from types import SimpleNamespace
    from typing import Any, cast

    from inspect_ai._display.textual.app import TextualTaskScreen

    # after a display type change a caller's recording is kept; without one
    # the input screen ends it, as before
    monkeypatch.setattr(display_rich, "_reconfigure_in_place", changed)
    app = cast(Any, SimpleNamespace(suspend_app=nullcontext))
    console = rich.get_console()
    console.record = True
    console.print("earlier")
    screen = TextualTaskScreen[None](app)
    with screen.input_screen(record_event=record_event) as screen_console:
        screen_console.print("prompt")

    assert console.record == changed
    if changed:
        recorded = console.export_text()
        assert "earlier" in recorded and "prompt" in recorded


class _TerminalOutput:
    """A stand-in stdout that reports a terminal."""

    def __init__(self) -> None:
        import io

        self.buffer = io.StringIO()

    def write(self, text: str) -> int:
        return self.buffer.write(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return True


@pytest.fixture
def terminal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(display_rich, "is_running_in_vscode", lambda: False)
    monkeypatch.setenv("TERM", "xterm-256color")
    for name in ["TTY_COMPATIBLE", "TTY_INTERACTIVE", "FORCE_COLOR", "NO_COLOR"]:
        monkeypatch.delenv(name, raising=False)


def test_restore_detects_settings_for_redirected_output(
    fresh_display: None, terminal_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import sys

    # a plain display set up on a terminal, then stdout redirected
    monkeypatch.setattr(sys, "stdout", _TerminalOutput())
    rich.reconfigure()
    rich_initialise("plain", plain=True)
    monkeypatch.setattr(sys, "stdout", io.StringIO())

    display_rich.rich_display_type_changed(display_built=True)
    console = rich.get_console()
    assert console.color_system is None
    assert not console.is_interactive


def test_restore_keeps_explicit_settings_for_redirected_output(
    fresh_display: None, terminal_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import sys

    monkeypatch.setattr(sys, "stdout", io.StringIO())
    rich.reconfigure(color_system="truecolor", force_interactive=True)
    rich_initialise("plain", plain=True)

    display_rich.rich_display_type_changed(display_built=True)
    console = rich.get_console()
    assert console.color_system == "truecolor"
    assert console.is_interactive
