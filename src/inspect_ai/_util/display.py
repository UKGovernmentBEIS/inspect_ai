import os
from logging import getLogger
from typing import Literal

from inspect_ai._util.constants import DEFAULT_DISPLAY

logger = getLogger(__name__)

DisplayType = Literal["full", "rich", "plain", "none"]


def display_type() -> DisplayType:
    display = os.environ.get("INSPECT_DISPLAY", DEFAULT_DISPLAY).lower().strip()
    match display:
        case "full" | "rich" | "plain" | "none":
            return display
        case _:
            logger.warning(f"Unknown display type '{display}'")
            return "full"
