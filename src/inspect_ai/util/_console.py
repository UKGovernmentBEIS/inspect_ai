from contextlib import contextmanager
from typing import Iterator

from rich.console import Console


@contextmanager
def console_input(
    header: str | None = None, transient: bool = True
) -> Iterator[Console]:
    """Console for receiving user input.

    Context manager that clears the task display and provides a
    console for receiving user input.

    Args:
       header (str | None): Header line to print above console
         content (defaults to printing no header)
       transient (bool): Return the console to the task display
         after input is provided (defaults to `True`)

    Returns:
       Console to use for input.
    """
    from inspect_ai._display._display import task_screen

    with task_screen().console_input(header=header, transient=transient) as console:
        yield console
