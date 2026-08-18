import os

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
    transient: bool | None = None,
    width: int | None = None,
    record_event: bool = True,
) -> Iterator[Console]:
    """Input screen for receiving user input.

    Context manager that clears the task display and provides a
    screen for receiving console input.

    Args:
      header (str | None): Header line to print above console
        content (defaults to printing no header)
      transient (bool): Return to task progress display after
        the user completes input (defaults to `True` for normal
        sessions and `False` when trace mode is enabled).
      width (int): Input screen width in characters (defaults to
        full width)
      record_event (bool): Emit an `InputEvent` to the transcript
        capturing the recorded console session (defaults to `True`).
        Set to `False` when the caller emits its own structured
        event for the interaction.

    Returns:
       Console to use for input.
    """
    from inspect_ai._display.core.active import task_screen

    with task_screen().input_screen(
        header=header, transient=transient, width=width, record_event=record_event
    ) as console:
        yield console
