import asyncio
import os
import sys
import traceback
import unicodedata
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


def rich_traceback(
    exc_type: Type[Any], exc_value: BaseException, exc_traceback: TracebackType | None
) -> RenderableType:
    rich_tb = Traceback.from_exception(
        exc_type=exc_type,
        exc_value=exc_value,
        traceback=exc_traceback,
        suppress=[click, asyncio, tenacity, sys.modules[PKG_NAME]],
        show_locals=os.environ.get("INSPECT_TRACEBACK_LOCALS", None) == "1",
        width=CONSOLE_DISPLAY_WIDTH,
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
    """Format exception traceback as plain text and ANSI-colored."""
    traceback_text, truncated = truncate_traceback(exc_type, exc_value, exc_traceback)

    if not truncated:
        with open(os.devnull, "w") as f:
            console = Console(record=True, file=f, legacy_windows=True)
            console.print(rich_traceback(exc_type, exc_value, exc_traceback))
            traceback_ansi = console.export_text(styles=True)
    else:
        traceback_ansi = traceback_text

    return traceback_text, traceback_ansi
