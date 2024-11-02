import sys

from inspect_ai._util.ansi import no_ansi

from .display import Display
from .display_rich import RichDisplay
from .display_textual import TextualDisplay


def display() -> Display:
    global _active_display
    if _active_display is None:
        force_rich = True
        have_tty = sys.stdout.isatty()
        if have_tty and not no_ansi() and not force_rich:
            _active_display = TextualDisplay()
        else:
            _active_display = RichDisplay()

    return _active_display


_active_display: Display | None = None
