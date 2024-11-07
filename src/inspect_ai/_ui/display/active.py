import os
import sys

from inspect_ai._util.ansi import no_ansi

from .display import Display
from .rich.rich import RichDisplay
from .textual.textual import TextualDisplay


def display() -> Display:
    global _active_display
    if _active_display is None:
        have_tty = sys.stdout.isatty()
        if (
            have_tty
            and not no_ansi()
            and os.environ.get("INSPECT_TEXTUAL_UI", None) is not None
        ):
            _active_display = TextualDisplay()
        else:
            _active_display = RichDisplay()

    return _active_display


_active_display: Display | None = None
