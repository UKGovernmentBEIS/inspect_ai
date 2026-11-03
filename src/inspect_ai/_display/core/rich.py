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

    # set attributes rather than rich.reconfigure(), which would replace the
    # user's other console options and any active capture or live display
    console = rich.get_console()
    if _console_settings and _console_settings.console_state is console.__dict__:
        before = _console_settings.before
    else:
        before = _display_settings(console)

    # reflect ansi prefs
    if plain:
        console.no_color = True
        console._force_terminal = False
        console._color_system = console._detect_color_system()
        console.is_interactive = False
    elif rich_no_color(plain):
        console.no_color = True
    if size_kwargs:
        console.size = (size_kwargs["width"], size_kwargs["height"])

    # reflect display == none
    if display == "none":
        console.quiet = True

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
