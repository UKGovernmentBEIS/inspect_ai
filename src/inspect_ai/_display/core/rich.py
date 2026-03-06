from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

import rich
from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import CodeBlock, Markdown
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


def rich_initialise(
    display: DisplayType | None = None, plain: bool | None = None
) -> None:
    # default args
    display = display if display is not None else display_type()
    plain = plain if plain is not None else display_type_plain()

    # reflect ansi prefs
    if plain:
        rich.reconfigure(no_color=True, force_terminal=False, force_interactive=False)
    elif rich_no_color(plain):
        rich.reconfigure(no_color=True)

    # reflect display == none
    if display == "none":
        rich.reconfigure(quiet=True)

    # consistent markdown code bock background
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
