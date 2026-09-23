import os
import re
import sys
from types import TracebackType
from typing import Callable

from rich.console import Console

from inspect_ai._util.rich import format_traceback, rich_traceback

_SGR = re.compile(r"\x1b\[[0-9;]*m")


def _raise_value_error() -> None:
    raise ValueError("test error message")


def _exc_info(
    fn: Callable[..., None], *args: object
) -> tuple[type[BaseException], BaseException, TracebackType | None]:
    try:
        fn(*args)
    except ValueError:
        exc_type, exc_value, exc_tb = sys.exc_info()
        assert exc_type is not None and exc_value is not None
        return exc_type, exc_value, exc_tb
    raise AssertionError("expected ValueError")


def _render_highlighted(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> str:
    with open(os.devnull, "w") as f:
        console = Console(record=True, file=f, legacy_windows=True)
        console.print(rich_traceback(exc_type, exc_value, exc_tb))
        return console.export_text(styles=True)


def test_format_traceback():
    try:
        raise ValueError("test error message")
    except ValueError as ex:
        text, ansi = format_traceback(type(ex), ex, ex.__traceback__)

    assert text is not None
    assert ansi is not None
    assert "ValueError" in text
    assert "test error message" in text
    assert "ValueError" in ansi


def test_format_traceback_ansi_skips_syntax_highlighting():
    exc_type, exc_value, exc_tb = _exc_info(_raise_value_error)
    _, ansi = format_traceback(exc_type, exc_value, exc_tb)

    # the source snippet is still present (with rich's frame styling) ...
    assert 'raise ValueError("test error message")' in _SGR.sub("", ansi)
    assert _SGR.search(ansi)
    # ... but without the per-token styling a pygments lexer would add
    highlighted = _render_highlighted(exc_type, exc_value, exc_tb)
    assert len(_SGR.findall(ansi)) < len(_SGR.findall(highlighted))
