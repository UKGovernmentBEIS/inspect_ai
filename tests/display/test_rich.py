import contextlib
import io
from types import SimpleNamespace
from typing import Any, Callable, Iterator, cast

import pytest
import rich
from rich.live import Live

import inspect_ai._display.core.rich as display_rich
from inspect_ai._display.core.display import TaskScreen
from inspect_ai._display.core.rich import (
    _dumb_terminal_size_kwargs,
    rich_initialise,
    rich_restore_defaults,
)
from inspect_ai._display.rich.display import RichTaskScreen
from inspect_ai._display.textual.app import TextualTaskScreen
from inspect_ai.event._input import InputEvent
from inspect_ai.log._transcript import Transcript, _transcript


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


@contextlib.contextmanager
def _rich_task_screen() -> Iterator[TaskScreen]:
    with Live(console=rich.get_console()) as live:
        yield RichTaskScreen(live)


@contextlib.contextmanager
def _textual_task_screen() -> Iterator[TaskScreen]:
    app = SimpleNamespace(suspend_app=contextlib.nullcontext)
    yield TextualTaskScreen(cast(Any, app))


TaskScreenFactory = Callable[[], contextlib.AbstractContextManager[TaskScreen]]


def _run_input_screen(task_screen: TaskScreenFactory) -> InputEvent:
    transcript = Transcript()
    token = _transcript.set(transcript)
    try:
        with task_screen() as screen:
            with screen.input_screen() as screen_console:
                screen_console.print("approve the tool call?")
    finally:
        _transcript.reset(token)
    [event] = [e for e in transcript.events if isinstance(e, InputEvent)]
    return event


@pytest.mark.parametrize("task_screen", [_rich_task_screen, _textual_task_screen])
def test_input_screen_keeps_caller_recording(
    fresh_display: None, task_screen: TaskScreenFactory
) -> None:
    rich.reconfigure(record=True, file=io.StringIO())
    console = rich.get_console()
    console.print("before the eval")
    event = _run_input_screen(task_screen)
    console.print("after the eval")

    assert "approve the tool call?" in event.input
    assert "before the eval" not in event.input
    assert console.record
    recording = console.export_text()
    for text in ["before the eval", "approve the tool call?", "after the eval"]:
        assert recording.count(text) == 1


@pytest.mark.parametrize("task_screen", [_rich_task_screen, _textual_task_screen])
def test_input_screen_shows_interaction_during_caller_capture(
    fresh_display: None, task_screen: TaskScreenFactory
) -> None:
    output = io.StringIO()
    rich.reconfigure(file=output)
    console = rich.get_console()
    with console.capture() as capture:
        console.print("before the eval")
        event = _run_input_screen(task_screen)
        console.print("after the eval")

    assert "approve the tool call?" in event.input
    assert "approve the tool call?" in event.input_ansi
    assert "approve the tool call?" in output.getvalue()
    captured = capture.get()
    assert "before the eval" in captured
    assert "after the eval" in captured
    assert "approve the tool call?" not in captured
