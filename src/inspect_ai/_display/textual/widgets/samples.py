from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import OptionList, Static


class SamplesView(Widget):
    DEFAULT_CSS = """
    SamplesView {
        width: 1fr;
        height: 1fr;
        padding: 0 1 0 1;
        layout: grid;
        grid-size: 2 1;
        grid-columns: 30 1fr;
    }
    SamplesView OptionList {
        height: 100%;
        scrollbar-size-vertical: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()

    def compose(self) -> ComposeResult:
        yield OptionList(
            "Aerilon",
            "Aquaria",
            "Canceron",
            "Caprica",
            "Gemenon",
            "Leonis",
            "Libran",
            "Picon",
            "Sagittaron",
            "Scorpia",
            "Tauron",
            "Virgon",
            "Aerilon",
            "Aquaria",
            "Canceron",
            "Caprica",
            "Gemenon",
            "Leonis",
            "Libran",
            "Picon",
            "Sagittaron",
            "Scorpia",
            "Tauron",
            "Virgon",
        )
        yield Static("Foobar")
