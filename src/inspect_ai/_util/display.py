import os


def no_ansi() -> bool:
    display = os.environ.get("INSPECT_DISPLAY", None)
    return display is not None and display.lower() in ["plain", "none"]


def no_display() -> bool:
    return os.environ.get("INSPECT_DISPLAY", None) == "none"
