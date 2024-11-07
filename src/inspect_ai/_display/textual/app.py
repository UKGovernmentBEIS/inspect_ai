from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from inspect_ai._util.terminal import detect_terminal_background

from ..core.rich import rich_initialise


class TaskScreenApp(App[None]):
    TITLE = "Inspect Eval"
    CSS_PATH = "app.tcss"
    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]

    def __init__(self) -> None:
        # call super
        super().__init__()

        # dynamically enable dark mode or light mode
        self.dark = detect_terminal_background().dark

        # enable rich hooks
        rich_initialise()

    def compose(self) -> ComposeResult:
        yield Header(classes="header")
        yield Footer()

    def action_toggle_dark(self) -> None:
        self.dark = not self.dark
