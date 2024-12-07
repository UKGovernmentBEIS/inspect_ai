from typing import Callable, Literal

from rich.console import Group, RenderableType
from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.reactive import reactive
from textual.widgets import Static
from typing_extensions import override

from inspect_ai._display.core.input import InputPanel
from inspect_ai._util.registry import registry_unqualified_name
from inspect_ai.approval._human.util import render_tool_approval
from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall, ToolCallView

from .._approval import Approval, ApprovalDecision
from .manager import ApprovalRequest, PendingApprovalRequest, human_approval_manager

PANEL_TITLE = "Approvals"


async def panel_approval(
    message: str,
    call: ToolCall,
    view: ToolCallView,
    state: TaskState | None,
    choices: list[ApprovalDecision],
) -> Approval:
    from inspect_ai._display.core.active import task_screen

    # ensure the approvals panel is shown
    task_screen().input_panel(PANEL_TITLE, ApprovalInputPanel)

    # submit to human approval manager (will be picked up by panel)
    return await human_approval_manager().approve(
        ApprovalRequest(
            message=message, call=call, view=view, state=state, choices=choices
        )
    )


class ApprovalInputPanel(InputPanel):
    DEFAULT_CSS = """
    ApprovalInputPanel {
        width: 1fr;
        height: 1fr;
        padding: 0 1 1 1;
        layout: grid;
        grid-size: 1 3;
        grid-rows: auto 1fr auto;
    }
    """

    _approvals: list[tuple[str, PendingApprovalRequest]] = []
    _unsubscribe: Callable[[], None] | None = None

    @override
    def compose(self) -> ComposeResult:
        yield ApprovalRequestHeading()
        yield ApprovalRequestContent()
        yield Static("Approval Toolbar")

    def on_mount(self) -> None:
        self._unsubscribe = human_approval_manager().on_change(
            self.on_approvals_changed
        )

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()

    def on_approvals_changed(self, action: Literal["add", "remove"]) -> None:
        heading = self.query_one(ApprovalRequestHeading)
        content = self.query_one(ApprovalRequestContent)
        self._approvals = human_approval_manager().approval_requests()
        if len(self._approvals) > 0:
            approval_request = self._approvals[0][1]
            self.set_title(f"{PANEL_TITLE} ({len(self._approvals):,})")
            heading.request = approval_request
            content.approval = approval_request.request
            if action == "add":
                self.activate()
        else:
            self.set_title(PANEL_TITLE)
            heading.request = None
            content.approval = None
            self.deactivate()


class ApprovalRequestHeading(Static):
    DEFAULT_CSS = """
    ApprovalRequestHeading {
        width: 1fr;
        background: $surface;
        color: $secondary;
        margin-left: 1;
    }
    """

    request: reactive[PendingApprovalRequest | None] = reactive(None)

    def render(self) -> RenderableType:
        if self.request is not None:
            return f"{registry_unqualified_name(self.request.task)} (id: {self.request.id}, epoch {self.request.epoch}): {self.request.model}"
        else:
            return ""


class ApprovalRequestContent(ScrollableContainer):
    DEFAULT_CSS = """
    ApprovalRequestContent {
        scrollbar-size-vertical: 1;
        scrollbar-gutter: stable;
        border: solid $foreground 20%;
    }
    """

    approval: reactive[ApprovalRequest | None] = reactive(None)

    def compose(self) -> ComposeResult:
        yield Static()

    def watch_approval(self, approval: ApprovalRequest | None) -> None:
        content = self.query_one(Static)
        if approval:
            content.update(
                Group(*render_tool_approval(approval.message, approval.view))
            )
            self.scroll_end(animate=False)
        else:
            content.update("No approvals pending.")
