from textual.containers import Container
from textual.widgets import Static


class SamplesView(Container):
    def __init__(self) -> None:
        super().__init__(Static("Samples"))
