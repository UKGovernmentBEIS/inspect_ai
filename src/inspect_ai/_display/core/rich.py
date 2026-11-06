import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

import rich
from rich.console import Console, ConsoleOptions, RenderResult
from rich.segment import Segment
from rich.syntax import Syntax
from typing_extensions import override

from inspect_ai._util.platform import is_running_in_jupyterlab, is_running_in_vscode
from inspect_ai._util.transcript import transcript_code_theme
from inspect_ai.util._display import DisplayType, display_type, display_type_plain


def is_vscode_notebook(console: Console) -> bool:
    return console.is_jupyter and is_running_in_vscode()


def rich_no_color(plain: bool) -> bool:
    return plain or not is_running_in_vscode() or is_running_in_jupyterlab()


_DISPLAY_SETTINGS = (
    "no_color",
    "quiet",
    "is_interactive",
    "_force_terminal",
    "_color_system",
    "_width",
    "_height",
)
"""Global console attributes that rich_initialise changes for a display type."""


@dataclass
class _ConsoleSettings:
    console_state: dict[str, Any]
    """The console's `__dict__`, which `rich.reconfigure()` replaces."""

    before: dict[str, Any]
    """Display settings before rich_initialise changed them."""

    applied: dict[str, Any]
    """Display settings as rich_initialise last left them."""

    detected: frozenset[str]
    """Settings in `before` that the console detected for its output."""


_console_settings: _ConsoleSettings | None = None

_reconfigure_in_place = False
"""Whether rich_initialise sets display settings on the existing console.

Set by a display type change after a display was built. Replacing the console
there (as `rich.reconfigure()` does) would also drop console state from after
that display started, such as an open theme, capture
or live display, a recording, or options set by the user between evals. A
process without such a change is unaffected.
"""


def _display_settings(console: Console) -> dict[str, Any]:
    return {name: getattr(console, name) for name in _DISPLAY_SETTINGS}


_DETECTED_SETTINGS = ("_color_system", "is_interactive")
"""Display settings the console detects for its output, unless set explicitly."""


def _detected_settings(console: Console) -> dict[str, Any]:
    """The detected settings for the console's current output and options."""
    detected = Console(
        file=console._file,
        stderr=console.stderr,
        force_terminal=console._force_terminal,
        force_jupyter=console.is_jupyter,
        legacy_windows=console.legacy_windows,
        _environ=console._environ,
    )
    return {name: getattr(detected, name) for name in _DETECTED_SETTINGS}


def rich_initialise(
    display: DisplayType | None = None, plain: bool | None = None
) -> None:
    global _console_settings

    # default args
    display = display if display is not None else display_type()
    plain = plain if plain is not None else display_type_plain()
    size_kwargs = _dumb_terminal_size_kwargs()

    # undo an earlier call first (textual calls this for each eval), so the
    # snapshot holds the user's settings rather than ours
    rich_restore_defaults()
    console = rich.get_console()
    before = _display_settings(console)
    detected = frozenset(
        name
        for name, value in _detected_settings(console).items()
        if before[name] == value
    )

    # reflect ansi prefs
    if plain:
        _reconfigure(
            no_color=True,
            force_terminal=False,
            force_interactive=False,
            **size_kwargs,
        )
    elif rich_no_color(plain):
        _reconfigure(no_color=True, **size_kwargs)
    elif size_kwargs:
        _reconfigure(**size_kwargs)

    # reflect display == none
    if display == "none":
        _reconfigure(quiet=True)

    console = rich.get_console()
    _console_settings = _ConsoleSettings(
        console.__dict__, before, _display_settings(console), detected
    )

    # consistent markdown code bock background
    from rich.markdown import CodeBlock, Markdown

    class CustomCodeBlock(CodeBlock):
        @override
        def __rich_console__(
            self, console: Console, options: ConsoleOptions
        ) -> RenderResult:
            code = str(self.text).rstrip()
            syntax = Syntax(
                code,
                self.lexer_name,
                theme=transcript_code_theme(),
                word_wrap=True,
                background_color="#282c34",
                padding=0,
            )
            yield syntax

    Markdown.elements["fence"] = CustomCodeBlock
    Markdown.elements["code_block"] = CustomCodeBlock


def _reconfigure(**kwargs: Any) -> None:
    if _reconfigure_in_place:
        # the display settings rich.reconfigure() would give, detected for the
        # existing console's output and set on it
        console = rich.get_console()
        configured = Console(
            file=console._file,
            stderr=console.stderr,
            force_jupyter=console.is_jupyter,
            legacy_windows=console.legacy_windows,
            _environ=console._environ,
            **kwargs,
        )
        for name in _DISPLAY_SETTINGS:
            setattr(console, name, getattr(configured, name))
    else:
        rich.reconfigure(**kwargs)


def rich_display_type_changed(display_built: bool) -> None:
    """Prepare the console for a display rebuilt after a display type change.

    Args:
       display_built: Whether a display was built for the previous type (and
          not only the type queried, e.g. by `get_model().generate()`).
    """
    global _reconfigure_in_place
    if display_built:
        _reconfigure_in_place = True
    rich_restore_defaults()


