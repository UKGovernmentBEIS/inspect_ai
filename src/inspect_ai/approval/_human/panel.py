from textual.app import ComposeResult
from textual.widgets import Static
from typing_extensions import override

from inspect_ai._display.core.input import InputPanel


class ApprovalInputPanel(InputPanel):
    @override
    def compose(self) -> ComposeResult:
        yield Static("Approval")

    @override
    def update(self) -> None:
        pass
