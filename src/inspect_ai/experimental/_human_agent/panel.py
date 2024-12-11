from typing import cast

from textual.app import ComposeResult
from textual.containers import (
    Container,
    Horizontal,
    ScrollableContainer,
)
from textual.reactive import reactive
from textual.widgets import (
    Button,
    ContentSwitcher,
    Label,
    Link,
    LoadingIndicator,
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
    SANDBOX_CONNECTION_ID = "sandbox-connection"
    SANDBOX_INSTRUCTIONS_ID = "sandbox-instructions"
    LOGIN_VSCODE_TERMINAL_ID = "login-vscode-terminal"
    LOGIN_VSCODE_WINDOW_ID = "login-vscode-window"

    DEFAULT_CSS = f"""
    #{SANDBOX_VIEW_ID} {{
    }}
    #{SANDBOX_CONNECTION_ID} {{
        margin-top: 1;
        margin-bottom: 1;
        color: $secondary;
    }}
    HumanAgentPanel VSCodeLink {{
        margin-left: 1;
        margin-right: 2;
    }}
    """

    connection: reactive[SandboxConnection | None] = reactive(None)

    async def show_cmd(self, cmd: str) -> None:
        pass

    def compose(self) -> ComposeResult:
        with ContentSwitcher(initial=LoadingView.ID):
            yield LoadingView()
            with ScrollableContainer(id=self.SANDBOX_VIEW_ID):
                yield Static(id=self.SANDBOX_INSTRUCTIONS_ID)
                yield Static(id=self.SANDBOX_CONNECTION_ID)
                with Horizontal():
                    yield Label("Login:")
                    yield VSCodeLink(
                        "VS Code Terminal",
                        id=self.LOGIN_VSCODE_TERMINAL_ID,
                    )
                    yield Label("Login:")
                    yield VSCodeLink(
                        "VS Code Window",
                        id=self.LOGIN_VSCODE_WINDOW_ID,
                    )

    def watch_connection(self, connection: SandboxConnection | None) -> None:
        if connection:
            # switch to sandbox view
            self.query_one(ContentSwitcher).current = self.SANDBOX_VIEW_ID

            # note whether we are in vscode
            vscode = can_execute_vscode_commands()

            # update instructions
            instructions_lbl = cast(
                Static, self.query_one(f"#{self.SANDBOX_INSTRUCTIONS_ID}")
            )
            instructions = f"""You are completing a computing task on a Linux system (task instructions will be presented when you login). Login to the system with the following command{' (or use the links below to access the system within VS Code)' if vscode else ''}:"""
            instructions_lbl.update(instructions)

            # connection command
            connection_lbl = cast(
                Static, self.query_one(f"#{self.SANDBOX_CONNECTION_ID}")
            )
            connection_lbl.update(connection.command)

            terminal_btn = cast(
                VSCodeLink, self.query_one(f"#{self.LOGIN_VSCODE_TERMINAL_ID}")
            )
            terminal_btn.display = vscode
            terminal_btn.commands = [
                VSCodeCommand(command="workbench.action.terminal.new"),
                VSCodeCommand(
                    command="workbench.action.terminal.sendSequence",
                    args=[{"text": f"{connection.command}\n"}],
                ),
            ]

            window_btn = cast(
                VSCodeLink, self.query_one(f"#{self.LOGIN_VSCODE_WINDOW_ID}")
            )
            if connection.vscode_command is not None:
                window_btn.display = vscode
                window_btn.commands = [
                    VSCodeCommand(
                        command=connection.vscode_command[0],
                        args=connection.vscode_command[1:],
                    )
                ]
            else:
                window_btn.display = False


class LoadingView(Container):
    ID = "human-agent-loading-view"

    def __init__(self) -> None:
        super().__init__(id=self.ID)

    def compose(self) -> ComposeResult:
        yield LoadingIndicator()
        yield Button()  # add focusable widget so the tab can activate


class VSCodeLink(Link):
    def __init__(
        self,
        text: str,
        *,
        url: str | None = None,
        tooltip: str | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            text,
            url=url,
            tooltip=tooltip,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
        )
        self.commands: list[VSCodeCommand] = []

    def on_click(self) -> None:
        execute_vscode_commands(self.commands)
