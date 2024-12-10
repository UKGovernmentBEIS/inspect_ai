from typing import cast

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widgets import Button, Link, Static

from inspect_ai._util.vscode import (
    VSCodeCommand,
    execute_vscode_commands,
)
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
        yield Button(
            "Open VS Code",
            id="open-vscode",
        )
        yield Static(id="sandbox-connection")

    def watch_connection(self, new_value: SandboxConnection | None) -> None:
        ui = cast(Static, self.query_one("#sandbox-connection"))
        ui.update(new_value.command if new_value else "")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if self.connection:
            if event.button.id == "open-terminal":
                execute_vscode_commands(
                    [
                        VSCodeCommand(command="workbench.action.terminal.new"),
                        VSCodeCommand(
                            command="workbench.action.terminal.sendSequence",
                            args=[{"text": f"{self.connection.command}\n"}],
                        ),
                    ]
                )
            elif event.button.id == "open-vscode" and self.connection.vscode_command:
                execute_vscode_commands(
                    VSCodeCommand(
                        command=self.connection.vscode_command[0],
                        args=self.connection.vscode_command[1:],
                    )
                )
