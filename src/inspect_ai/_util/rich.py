import asyncio
import os
import sys
import traceback
import unicodedata
from collections import OrderedDict
from types import TracebackType
from typing import Any, Tuple, Type

import click
import tenacity
from rich.console import Console, RenderableType
from rich.style import Style
from rich.text import Text
from rich.traceback import Traceback

from inspect_ai._util.constants import CONSOLE_DISPLAY_WIDTH, PKG_NAME
from inspect_ai._util.text import truncate_lines

# LRU cache of rendered tracebacks (keyed by plain-text traceback)
_traceback_cache: OrderedDict[str, tuple[str, str]] = OrderedDict()
_TRACEBACK_CACHE_MAX_SIZE = 32

# Frame cap for the stored ANSI traceback. Keeps a runaway stack (e.g. a
# RecursionError) from rendering, and storing, a hundred source snippets.
_TRACEBACK_ANSI_MAX_FRAMES = 40


def tool_result_display(
    text: str, max_lines: int = 100, style: str | Style = ""
) -> list[RenderableType]:
    return lines_display(
        clean_control_characters(text), max_lines=max_lines, style=style
    )


def lines_display(
    text: str, max_lines: int = 100, style: str | Style = ""
) -> list[RenderableType]:
    lines, truncated = truncate_lines(text, max_lines)

    content: list[RenderableType] = [Text(lines, style=style)]
    if truncated is not None:
        content.append(Text())
        content.append(
            Text.from_markup(
                f"[italic]Output truncated ({truncated} additional lines)...[/italic]",
                style=style,
            )
        )

    return content


# clean control characters sent by untrusted sources (e.g. tool output)
# which can trigger rich text measurement bugs
def clean_control_characters(text: str) -> str:
    return "".join(
        c for c in text if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf")
    )


class _PlainCodeTraceback(Traceback):
    """Rich traceback whose frame source snippets are not syntax highlighted.

    Rich picks a pygments lexer per frame and lexes the frame's source file from
    its first line to the frame's line, which for large modules costs seconds
    per traceback. The "text" lexer is pygments' null lexer, so the snippets are
    still shown, just unhighlighted. If a future rich release stops consulting
    `_guess_lexer`, this degrades to full highlighting rather than failing.
    """

    @classmethod
    def _guess_lexer(cls, filename: str, code: str) -> str:
        return "text"


def rich_traceback(
    exc_type: Type[Any],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
    highlight_code: bool = True,
    max_frames: int = 100,
) -> RenderableType:
    """Rich renderable for an exception traceback.

    Args:
        exc_type: Exception type.
        exc_value: Exception value.
        exc_traceback: Exception traceback.
        highlight_code: Syntax highlight frame source snippets. Highlighting
            lexes each frame's whole source file, so pass `False` when the
            output will not be shown on a terminal at render time.
        max_frames: Maximum frames to show (the middle of the stack is elided);
            0 for no limit. Defaults to rich's own default of 100.
    """
    traceback_cls = Traceback if highlight_code else _PlainCodeTraceback
    rich_tb = traceback_cls.from_exception(
        exc_type=exc_type,
        exc_value=exc_value,
        traceback=exc_traceback,
        suppress=[click, asyncio, tenacity, sys.modules[PKG_NAME]],
        show_locals=os.environ.get("INSPECT_TRACEBACK_LOCALS", None) == "1",
        width=CONSOLE_DISPLAY_WIDTH,
        max_frames=max_frames,
    )
    return rich_tb


def truncate_traceback(
    exc_type: Type[Any],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
    max_length: int = 1048576,  # 1MB
) -> Tuple[str, bool]:
    tb_list = traceback.format_exception(exc_type, exc_value, exc_traceback)

    # Keep the front and back of the traceback
    header = tb_list[0]
    error_msg = tb_list[-1]

    # Join the middle parts (stack frames)
    frames = "".join(tb_list[1:-1])

    # It all fits, use it as is
    full_tb = header + frames + error_msg
    if len(full_tb) <= max_length:
        return full_tb, False

    ellipsis = "\n...\n"

    # Minimum header size
    header_size = min(len(header), 1024)

    # Minimum frames size
    frames_size = min(len(frames), 1024)

    # Remaining space for error message
    error_msg_size = max(0, max_length - header_size - frames_size)

    def truncate_middle(text: str, size: int) -> str:
        if len(text) <= size:
            return text
        half = (size - len(ellipsis)) // 2
        return f"{text[:half]}{ellipsis}{text[-half:]}"

    # Truncate each part as needed
    truncated_header = truncate_middle(header, header_size)
    truncated_frames = truncate_middle(frames, frames_size)
    truncated_error = truncate_middle(error_msg, error_msg_size)

    return truncated_header + truncated_frames + truncated_error, True


def format_traceback(
    exc_type: Type[BaseException],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
) -> tuple[str, str]:
    """Format exception traceback as plain text and ANSI-colored.

    The ANSI variant is stored in the log (`EvalError.traceback_ansi`) rather
    than shown on a terminal at render time, so its frame source snippets are
    not syntax highlighted and at most `_TRACEBACK_ANSI_MAX_FRAMES` frames are
    shown. The plain text variant is complete.
    """
    traceback_text, truncated = truncate_traceback(exc_type, exc_value, exc_traceback)

    # with INSPECT_TRACEBACK_LOCALS the ANSI render includes local variables,
    # which the plain-text cache key does not capture, so don't cache
    use_cache = os.environ.get("INSPECT_TRACEBACK_LOCALS", None) != "1"

    if use_cache:
        cached = _traceback_cache.get(traceback_text)
        if cached is not None:
            _traceback_cache.move_to_end(traceback_text)
            return cached

    if not truncated:
        with open(os.devnull, "w") as f:
            console = Console(record=True, file=f, legacy_windows=True)
            console.print(
                rich_traceback(
                    exc_type,
                    exc_value,
                    exc_traceback,
                    highlight_code=False,
                    max_frames=_TRACEBACK_ANSI_MAX_FRAMES,
                )
            )
            traceback_ansi = console.export_text(styles=True)
    else:
        traceback_ansi = traceback_text

    result = traceback_text, traceback_ansi
    if use_cache:
        _traceback_cache[traceback_text] = result
        while len(_traceback_cache) > _TRACEBACK_CACHE_MAX_SIZE:
            _traceback_cache.popitem(last=False)
    return result
