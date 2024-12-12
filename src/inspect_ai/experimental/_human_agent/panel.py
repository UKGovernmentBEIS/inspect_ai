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

from inspect_ai._util.throttle import throttle
from inspect_ai._util.vscode import (
    VSCodeCommand,
    can_execute_vscode_commands,
    execute_vscode_commands,
)
from inspect_ai.util import InputPanel
from inspect_ai.util._sandbox.environment import SandboxConnection

from .state import HumanAgentState


class HumanAgentPanel(InputPanel):
    DEFAULT_TITLE = "Human Agent"

    SANDBOX_VIEW_ID = "human-agent-sandbox-view"
    SANDBOX_CONNECTION_ID = "sandbox-connection"
    SANDBOX_INSTRUCTIONS_ID = "sandbox-instructions"
    VSCODE_INSTRUCTIONS_ID = "vscode-instructions"
    LOGIN_VSCODE_TERMINAL_ID = "login-vscode-terminal"
    LOGIN_VSCODE_WINDOW_ID = "login-vscode-window"

    INSTRUCTIONS_CLASS = "instructions"
    LINK_LABEL_CLASS = "link-label"

    DEFAULT_CSS = f"""
    #{SANDBOX_VIEW_ID} {{
        scrollbar-size-vertical: 1;
    }}
    HumanAgentPanel .{INSTRUCTIONS_CLASS} {{
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

    @throttle(1)
    def update_state(self, state: HumanAgentState) -> None:
        status_bar = self.query_one(StatusBar)
        status_bar.running = state.running
        status_bar.time = state.time

    def compose(self) -> ComposeResult:
        with ContentSwitcher(initial=LoadingView.ID):
            yield LoadingView()
            with ScrollableContainer(id=self.SANDBOX_VIEW_ID):
                yield StatusBar()
                yield Static(
                    id=self.SANDBOX_INSTRUCTIONS_ID, classes=self.INSTRUCTIONS_CLASS
                )
                yield Static(id=self.SANDBOX_CONNECTION_ID)
                yield Static(
                    id=self.VSCODE_INSTRUCTIONS_ID, classes=self.INSTRUCTIONS_CLASS
                )
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
            instructions = """You are completing a task on a Linux system (task instructions will be presented when you login). Login to the system with the following command. Hold down Alt (or Option) to select text for copying:"""
            instructions_lbl.update(instructions)

            # connection command (always available)
            connection_lbl = cast(
                Static, self.query_one(f"#{self.SANDBOX_CONNECTION_ID}")
            )
            connection_lbl.update(connection.command)

            # vscode instructions
            vscode_instructions_lbl = cast(
                Static, self.query_one(f"#{self.VSCODE_INSTRUCTIONS_ID}")
            )
            vscode_instructions_lbl.display = vscode
            vscode_instructions_lbl.update(
                "Alternatively, login to the system within VS Code:"
            )

            # login: vscode terminanl
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

            # login: vscode window
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

    running: reactive[bool] = reactive(True)
    time: reactive[float] = reactive(0)

    def __init__(self) -> None:
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Label("Status:", classes=self.LABEL_CLASS)
        yield Static("Started", id=self.STATUS_ID, classes=self.VALUE_CLASS)
        yield Label(" Time:", classes=self.LABEL_CLASS)
        yield Static("0:00:00", id=self.TIME_ID, classes=self.VALUE_CLASS)
        # yield Static("  ⏸")  # ▶️
        yield Link("Help")

    def watch_running(self, running: bool) -> None:
        cast(Static, self.query_one(f"#{self.STATUS_ID}")).update(
            "Started" if running else "Stopped"
        )

    def watch_time(self, time: float) -> None:
        minutes, seconds = divmod(self.time, 60)
        hours, minutes = divmod(minutes, 60)
        time_display = f"{hours:.0f}:{minutes:02.0f}:{seconds:02.0f}"
        cast(Static, self.query_one(f"#{self.TIME_ID}")).update(time_display)


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
