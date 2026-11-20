import os
import sys
from typing import Callable, TextIO

import anyio
import pytest
import rich
from rich.console import Console

import inspect_ai._display.core.rich as display_rich
from inspect_ai._display.core.rich import (
    _dumb_terminal_size_kwargs,
    rich_initialise,
    rich_restore_defaults,
)
from inspect_ai._display.rich.display import RichDisplay


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


def test_rich_initialise_keeps_a_render_hook_the_caller_registered(monkeypatch):
    """A host that registered a render hook can still pop it after the eval."""
    import rich
    from rich.console import Console, ConsoleRenderable, RenderHook

    class _Hook(RenderHook):
        def process_renderables(
            self, renderables: list[ConsoleRenderable]
        ) -> list[ConsoleRenderable]:
            return renderables

    console = Console(force_terminal=False)
    monkeypatch.setattr(rich, "_console", console)
    hook = _Hook()
    console.push_render_hook(hook)

    rich_initialise(display="none", plain=True)

    assert rich.get_console() is console
    assert list(getattr(console, "_render_hooks", [])) == [hook]
    console.pop_render_hook()


def test_rich_initialise_keeps_a_hosts_progress_context_usable(monkeypatch):
    """Entering an eval inside a host context must not break leaving that context.

    ``rich.reconfigure()`` drops the render hook the ``Progress`` pushed, so ``__exit__``
    would pop from an empty list.
    """
    import rich
    from rich.console import Console
    from rich.progress import Progress

    monkeypatch.setattr(rich, "_console", Console(force_terminal=False))

    with Progress(redirect_stdout=False, redirect_stderr=False) as progress:
        progress.add_task("host", total=1)
        rich_initialise(display="none", plain=True)

        console = rich.get_console()
        assert getattr(console, "_render_hooks", [])


class _SetupFailed(Exception):
    pass


_CHILD_OUTPUT = "build step 1"
_LATER_CHILD_OUTPUT = "build step 2"


async def _write_from_child(out: TextIO, text: str) -> None:
    out.flush()
    await anyio.run_process(
        [sys.executable, "-c", f"print({text!r})"], stdout=out.fileno()
    )


async def _run_setup(
    display: RichDisplay,
    out: TextIO,
    end: str,
    meanwhile: Callable[[], None] | None = None,
) -> None:
    """A sandbox setup whose child process writes to the terminal descriptor.

    `meanwhile` runs between two child writes, as another task would while
    the setup awaits its child.
    """
    with anyio.CancelScope() as scope:
        with display.suspend_task_app():
            await _write_from_child(out, _CHILD_OUTPUT)
            if meanwhile is not None:
                meanwhile()
                await _write_from_child(out, _LATER_CHILD_OUTPUT)
            if end == "error":
                raise _SetupFailed()
            elif end == "cancel":
                scope.cancel()
                await anyio.lowlevel.checkpoint()
    assert scope.cancelled_caught == (end == "cancel")


def _assert_output_kept(output: str, redrawn: str) -> None:
    before, child, after = output.partition(_CHILD_OUTPUT + "\n")
    assert child, output
    # the live render was cleared before the child wrote its line ...
    assert before.endswith("\x1b[2K"), repr(before[-80:])
    # ... and is drawn again below it without moving the cursor back over it
    redraw = after.index(redrawn)
    assert "\x1b[1A" not in after[:redraw], repr(after[:redraw])


def _terminal_console(height: int | None = None) -> tuple[Console, int, TextIO]:
    """A terminal console on a pipe (use with the ``terminal_env`` fixture)."""
    read_fd, write_fd = os.pipe()
    out = os.fdopen(write_fd, "w")
    console = Console(
        file=out, force_terminal=True, width=60, height=height, color_system=None
    )
    return console, read_fd, out


def _read_all(read_fd: int, out: TextIO) -> str:
    out.close()
    chunks = []
    while chunk := os.read(read_fd, 65536):
        chunks.append(chunk)
    os.close(read_fd)
    return b"".join(chunks).decode()


@pytest.mark.anyio
@pytest.mark.parametrize("end", ["normal", "error", "cancel"])
async def test_rich_setup_output_is_written_above_the_task_display(
    fresh_display: None,
    terminal_env: None,
    monkeypatch: pytest.MonkeyPatch,
    end: str,
) -> None:
    """Output a sandbox setup's child process writes is not drawn over."""
    display = RichDisplay()
    console, read_fd, out = _terminal_console()
    monkeypatch.setattr(rich, "_console", console)
    async with display.task_screen([], parallel=False):
        assert display.live is not None
        display.live.update("TASK TOP\nTASK BOTTOM", refresh=True)
        if end == "error":
            with pytest.raises(_SetupFailed):
                await _run_setup(display, out, end)
        else:
            await _run_setup(display, out, end)
        assert display.live.is_started
        display.live.update("TASK TOP\nTASK BOTTOM 2", refresh=True)

    _assert_output_kept(_read_all(read_fd, out), "TASK TOP")


