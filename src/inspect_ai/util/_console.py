import os

from inspect_ai._util.constants import CONSOLE_DISPLAY_WIDTH

if os.name == "posix":
    # This makes Rich console input better if imported, but
    # raises a ModuleNotFound error on Windows, so posix only
    import readline  # noqa: F401
from contextlib import contextmanager
from typing import Iterator

from rich.console import Console


@contextmanager
def input_screen(
    header: str | None = None,
    transient: bool = True,
    width: int = CONSOLE_DISPLAY_WIDTH,
) -> Iterator[Console]:
    """Input screen for receiving user input.

    Context manager that clears the task display and provides a
    screen for receiving console input.

    Args:
      header (str | None): Header line to print above console
        content (defaults to printing no header)
      transient (bool): Return to task progress display after
        the user completes input (defaults to `True`).
      width (int): Input screen width in characters (defaults to
        120, and is reduced if greater that the console width).

    Returns:
       Console to use for input.
    """
    from inspect_ai._display._display import task_screen

    with task_screen().input_screen(
        header=header, transient=transient, width=width
    ) as console:
        yield console
