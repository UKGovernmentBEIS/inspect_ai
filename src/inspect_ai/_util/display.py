import os
from logging import getLogger
from typing import Literal

logger = getLogger(__name__)

DisplayType = Literal["full", "rich", "plain", "none"]


def display_type() -> DisplayType:
    display = os.environ.get("INSPECT_DISPLAY", "full").lower().strip()
    match display:
        case "full" | "rich" | "plain" | "none":
            if display == "full" and not _enable_full_display:
                return "rich"
            else:
                return display
        case _:
            logger.warning(f"Unknown display type '{display}'")
            return "full"


def enable_full_display() -> None:
    global _enable_full_display
    _enable_full_display = True


_enable_full_display: bool = False
