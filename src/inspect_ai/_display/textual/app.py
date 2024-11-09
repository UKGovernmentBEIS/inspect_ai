from textual.app import App, ComposeResult
from textual.events import Unmount
from textual.message import Message
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
        rich_initialise(self.dark)

    def compose(self) -> ComposeResult:
        yield Header(classes="header")
        yield Footer()

    def action_toggle_dark(self) -> None:
        self.dark = not self.dark

    # filter Unmount event so it doesn't clutter up the log
    async def _on_message(self, message: Message) -> None:
        if isinstance(message, Unmount):
            pass
        else:
            await super()._on_message(message)
