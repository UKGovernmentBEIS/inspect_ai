import os
from logging import getLogger
from typing import Literal

from inspect_ai._util.constants import DEFAULT_DISPLAY

logger = getLogger(__name__)

DisplayType = Literal["full", "rich", "plain", "none"]


_display_type: DisplayType | None = None
_display_metrics: bool = True


def init_display_type(
    display: str | None = None, display_metrics: bool = True
) -> DisplayType:
    global _display_type
    global _display_metrics
    display = (
        display or os.environ.get("INSPECT_DISPLAY", DEFAULT_DISPLAY).lower().strip()
    )
    _display_metrics = display_metrics
    match display:
        case "full" | "rich" | "plain" | "none":
            _display_type = display
        case _:
            logger.warning(f"Unknown display type '{display}'")
            _display_type = "full"
    return _display_type


def display_type() -> DisplayType:
    global _display_type
    if _display_type:
        return _display_type
    else:
        return init_display_type()


def display_metrics() -> bool:
    global _display_metrics
    return _display_metrics
