from typing import cast

from rich.console import RenderableType
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class AppFooter(Widget):
    DEFAULT_CSS = """
    AppFooter {
        layout: grid;
        grid-size: 2 1;
        grid-columns: 1fr auto;
        grid-gutter: 2;
        background: $foreground 5%;
        color: $text-muted;
        dock: bottom;
        height: auto;
        padding: 0 1
    }
    """

    left: reactive[RenderableType] = reactive("")
    right: reactive[RenderableType] = reactive("")

    def compose(self) -> ComposeResult:
        yield Static(id="footer-left")
        yield Static(id="footer-right")

    def watch_left(self, new_left: RenderableType) -> None:
        footer_left = cast(Static, self.query_one("#footer-left"))
        footer_left.update(new_left)

    def watch_right(self, new_right: RenderableType) -> None:
        footer_right = cast(Static, self.query_one("#footer-right"))
        footer_right.update(new_right)
