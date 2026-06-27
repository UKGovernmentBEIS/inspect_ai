import asyncio
import os
import re
import sys
import traceback
import unicodedata
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Tuple, Type

import click
import tenacity
from rich.console import Console, ConsoleOptions, RenderableType, RenderResult
from rich.segment import Segment
from rich.style import Style, StyleType
from rich.text import Span, Text
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


def clean_control_characters(text: str) -> str:
    """Remove terminal-directed controls while preserving useful whitespace."""
    return "".join(
        c for c in text if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf")
    )


@dataclass
class _ControlCharacterCleanRenderable:
    renderable: RenderableType

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        for segment in console.render(self.renderable, options):
            if segment.control:
                yield segment
            else:
                yield Segment(
                    clean_control_characters(segment.text),
                    segment.style,
                )


def clean_control_characters_renderable(
    renderable: RenderableType,
) -> RenderableType:
    """Clean text emitted by a nested Rich renderable without removing styles."""
    return _ControlCharacterCleanRenderable(renderable)


def untrusted_text_from_ansi(text: str) -> Text:
    """Parse visual ANSI styles while discarding controls and hyperlinks."""
    safe_ansi: list[str] = []
    offset = 0
    for match in re.finditer(r"\x1b\[[0-9;:]*m", text):
        safe_ansi.append(clean_control_characters(text[offset : match.start()]))
        safe_ansi.append(match.group())
        offset = match.end()
    safe_ansi.append(clean_control_characters(text[offset:]))

    parsed = Text.from_ansi("".join(safe_ansi))
    plain = parsed.plain

    offsets = [0]
    cleaned: list[str] = []
    for char in plain:
        if char in "\n\t" or unicodedata.category(char) not in ("Cc", "Cf"):
            cleaned.append(char)
        offsets.append(len(cleaned))

    def safe_style(style: StyleType) -> StyleType:
        return (
            style.update_link(None)
            if isinstance(style, Style) and style.link
            else style
        )

    spans = [
        Span(offsets[span.start], offsets[span.end], safe_style(span.style))
        for span in parsed.spans
        if offsets[span.start] < offsets[span.end]
    ]
    return Text(
        "".join(cleaned),
        style=safe_style(parsed.style),
        justify=parsed.justify,
        overflow=parsed.overflow,
        no_wrap=parsed.no_wrap,
        end=parsed.end,
        tab_size=parsed.tab_size,
        spans=spans,
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
    return clean_control_characters_renderable(rich_tb)


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
