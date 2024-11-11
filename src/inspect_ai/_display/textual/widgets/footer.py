from textual.widgets import Footer


class TaskScreenFooter(Footer):
    def __init__(self) -> None:
        super().__init__(show_command_palette=False)
