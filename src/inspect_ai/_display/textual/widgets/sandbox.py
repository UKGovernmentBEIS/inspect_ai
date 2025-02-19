from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from inspect_ai.util._sandbox.environment import SandboxConnection

from .port_mappings import PortMappingsView


class SandboxView(Vertical):
    DEFAULT_CSS = """
    SandboxView {
        height: auto;
    }
    SandboxView * {
        height: auto;
    }
    .indent {
        width: 2;
    }
    .no_indent {
        width: 0;
    }
    """

    def __init__(
        self,
        connection: SandboxConnection,
        name: str | None,  # if None, no header or indent
    ) -> None:
        super().__init__()
        self.sandbox_name = name
        self.connection = connection

    def compose(self) -> ComposeResult:
        if self.sandbox_name:
            yield Static(self.sandbox_name)
        with Horizontal():
            yield Static("", classes="indent" if self.sandbox_name else "no_indent")
            with Vertical():
                yield Static(self.connection.command, markup=False)
                if self.connection.ports:
                    yield PortMappingsView(self.connection.ports)
