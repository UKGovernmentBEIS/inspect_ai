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
    before = _display_settings(rich.get_console())

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
        console.__dict__, before, _display_settings(console)
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
    is a console replaced by `rich.reconfigure()`.
    """
    global _console_settings
    console = rich.get_console()
    if _console_settings and _console_settings.console_state is console.__dict__:
        for name, value in _console_settings.before.items():
            if getattr(console, name) == _console_settings.applied[name]:
                setattr(console, name, value)
    _console_settings = None


def rich_live_display_open() -> bool:
    """Is a Rich live display (e.g. progress or a status) open on the global console?"""
    console = rich.get_console()
    # rich >= 14.1 keeps a stack of live displays, earlier versions a single one
    return bool(getattr(console, "_live_stack", None)) or (
        getattr(console, "_live", None) is not None
    )


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