@pytest.mark.anyio
@pytest.mark.parametrize("end", ["normal", "error", "cancel"])
async def test_rich_setup_keeps_a_tall_task_display_cropped(
    fresh_display: None,
    terminal_env: None,
    monkeypatch: pytest.MonkeyPatch,
    end: str,
) -> None:
    """A task display taller than the terminal is still cropped after setup."""
    display = RichDisplay()
    console, read_fd, out = _terminal_console(height=24)
    monkeypatch.setattr(rich, "_console", console)
    async with display.task_screen([], parallel=False):
        assert display.live is not None
        display.live.update("\n".join(f"ROW {i}" for i in range(40)), refresh=True)
        if end == "error":
            with pytest.raises(_SetupFailed):
                await _run_setup(display, out, end)
        else:
            await _run_setup(display, out, end)
        assert display.live.vertical_overflow == "ellipsis"
        display.live.update("\n".join(f"AFTER {i}" for i in range(40)), refresh=True)
        # the end of that redraw (the final render on exit is not cropped)
        out.write("REDRAWN\n")
        out.flush()

    output = _read_all(read_fd, out)
    after = output[output.index("AFTER 0") : output.index("REDRAWN")]
    assert "AFTER 22" in after
    assert "AFTER 39" not in after


@pytest.mark.anyio
@pytest.mark.parametrize("end", ["normal", "error", "cancel"])
async def test_rich_setup_output_is_written_above_the_mini_status(
    fresh_display: None,
    terminal_env: None,
    monkeypatch: pytest.MonkeyPatch,
    end: str,
) -> None:
    """The mini-status a non-transient input screen leaves is cleared too."""
    display = RichDisplay()
    console, read_fd, out = _terminal_console()
    monkeypatch.setattr(rich, "_console", console)
    async with display.task_screen([], parallel=False) as screen:
        with screen.input_screen(transient=False, record_event=False):
            pass
        assert display.screen is not None and display.screen.status_started
        # draw it now rather than on its next tick
        display.screen.status.update(spinner="clock")
        if end == "error":
            with pytest.raises(_SetupFailed):
                await _run_setup(display, out, end)
        else:
            await _run_setup(display, out, end)
        assert display.screen.status_started
        assert display.live is not None and not display.live.is_started

    _assert_output_kept(_read_all(read_fd, out), "Task running")


def _redraw_tick(display: RichDisplay) -> None:
    """Redraw the renderers that are running, as the display's ticks do."""
    assert display.live is not None and display.screen is not None
    if display.live.is_started:
        display.live.update("TASK TOP\nTASK BOTTOM", refresh=True)
    display.screen.status.update(spinner="clock")


@pytest.mark.anyio
@pytest.mark.parametrize("end", ["normal", "error", "cancel"])
@pytest.mark.parametrize("transient", [True, False])
@pytest.mark.parametrize("showing", ["task_display", "mini_status"])
async def test_rich_input_screen_closed_during_setup_draws_after_setup(
    fresh_display: None,
    terminal_env: None,
    monkeypatch: pytest.MonkeyPatch,
    showing: str,
    transient: bool,
    end: str,
) -> None:
    """An input screen closed during setup starts its renderers when setup ends."""
    display = RichDisplay()
    console, read_fd, out = _terminal_console()
    monkeypatch.setattr(rich, "_console", console)
    async with display.task_screen([], parallel=False) as screen:
        assert display.live is not None and display.screen is not None
        if showing == "mini_status":
            with screen.input_screen(transient=False, record_event=False):
                pass
        _redraw_tick(display)

        def close_input_screen() -> None:
            with screen.input_screen(transient=transient, record_event=False):
                pass
            _redraw_tick(display)

        if end == "error":
            with pytest.raises(_SetupFailed):
                await _run_setup(display, out, end, close_input_screen)
        else:
            await _run_setup(display, out, end, close_input_screen)

        assert display.live.is_started == transient
        assert display.screen.status_started == (not transient)
        _redraw_tick(display)

    output = _read_all(read_fd, out)
    _, _, during = output.partition(_CHILD_OUTPUT + "\n")
    during, later, _ = during.partition(_LATER_CHILD_OUTPUT + "\n")
    assert later, output
    # nothing was drawn between the two child writes ...
    assert "TASK" not in during and "Task running" not in during, repr(during)
    # ... and the renderer the input screen selected is drawn below them
    _assert_output_kept(output, "TASK TOP" if transient else "Task running")


class _OutputWidget:
    """Stands in for the ipywidgets Output that a notebook Live renders into."""

    created: list["_OutputWidget"] = []

    def __init__(self) -> None:
        self.closed = False
        self.uses = 0
        self.uses_after_close = 0
        _OutputWidget.created.append(self)

    def __enter__(self) -> None:
        self.uses += 1
        if self.closed:
            self.uses_after_close += 1

    def __exit__(self, *excinfo: object) -> None:
        pass

    def clear_output(self, wait: bool = False) -> None:
        pass

    def close(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_rich_setup_keeps_the_notebook_output_widget(
    fresh_display: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In a notebook, setup leaves the task display's output widget open."""
    import types

    ipywidgets = types.ModuleType("ipywidgets")
    setattr(ipywidgets, "Output", _OutputWidget)
    monkeypatch.setitem(sys.modules, "ipywidgets", ipywidgets)
    monkeypatch.setattr("IPython.display.display", lambda *args, **kwargs: None)
    monkeypatch.setattr(_OutputWidget, "created", [])

    display = RichDisplay()
    monkeypatch.setattr(rich, "_console", Console(force_jupyter=True))
    async with display.task_screen([], parallel=False):
        assert display.live is not None
        display.live.update("TASK", refresh=True)
        with display.suspend_task_app():
            pass
        display.live.update("TASK 2", refresh=True)

    # one widget, used for progress after setup and for the final results
    [widget] = _OutputWidget.created
    assert not widget.closed
    assert widget.uses_after_close == 0
    assert widget.uses >= 3
