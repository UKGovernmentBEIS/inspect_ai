from contextvars import ContextVar

from rich import print
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text


def trace_enabled() -> bool:
    """Is trace mode currently enabled."""
    return _trace.get(None) is True


def trace_panel(
    title: str,
    *,
    subtitle: str | None = None,
    content: RenderableType | list[RenderableType] = [],
) -> None:
    """Trace content into a standard trace panel display.

    Typically you would call `trace_enabled()` to confirm that trace mode
    is enabled before calling `trace_panel()`.

    Args:
      title (str): Panel title.
      subtitle (str | None): Panel subtitle. Optional.
      content (RenderableType | list[RenderableType]): One or more Rich renderables.
    """
    print(
        TracePanel(title, subtitle, content),
        Text(),
    )


class TracePanel(Panel):
    def __init__(
        self,
        title: str,
        subtitle: str | None = None,
        content: RenderableType | list[RenderableType] = [],
    ) -> None:
        # resolve content to list
        content = content if isinstance(content, list) else [content]

        # inject subtitle
        if subtitle:
            content.insert(0, Text())
            content.insert(0, Text.from_markup(f"[bold]{subtitle}[/bold]"))

        # use vs theme for markdown code
        for c in content:
            if isinstance(c, Markdown):
                c.code_theme = "xcode"

        super().__init__(
            Group(*content),
            title=f"[bold][blue]{title}[/blue][/bold]",
            highlight=True,
            expand=True,
        )


def init_trace(trace: bool | None) -> None:
    _trace.set(trace)


_trace: ContextVar[bool | None] = ContextVar("_trace_mode")
