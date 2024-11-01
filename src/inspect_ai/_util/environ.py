import os
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def environ_var(name: str, value: str) -> Iterator[None]:
    """
    Temporarily set an environment variable within a context.

    Args:
        name: Name of the environment variable to set
        value: Value to set the environment variable to

    Yields:
        None
    """
    previous_value = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if previous_value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous_value
