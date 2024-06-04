from datetime import datetime
from typing import Literal


def iso_now(
    timespec: Literal[
        "auto", "hours", "minutes", "seconds", "milliseconds" "microseconds"
    ] = "seconds",
) -> str:
    return datetime.now().astimezone().isoformat(timespec=timespec)
