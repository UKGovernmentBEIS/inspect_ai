from rich import print
from rich.console import RenderableType
from rich.text import Text

from inspect_ai._util.transcript import transcript_panel


def conversation_panel(
    title: str,
    *,
    subtitle: str | None = None,
    content: RenderableType | list[RenderableType] = [],
) -> None:
    """Trace content into a standard trace panel display.

    Typically you would call `display_type() == "conversation"` to confirm that
    we are in conversation mode before calling `conversation_panel()`.

    Args:
      title (str): Panel title.
      subtitle (str | None): Panel subtitle. Optional.
      content (RenderableType | list[RenderableType]): One or more Rich renderables.
    """
    print(
        transcript_panel(title, subtitle, content),
        Text(),
    )
