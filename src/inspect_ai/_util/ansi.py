import os


def no_ansi() -> bool:
    return os.environ.get("INSPECT_NO_ANSI", None) is not None
