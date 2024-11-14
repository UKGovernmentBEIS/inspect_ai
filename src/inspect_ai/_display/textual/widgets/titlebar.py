from __future__ import annotations

from typing import Iterator

from rich.text import Text
from textual.app import RenderResult
from textual.reactive import Reactive
from textual.widget import Widget


class Titlebar(Widget):
    DEFAULT_CSS = """
    Titlebar {
        dock: top;
        width: 100%;
        background: $foreground 5%;
        color: $accent;
        height: 1;
    }
    """

    DEFAULT_CLASSES = ""

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        """Initialise the header widget.

        Args:
            name: The name of the header widget.
            id: The ID of the header widget in the DOM.
            classes: The CSS classes of the header widget.
        """
        super().__init__(name=name, id=id, classes=classes)

    def compose(self) -> Iterator[Widget]:
        yield TitlebarTitle()

    @property
    def title(self) -> str:
        return self._header_title().text

    @title.setter
    def title(self, title: str) -> None:
        self._header_title().text = title

    @property
    def sub_title(self) -> str:
        return self._header_title().sub_text

    @sub_title.setter
    def sub_title(self, sub_title: str) -> None:
        self._header_title().sub_text = sub_title

    def _header_title(self) -> TitlebarTitle:
        return self.query_one(TitlebarTitle)


class TitlebarTitle(Widget):
    """Display the title / subtitle in the header."""

    DEFAULT_CSS = """
    TitlebarTitle {
        content-align: center middle;
        width: 100%;
    }
    """

    text: Reactive[str] = Reactive("")
    """The main title text."""

    sub_text = Reactive("")
    """The sub-title text."""

    def render(self) -> RenderResult:
        """Render the title and sub-title.

        Returns:
            The value to render.
        """
        text = Text(self.text, no_wrap=True, overflow="ellipsis")
        if self.sub_text:
            text.append(" — ")
            text.append(self.sub_text, "dim")
        return text
