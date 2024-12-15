from asyncio import CancelledError
from typing import Callable, Literal

from rich.console import RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer
from textual.reactive import reactive
from textual.widgets import Button, Static
from typing_extensions import override

from inspect_ai._util.registry import registry_unqualified_name
from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
from inspect_ai.util._panel import InputPanel, input_panel

from .._approval import Approval, ApprovalDecision
from .manager import ApprovalRequest, PendingApprovalRequest, human_approval_manager
from .util import (
    HUMAN_APPROVED,
    HUMAN_ESCALATED,
    HUMAN_REJECTED,
    HUMAN_TERMINATED,
    render_tool_approval,
)

PANEL_TITLE = "Approvals"


async def panel_approval(
    message: str,
    call: ToolCall,
    view: ToolCallView,
    state: TaskState | None,
    choices: list[ApprovalDecision],
) -> Approval:
    # ensure the approvals panel is shown
    await input_panel(PANEL_TITLE, ApprovalInputPanel)

    # submit to human approval manager (will be picked up by panel)
    approvals = human_approval_manager()
    id = approvals.request_approval(
        ApprovalRequest(
            message=message, call=call, view=view, state=state, choices=choices
        )
    )
    try:
        return await approvals.wait_for_approval(id)
    except CancelledError:
        approvals.withdraw_request(id)
        raise


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
        yield ApprovalRequestActions()

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
        actions = self.query_one(ApprovalRequestActions)
        self._approvals = human_approval_manager().approval_requests()
        if len(self._approvals) > 0:
            approval_id, approval_request = self._approvals[0]
            self.title = f"{PANEL_TITLE} ({len(self._approvals):,})"
            heading.request = approval_request
            content.approval = approval_request.request
            actions.approval_request = approval_id, approval_request
            if action == "add":
                self.activate()
                actions.activate()
            self.visible = True
        else:
            self.title = PANEL_TITLE
            heading.request = None
            content.approval = None
            actions.approval_request = None
            self.deactivate()
            self.visible = False


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
        padding: 0 1 0 1;
    }
    """

    approval: reactive[ApprovalRequest | None] = reactive(None)

    async def watch_approval(self, approval: ApprovalRequest | None) -> None:
        await self.remove_children()
        if approval:
            self.mount_all(
                Static(r) for r in render_tool_approval(approval.message, approval.view)
            )
            self.scroll_end(animate=False)


class ApprovalRequestActions(Horizontal):
    APPROVE_TOOL_CALL = "approve-tool-call"
    REJECT_TOOL_CALL = "reject-tool-call"
    ESCALATE_TOOL_CALL = "escalate-tool-call"
    TERMINATE_TOOL_CALL_SAMPLE = "terminate-tool-call-sample"

    DEFAULT_CSS = f"""
    ApprovalRequestActions Button {{
        margin-right: 1;
        min-width: 20;
    }}
    ApprovalRequestActions #{APPROVE_TOOL_CALL} {{
        color: $success;
    }}
    ApprovalRequestActions #{REJECT_TOOL_CALL} {{
        color: $warning-darken-3;
    }}
    ApprovalRequestActions #{ESCALATE_TOOL_CALL} {{
        color: $primary-darken-3;
        margin-left: 3;
    }}
    ApprovalRequestActions #{TERMINATE_TOOL_CALL_SAMPLE} {{
        color: $error-darken-1;
        margin-left: 3;
    }}
    """

    approval_request: reactive[tuple[str, PendingApprovalRequest] | None] = reactive(
        None
    )

    def compose(self) -> ComposeResult:
        yield Button(
            Text("Approve"),
            id=self.APPROVE_TOOL_CALL,
            tooltip="Approve the tool call.",
        )
        yield Button(
            Text("Reject"),
            id=self.REJECT_TOOL_CALL,
            tooltip="Reject the tool call.",
        )
        yield Button(
            Text("Escalate"),
            id=self.ESCALATE_TOOL_CALL,
            tooltip="Escalate the tool call to another approver.",
        )
        yield Button(
            Text("Terminate"),
            id=self.TERMINATE_TOOL_CALL_SAMPLE,
            tooltip="Terminate the sample.",
        )

    def activate(self) -> None:
        approve = self.query_one(f"#{self.APPROVE_TOOL_CALL}")
        approve.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if self.approval_request is not None:
            id, _ = self.approval_request
            if event.button.id == self.APPROVE_TOOL_CALL:
                approval = Approval(decision="approve", explanation=HUMAN_APPROVED)
            elif event.button.id == self.REJECT_TOOL_CALL:
                approval = Approval(decision="reject", explanation=HUMAN_REJECTED)
            elif event.button.id == self.ESCALATE_TOOL_CALL:
                approval = Approval(decision="escalate", explanation=HUMAN_ESCALATED)
            elif event.button.id == self.TERMINATE_TOOL_CALL_SAMPLE:
                approval = Approval(decision="terminate", explanation=HUMAN_TERMINATED)
            else:
                raise ValueError(f"Unexpected button id: {event.button.id}")
            human_approval_manager().complete_approval(id, approval)

    def watch_approval_request(
        self, approval_request: tuple[str, PendingApprovalRequest] | None
    ) -> None:
        choices = (
            approval_request[1].request.choices if approval_request is not None else []
        )

        def update_visible(id: str, choice: ApprovalDecision) -> None:
            self.query_one(f"#{id}").display = choice in choices

        update_visible(self.APPROVE_TOOL_CALL, "approve")
        update_visible(self.REJECT_TOOL_CALL, "reject")
        update_visible(self.ESCALATE_TOOL_CALL, "escalate")
        update_visible(self.TERMINATE_TOOL_CALL_SAMPLE, "terminate")
