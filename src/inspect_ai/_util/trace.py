from contextvars import ContextVar

from rich import print
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from .error import PrerequisiteError


def trace_multiple_samples_error() -> PrerequisiteError:
    return PrerequisiteError(
        "Trace mode can only be used for single task, simple sample evaluations."
    )


def trace_enabled() -> bool:
    return _trace.get(None) is True


def trace_message(title: str, content: str) -> None:
    if trace_enabled():
        print(
            TracePanel("Message", Text.from_markup(f"{title}\n"), content),
            Text(),
        )


class TracePanel(Panel):
    def __init__(self, title: str, *renderable: RenderableType) -> None:
        super().__init__(
            Group(*renderable),
            title=f"[bold][blue]{title}[/blue][/bold]",
            highlight=True,
            expand=True,
        )


def init_trace(trace: bool | None) -> None:
    _trace.set(trace)


_trace: ContextVar[bool | None] = ContextVar("_trace_mode")
