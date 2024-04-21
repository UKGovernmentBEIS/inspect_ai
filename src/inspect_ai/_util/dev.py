import os


def is_dev_mode() -> bool:
    return os.environ.get("INSPECT_DEV_MODE", None) is not None
