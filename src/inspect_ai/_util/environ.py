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


@contextmanager
def environ_vars(env_vars: dict[str, str]) -> Iterator[None]:
    """
    Temporarily set multiple environment variables within a context.

    Args:
        env_vars: Dictionary mapping environment variable names to values

    Yields:
        None
    """
    # save previous values
    previous_values = {}
    for name in env_vars:
        previous_values[name] = os.environ.get(name)

    # set new values
    for name, value in env_vars.items():
        os.environ[name] = value

    try:
        yield
    finally:
        # Restore previous environment
        for name in env_vars:
            previous_value = previous_values[name]
            if previous_value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous_value
