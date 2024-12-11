from typing import Literal, cast

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

    LINK_LABEL_CLASS = "link-label"

    DEFAULT_CSS = f"""
    #{SANDBOX_VIEW_ID} {{
        scrollbar-size-vertical: 1;
    }}
    #{SANDBOX_INSTRUCTIONS_ID} {{
        color: $text-muted;
        margin-bottom: 1;
    }}
    #{SANDBOX_CONNECTION_ID} {{
        margin-top: 1;
        margin-bottom: 1;
        color: $secondary;
    }}
    HumanAgentPanel .{LINK_LABEL_CLASS} {{
        color: $text-muted;
    }}
    HumanAgentPanel VSCodeLink {{
        margin-left: 1;
        margin-right: 2;
    }}
    """

    connection: reactive[SandboxConnection | None] = reactive(None)

    def start_task(self) -> None:
        status_bar = self.query_one(StatusBar)
        status_bar.status = "Started"

    def stop_task(self) -> None:
        status_bar = self.query_one(StatusBar)
        status_bar.status = "Stopped"

    def compose(self) -> ComposeResult:
        with ContentSwitcher(initial=LoadingView.ID):
            yield LoadingView()
            with ScrollableContainer(id=self.SANDBOX_VIEW_ID):
                yield StatusBar()
                yield Static(id=self.SANDBOX_INSTRUCTIONS_ID)
                yield Static(id=self.SANDBOX_CONNECTION_ID)
                with Horizontal():
                    yield Label("Login:", classes=self.LINK_LABEL_CLASS)
                    yield VSCodeLink(
                        "VS Code Terminal",
                        id=self.LOGIN_VSCODE_TERMINAL_ID,
                    )
                    yield Label("Login:", classes=self.LINK_LABEL_CLASS)
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
            instructions = f"""You are completing a task on a Linux system (task instructions will be presented when you login). Login to the system with the following command{' (or use the links below to access the system within VS Code)' if vscode else ''}:"""
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
                VSCodeCommand(
                    command="workbench.action.terminal.new", args=[{"location": 2}]
                ),
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


class StatusBar(Horizontal):
    STATUS_ID = "task-status"
    TIME_ID = "task-time"

    LABEL_CLASS = "status-label"
    VALUE_CLASS = "status-value"

    DEFAULT_CSS = f"""
    StatusBar {{
        width: 1fr;
        height: 1;
        background: $surface;
        margin-bottom: 1;
        layout: grid;
        grid-size: 6 1;
        grid-columns: auto auto auto auto 1fr;
        grid-gutter: 1;
    }}
    .{LABEL_CLASS} {{
        color: $primary;
    }}
    .{VALUE_CLASS} {{
        color: $foreground;
    }}
    StatusBar Link {{
        dock: right;
        margin-right: 1;
    }}
    """

    status: reactive[Literal["Started", "Stopped"]] = reactive("Started")

    def __init__(self) -> None:
        super().__init__()
        self.time: float = 0
        self.timer = self.app.set_interval(1, self.on_tick)

    def compose(self) -> ComposeResult:
        yield Label("Status:", classes=self.LABEL_CLASS)
        yield Static("Started", id=self.STATUS_ID, classes=self.VALUE_CLASS)
        yield Label(" Time:", classes=self.LABEL_CLASS)
        yield Static("0:00:00", id=self.TIME_ID, classes=self.VALUE_CLASS)
        # yield Static("  ⏸")  # ▶️
        yield Link("Help")

    def on_tick(self) -> None:
        if self.status == "Started":
            self.time = self.time + 1
            minutes, seconds = divmod(self.time, 60)
            hours, minutes = divmod(minutes, 60)
            time_display = f"{hours:.0f}:{minutes:02.0f}:{seconds:02.0f}"
            cast(Static, self.query_one(f"#{self.TIME_ID}")).update(time_display)

    def on_unmount(self) -> None:
        self.timer.stop()

    def watch_status(self, status: str) -> None:
        cast(Static, self.query_one(f"#{self.STATUS_ID}")).update(status)


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
