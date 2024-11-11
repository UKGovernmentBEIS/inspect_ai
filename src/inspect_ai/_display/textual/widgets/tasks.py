from textual.containers import ScrollableContainer
from textual.widgets import Static


class TasksView(ScrollableContainer):
    def __init__(self) -> None:
        super().__init__(Static("Tasks"))
