from typing import cast

from textual.app import ComposeResult
from textual.containers import (
    Container,
    Horizontal,
    VerticalScroll,
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

from inspect_ai._util.format import format_progress_time
from inspect_ai._util.vscode import (
    VSCodeCommand,
    can_execute_vscode_commands,
    execute_vscode_commands,
)
from inspect_ai.util import InputPanel, SandboxConnection, throttle

from .state import HumanAgentState


class HumanAgentPanel(InputPanel):
    DEFAULT_TITLE = "Human Agent"

    SANDBOX_VIEW_ID = "human-agent-sandbox-view"
    SANDBOX_INSTRUCTIONS_ID = "sandbox-instructions"
    VSCODE_LINKS_ID = "vscode-links"
    LOGIN_VSCODE_TERMINAL_ID = "login-vscode-terminal"
    LOGIN_VSCODE_WINDOW_ID = "login-vscode-window"
    LOGIN_VSCODE_WINDOW_LABEL_ID = "login-vscode-window-label"
    COMMAND_INSTRUCTIONS_ID = "command-instructions"
    SANDBOX_COMMAND_ID = "sandbox-command"

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
    #{SANDBOX_COMMAND_ID} {{
        color: $secondary;
    }}
    HumanAgentPanel .{LINK_LABEL_CLASS} {{
        color: $text-muted;
    }}
    HumanAgentPanel VSCodeLink {{
        margin-left: 1;
        margin-right: 2;
    }}
    HumanAgentPanel #{VSCODE_LINKS_ID} {{
        height: 1;
        margin-bottom: 1;
    }}
    """

    connection: reactive[SandboxConnection | None] = reactive(None)

    # implement HumanAgentView
    def connect(self, connection: SandboxConnection) -> None:
        self.connection = connection

    @throttle(1)
    def update_state(self, state: HumanAgentState) -> None:
        status_bar = self.query_one(StatusBar)
        status_bar.running = state.running
        status_bar.time = state.time

    def compose(self) -> ComposeResult:
        with ContentSwitcher(initial=LoadingView.ID):
            yield LoadingView()
            with VerticalScroll(id=self.SANDBOX_VIEW_ID):
                yield StatusBar()
                yield Static(
                    id=self.SANDBOX_INSTRUCTIONS_ID,
                    classes=self.INSTRUCTIONS_CLASS,
                    markup=False,
                )
                with Horizontal(id=self.VSCODE_LINKS_ID):
                    yield Label(
                        "Login:",
                        classes=self.LINK_LABEL_CLASS,
                        id=self.LOGIN_VSCODE_WINDOW_LABEL_ID,
                    )
                    yield VSCodeLink(
                        "VS Code Window",
                        id=self.LOGIN_VSCODE_WINDOW_ID,
                    )
                    yield Label("Login:", classes=self.LINK_LABEL_CLASS)
                    yield VSCodeLink(
                        "VS Code Terminal",
                        id=self.LOGIN_VSCODE_TERMINAL_ID,
                    )
                yield Static(
                    id=self.COMMAND_INSTRUCTIONS_ID,
                    classes=self.INSTRUCTIONS_CLASS,
                    markup=False,
                )
                yield Static(id=self.SANDBOX_COMMAND_ID, markup=False)

    def watch_connection(self, connection: SandboxConnection | None) -> None:
        if connection:
            # switch to sandbox view
            self.query_one(ContentSwitcher).current = self.SANDBOX_VIEW_ID

            # note whether we are in vscode
            vscode = can_execute_vscode_commands()

            # suffix for instructions based on whether we are in vscode
            instructions_command = "Login to the system with the following command (hold down Alt or Option to select text for copying):"
            instructions_vscode = (
                "Use the links below to login to the system within VS Code:"
            )

            # update instructions
            instructions_lbl = cast(
                Static, self.query_one(f"#{self.SANDBOX_INSTRUCTIONS_ID}")
            )
            instructions = f"""You are completing a task on a Linux system (task instructions will be presented when you login). {instructions_vscode if vscode else instructions_command}"""
            instructions_lbl.update(instructions)

            # login: vscode terminal
            vscode_links = self.query_one(f"#{self.VSCODE_LINKS_ID}")
            vscode_links.display = vscode
            terminal_btn = cast(
                VSCodeLink, self.query_one(f"#{self.LOGIN_VSCODE_TERMINAL_ID}")
            )
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
            window_lbl = cast(
                Label, self.query_one(f"#{self.LOGIN_VSCODE_WINDOW_LABEL_ID}")
            )
            window_btn_and_lbl_display = (
                vscode and connection.vscode_command is not None
            )
            window_btn.display = window_btn_and_lbl_display
            window_lbl.display = window_btn_and_lbl_display
            if connection.vscode_command is not None:
                window_btn.commands = [
                    VSCodeCommand(
                        command=connection.vscode_command[0],
                        args=connection.vscode_command[1:],
                    )
                ]

            # command (always available)
            command_instructions_lbl = cast(
                Static, self.query_one(f"#{self.COMMAND_INSTRUCTIONS_ID}")
            )
            command_instructions_lbl.display = vscode
            command_instructions_lbl.update(
                instructions_command.replace("Login", "Alternatively, login", 1)
            )
            command_lbl = cast(Static, self.query_one(f"#{self.SANDBOX_COMMAND_ID}"))
            command_lbl.update(connection.command)


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
        grid-size: 4 1;
        grid-columns: auto auto auto auto;
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
        yield Static(
            "Running", id=self.STATUS_ID, classes=self.VALUE_CLASS, markup=False
        )
        yield Label(" Time:", classes=self.LABEL_CLASS)
        yield Static("0:00:00", id=self.TIME_ID, classes=self.VALUE_CLASS, markup=False)

    def watch_running(self, running: bool) -> None:
        cast(Static, self.query_one(f"#{self.STATUS_ID}")).update(
            "Running" if running else "Stopped"
        )

    def watch_time(self, time: float) -> None:
        time_display = format_progress_time(time)
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
