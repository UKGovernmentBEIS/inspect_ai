from textual.events import Print
from textual.widgets import RichLog


class Log(RichLog):
    def __init__(self) -> None:
        return super().__init__()

    def on_print(self, event: Print) -> None:
        text = event.text
        if text.endswith("\n"):
            text = text[:-1]
        self.write(text, expand=True)
