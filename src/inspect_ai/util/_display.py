import os
from logging import getLogger
from typing import Literal

from inspect_ai._util._async import configured_async_backend
from inspect_ai._util.constants import DEFAULT_DISPLAY
from inspect_ai._util.thread import is_main_thread

logger = getLogger(__name__)

DisplayType = Literal["full", "conversation", "rich", "plain", "none"]
"""Console display type."""


_display_type: DisplayType | None = None


def init_display_type(display: str | None = None) -> DisplayType:
    global _display_type
    display = (
        display or os.environ.get("INSPECT_DISPLAY", DEFAULT_DISPLAY).lower().strip()
    )

    # if trio is configured as the backend then throttle down to "rich"
    # (as textual uses asyncio directly so is not compatible with trio)
    if configured_async_backend() == "trio" and display == "full":
        display = "rich"

    # if we are on a background thread then throttle down to "plain"
    # ("full" requires textual which cannot run in a background thread
    # b/c it calls the Python signal function; "rich" assumes exclusive
    # display access which may not be the case for threads)
    if display in ["full", "rich"] and not is_main_thread():
        display = "plain"

    match display:
        case "full" | "conversation" | "rich" | "plain" | "none":
            _display_type = display
        case _:
            logger.warning(
                f"Unknown display type '{display}' (setting display to 'full')"
            )
            _display_type = "full"
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
