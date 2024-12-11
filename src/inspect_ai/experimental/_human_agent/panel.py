from typing import cast

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Button,
    ContentSwitcher,
    Link,
    LoadingIndicator,
    RichLog,
    Static,
)

from inspect_ai._util.vscode import (
    VSCodeCommand,
    can_execute_vscode_commands,
    execute_vscode_commands,
)
from inspect_ai.util import InputPanel
from inspect_ai.util._sandbox.environment import SandboxConnection


class HumanAgentPanel(InputPanel):
    DEFAULT_TITLE = "Human Agent"

    SANDBOX_VIEW_ID = "human-agent-sandbox-view"

    DEFAULT_CSS = f"""
    #{SANDBOX_VIEW_ID} {{
        layout: grid;
        grid-size: 2 1;
    }}
    """

    connection: reactive[SandboxConnection | None] = reactive(None)

    async def show_cmd(self, cmd: str) -> None:
        self.query_one(RichLog).write(cmd)

    def compose(self) -> ComposeResult:
        with ContentSwitcher(initial=LoadingView.ID):
            yield LoadingView()
            with Container(id=self.SANDBOX_VIEW_ID):
                with Vertical():
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
                with Vertical():
                    yield RichLog()

    def watch_connection(self, connection: SandboxConnection | None) -> None:
        if connection:
            self.query_one(ContentSwitcher).current = self.SANDBOX_VIEW_ID
            # get references to ui
            connection_lbl = cast(Static, self.query_one("#sandbox-connection"))
            terminal_btn = self.query_one("#open-terminal")
            vscode_btn = self.query_one("#open-vscode")

            connection_lbl.update(connection.command)
            terminal_btn.display = can_execute_vscode_commands()
            vscode_btn.display = (
                can_execute_vscode_commands() and connection.vscode_command is not None
            )

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


class LoadingView(Container):
    ID = "human-agent-loading-view"

    def __init__(self) -> None:
        super().__init__(id=self.ID)

    def compose(self) -> ComposeResult:
        yield LoadingIndicator()
        yield Button()  # add focusable widget so the tab can activate
