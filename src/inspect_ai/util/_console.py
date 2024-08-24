from contextlib import contextmanager
from typing import Iterator

from rich.console import Console


@contextmanager
def console_input() -> Iterator[Console]:
    """Console for receiving user input.

    Context manager that temporarily clears the task display and provides
    a console for receiving user input.
    """
    from inspect_ai._display._display import task_screen

    with task_screen().console_input() as console:
        yield console
