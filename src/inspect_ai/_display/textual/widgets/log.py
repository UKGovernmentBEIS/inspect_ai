from rich.text import Text
from textual.widgets import RichLog


class LogView(RichLog):
    def __init__(self) -> None:
        return super().__init__()

    def write_ansi(self, text: str) -> None:
        # process line by line
        for line in text.splitlines():
            self.write_ansi_line(line)

    def write_ansi_line(self, line: str) -> None:
        # tweak rich console lines with path at end to not go under the scrollbar
        # (remove two inner spaces and add a space at the end)
        if "2m1786" in line:
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
