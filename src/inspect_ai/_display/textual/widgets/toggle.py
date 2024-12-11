from textual.events import Click
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static


class Toggle(Static, can_focus=True):
    toggled = reactive(True)

    def __init__(
        self, on_symbol: str = "▼", off_symbol: str = "▶", toggled: bool = False
    ) -> None:
        super().__init__()

        self.on_symbol = on_symbol
        self.off_symbol = off_symbol
        self.toggled = toggled

    class Toggled(Message):
        """Request toggle."""

    async def _on_click(self, event: Click) -> None:
        """Inform ancestor we want to toggle."""
        event.stop()
        self.toggled = not self.toggled
        self.post_message(self.Toggled())

    def _watch_toggled(self, toggled: bool) -> None:
        if toggled:
            self.update(self.on_symbol)
        else:
            self.update(self.off_symbol)
