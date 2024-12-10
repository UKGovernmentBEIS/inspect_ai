from typing import cast

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widgets import Button, Link, Static

from inspect_ai._util.vscode import execute_vscode_command
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
        yield Button(
            "Open Terminal",
            id="open-terminal",
        )
        yield Static(id="sandbox-connection")

    def watch_connection(self, new_value: SandboxConnection | None) -> None:
        ui = cast(Static, self.query_one("#sandbox-connection"))
        ui.update(new_value.command if new_value else "")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open-terminal" and self.connection:
            execute_vscode_command(
                "workbench.action.terminal.new",
                [{"shellArgs": ["-c", self.connection.command]}],
            )
