from typing import cast

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widgets import Link, Static

from inspect_ai.util import InputPanel
from inspect_ai.util._sandbox.environment import SandboxConnection


class HumanUserPanel(InputPanel):
    connection: reactive[SandboxConnection | None] = reactive(None)

    def compose(self) -> ComposeResult:
        yield Link(
            "Go to textualize.io",
            url="https://textualize.io",
            tooltip="Click me",
        )
        yield Static(id="sandbox-connection")

    def watch_connection(self, new_value: SandboxConnection | None) -> None:
        ui = cast(Static, self.query_one("#sandbox-connection"))
        ui.update(new_value.command if new_value else "")
