from rich.text import Text
from textual.reactive import reactive
from textual.widgets import RichLog


class ConsoleView(RichLog):
    DEFAULT_CSS = """
    ConsoleView {
        scrollbar-size-horizontal: 1;
        scrollbar-size-vertical: 1;
        scrollbar-gutter: stable;
        background: transparent;
    }
    """

    # enable tab container to print our unread count
    unread: reactive[int | None] = reactive(None)

    def __init__(self) -> None:
        super().__init__()
        self.active = False
        self.show_horizontal_scrollbar = False

    async def notify_active(self, active: bool) -> None:
        self.active = active
        if self.active:
            self.unread = None

    def write_ansi(self, text: str) -> None:
        # process line by line
        for line in text.splitlines():
            self.write_ansi_line(line)

        # tick unread if we aren't active
        if not self.active and len(text.strip()) > 0:
            self.unread = (self.unread or 0) + 1

    def write_ansi_line(self, line: str) -> None:
        # tweak rich console lines with path at end to not go under the scrollbar
        # (remove two inner spaces and add a space at the end)
        if "[2m" in line:
            chars = list(line)
            removed = 0
            for i in range(len(chars) - 1, -1, -1):
                if chars[i].isspace():
                    chars.pop(i)
                    removed += 1
                    if removed > 1:
                        break
            line = "".join(chars) + " "

        self.write(Text.from_ansi(line))