def rich_restore_defaults() -> None:
    """Undo the global console display settings made by rich_initialise.

    rich_initialise only sets what the current display type needs, so settings
    for an earlier type (e.g. quiet for "none", or plain's terminal detection)
    would otherwise carry over to the next one. Settings changed since
    rich_initialise (e.g. by the user between evals) are left as they are, as
    is a console replaced by `rich.reconfigure()`. Settings the console had
    detected are detected again, as its output may have changed since (e.g.
    stdout redirected to a file).
    """
    global _console_settings
    console = rich.get_console()
    settings = _console_settings
    if settings and settings.console_state is console.__dict__:
        restore = [
            name
            for name in _DISPLAY_SETTINGS
            if settings.before[name] != settings.applied[name]
            and getattr(console, name) == settings.applied[name]
        ]
        for name in restore:
            setattr(console, name, settings.before[name])
        detected = _detected_settings(console)
        for name in restore:
            if name in settings.detected:
                setattr(console, name, detected[name])
    _console_settings = None


def rich_console_in_use() -> bool:
    """Is a live display (e.g. progress or a status) or the alternate screen open?

    Changing the global console's display settings under either would change
    how it renders, or (for the alternate screen) stop it restoring the
    terminal when it closes.
    """
    console = rich.get_console()
    # rich >= 14.1 keeps a stack of live displays, earlier versions a single one
    live = bool(getattr(console, "_live_stack", None)) or (
        getattr(console, "_live", None) is not None
    )
    return live or console.is_alt_screen


def _dumb_terminal_size_kwargs() -> dict[str, int]:
    if os.environ.get("TERM") != "dumb":
        return {}

    columns = _positive_int_env("COLUMNS")
    if columns is None:
        return {}

    return {
        "width": columns,
        "height": _positive_int_env("LINES") or 25,
    }


def _positive_int_env(name: str) -> int | None:
    try:
        value = int(os.environ[name])
    except (KeyError, ValueError):
        return None
    return value if value > 0 else None


@dataclass
class RichTheme:
    meta: str = "blue"
    light: str = "bright_black"
    metric: str = "green"
    link: str = "blue"
    success: str = "green"
    error: str = "red"
    warning: str = "orange3"


def rich_theme() -> RichTheme:
    global _theme
    if _theme is None:
        _theme = RichTheme()
    return _theme


_theme: RichTheme | None = None


@contextmanager
def input_screen_capture_suspended(console: Console) -> Iterator[None]:
    """Show an input screen inside a caller's `console.capture()`.

    Only after a display type change, when the console (with a capture opened
    before the change) is kept rather than replaced, so the capture would hide
    the screen's prompt. Output the capture holds is set aside for the screen
    and restored after it. Without a change, a capture behaves as before.
    """
    if not _reconfigure_in_place:
        yield
        return

    thread_locals = console._thread_locals
    pending, pending_index = thread_locals.buffer, thread_locals.buffer_index
    thread_locals.buffer, thread_locals.buffer_index = [], 0
    try:
        yield
    finally:
        thread_locals.buffer, thread_locals.buffer_index = pending, pending_index


@contextmanager
def input_screen_recording(console: Console, record_event: bool) -> Iterator[None]:
    """Record an input screen's output and input, as an `InputEvent` if requested.

    After a display type change the console is kept with any recording the
    caller started, so the screen records to a buffer of its own and the
    caller's recording is restored afterwards, with the interaction added if
    it was on. Without a change, the screen records to the console's buffer
    and ends the recording, as before.
    """
    from inspect_ai.event._input import InputEvent
    from inspect_ai.log._transcript import transcript

    isolate = _reconfigure_in_place
    with console._record_buffer_lock:
        caller_record, caller_buffer = console.record, console._record_buffer
        if isolate:
            console._record_buffer = []
    console.record = True
    try:
        yield
    finally:
        if isolate:
            with console._record_buffer_lock:
                interaction = list(console._record_buffer)
            input = console.export_text(clear=False, styles=False)
            input_ansi = console.export_text(clear=False, styles=True)
            with console._record_buffer_lock:
                if caller_record:
                    caller_buffer.extend(interaction)
                console._record_buffer = caller_buffer
            console.record = caller_record
        else:
            input = console.export_text(clear=False, styles=False)
            input_ansi = console.export_text(clear=True, styles=True)
            console.record = False
        if record_event:
            transcript()._event(InputEvent(input=input, input_ansi=input_ansi))


@contextmanager
def record_console_input() -> Iterator[None]:
    # monkey patch .input method to record inputs
    input_original = Console.input

    def input_with_record(self: Console, *args: Any, **kwargs: Any) -> str:
        result = input_original(self, *args, **kwargs)
        if self.record:
            with self._record_buffer_lock:
                self._record_buffer.append(Segment(result))
        return result

    Console.input = input_with_record  # type: ignore

    try:
        yield
    finally:
        Console.input = input_original  # type: ignore
