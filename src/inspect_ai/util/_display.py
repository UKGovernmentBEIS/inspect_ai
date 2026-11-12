import os
from logging import getLogger
from typing import Literal

from inspect_ai._util._async import configured_async_backend
from inspect_ai._util.constants import DEFAULT_DISPLAY
from inspect_ai._util.thread import is_main_thread

logger = getLogger(__name__)

DisplayType = Literal["full", "conversation", "rich", "plain", "log", "none"]
"""Console display type."""


_display_type: DisplayType | None = None


def init_display_type(display: str | None = None) -> DisplayType:
    global _display_type
    display = (
        display or os.environ.get("INSPECT_DISPLAY", DEFAULT_DISPLAY).lower().strip()
    )
    display_name = display

    # if trio is configured as the backend then throttle down to "rich"
    # (as textual uses asyncio directly so is not compatible with trio)
    if configured_async_backend() == "trio" and display == "full":
        display = "rich"

    requested = display

    # if we are on a background thread then throttle down to "plain"
    # ("full" requires textual which cannot run in a background thread
    # b/c it calls the Python signal function; "rich" assumes exclusive
    # display access which may not be the case for threads)
    if display in ["full", "rich"] and not is_main_thread():
        display = "plain"

    new_display_type: DisplayType
    match display:
        case "full" | "conversation" | "rich" | "plain" | "log" | "none":
            new_display_type = display
        case _:
            logger.warning(
                f"Unknown display type '{display}' (setting display to 'full')"
            )
            new_display_type = "full"

    if _display_type is not None and new_display_type != _display_type:
        from inspect_ai._display.core.active import (
            active_display,
            clear_active_display,
        )
        from inspect_ai._display.core.rich import rich_console_in_use
        from inspect_ai._eval import eval as eval_module

        # a running eval, or a built display while the console has a live
        # display (e.g. progress for score() or a log conversion on another
        # thread) or the alternate screen open, keeps the display and the type
        # it is rendering with (a type that was only queried has no display)
        in_use = active_display() is not None and rich_console_in_use()
        if eval_module._eval_async_running or in_use:
            # a request for the current type that only differs because of the
            # background thread throttle (e.g. score() with no display called
            # from a scorer on a worker thread) isn't a change
            if requested != _display_type:
                logger.warning(
                    f"Ignoring display type '{display_name}' while the "
                    f"'{_display_type}' display is in use."
                )
            return _display_type

        # the active display was built for the previous type (e.g. by an
        # earlier eval() in this process), so drop it to be rebuilt
        clear_active_display()

    _display_type = new_display_type
    return _display_type


def display_type() -> DisplayType:
    """Get the current console display type.

    Returns:
       DisplayType: Display type.
    """
    global _display_type
    if _display_type:
        return _display_type
    else:
        return init_display_type()


def display_type_plain() -> bool:
    """Does the current display type prefer plain text?

    Returns:
       bool: True if the display type is "plain" or "log".
    """
    return display_type() in ["plain", "log"]


def display_type_initialized() -> bool:
    global _display_type
    return _display_type is not None


def display_counter(caption: str, value: str) -> None:
    """Display a counter in the UI.

    Args:
        caption: The counter's caption e.g. "HTTP rate limits".
        value: The counter's value e.g. "42".
    """
    from inspect_ai._display.core.active import display

    display().display_counter(caption, value)
