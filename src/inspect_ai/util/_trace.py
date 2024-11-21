from contextvars import ContextVar

from rich import print
from rich.console import RenderableType
from rich.text import Text

from inspect_ai._util.transcript import transcript_panel


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
        transcript_panel(title, subtitle, content),
        Text(),
    )


def init_trace(trace: bool | None) -> None:
    _trace.set(trace)


_trace: ContextVar[bool | None] = ContextVar("_trace_mode")
