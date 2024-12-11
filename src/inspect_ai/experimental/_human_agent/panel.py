from typing import cast

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widgets import Button, Link, Static

from inspect_ai._util.vscode import (
    VSCodeCommand,
    can_execute_vscode_commands,
    execute_vscode_commands,
)
from inspect_ai.util import InputPanel
from inspect_ai.util._sandbox.environment import SandboxConnection


class HumanAgentPanel(InputPanel):
    DEFAULT_TITLE = "Human Agent"

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

    def watch_connection(self, connection: SandboxConnection | None) -> None:
        # get references to ui
        connection_lbl = cast(Static, self.query_one("#sandbox-connection"))
        terminal_btn = self.query_one("#open-terminal")
        vscode_btn = self.query_one("#open-vscode")

        # populate for connection
        if connection is not None:
            connection_lbl.update(connection.command)
            terminal_btn.display = can_execute_vscode_commands()
            vscode_btn.display = (
                can_execute_vscode_commands() and connection.vscode_command is not None
            )
        # hide for no connection
        else:
            connection_lbl.update("")
            terminal_btn.display = False
            vscode_btn.display = False

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
