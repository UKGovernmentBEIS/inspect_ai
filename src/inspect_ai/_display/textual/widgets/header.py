from typing import Iterable

from textual.widget import Widget
from textual.widgets import Header
from textual.widgets._header import HeaderTitle


class TaskScreenHeader(Header):
    def compose(self) -> Iterable[Widget]:
        yield HeaderTitle()
