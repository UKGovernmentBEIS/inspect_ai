import os
from typing import Any

from rich.console import Console, RenderableType


def render_text(
    text: RenderableType | list[RenderableType], styles: bool = True, **options: Any
) -> str:
    """Render text from Rich renderables.

    Args:
      text (RenderableType | list[RenderableType]): Renderables.
      styles (bool): If True, ansi escape codes will be included. False for plain text.
        Defaults to True.
      **options (Any): Additonal keyword arguments to pass to `Console` constructor.

    Returns:
       str: Rendered text (with ansi codes if `styles=True`)
    """
    # resolve to text
    text = text if isinstance(text, list) else [text]

    # print to console attached to /dev/null
    with open(os.devnull, "w") as f:
        console = Console(file=f, record=True, force_terminal=True, **options)
        for t in text:
            console.print(t)

    # export (optionally w/ ansi styles)
    return console.export_text(styles=styles).strip()
