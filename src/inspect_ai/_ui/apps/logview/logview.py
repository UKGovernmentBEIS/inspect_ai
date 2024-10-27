from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer
from textual.widgets import Button, Footer, Header

# textual console
# textual run --dev inspect_ai._ui.apps.logview.logview:LogviewApp


class LogviewApp(App[None]):
    CSS_PATH = "logview.tcss"
    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]

    def compose(self) -> ComposeResult:
        yield Header(classes="header")
        yield Footer()
        yield ScrollableContainer(Button(label="Do It", variant="success"))

    def action_toggle_dark(self) -> None:
        self.dark = not self.dark


if __name__ == "__main__":
    app = LogviewApp()
    app.run()
