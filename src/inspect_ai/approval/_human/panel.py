from typing import Callable

from textual.app import ComposeResult
from textual.widgets import Static
from typing_extensions import override

from inspect_ai._display.core.input import InputPanel
from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall, ToolCallView

from .._approval import Approval, ApprovalDecision
from .manager import ApprovalRequest, human_approval_manager

PANEL_TITLE = "Approvals"


async def panel_approval(
    message: str,
    call: ToolCall,
    view: ToolCallView,
    state: TaskState | None,
    choices: list[ApprovalDecision],
) -> Approval:
    from inspect_ai._display.core.active import task_screen

    # ensure the approvals panel is shown and activate it
    panel = task_screen().input_panel(PANEL_TITLE, ApprovalInputPanel)
    panel.activate()

    # submit to human approval manager (will be picked up by panel)
    return await human_approval_manager().approve(
        ApprovalRequest(
            message=message, call=call, view=view, state=state, choices=choices
        )
    )


class ApprovalInputPanel(InputPanel):
    _approvals: list[tuple[str, ApprovalRequest]] = []
    _approvals_unsubscribe: Callable[[], None] | None = None

    @override
    def compose(self) -> ComposeResult:
        yield Static("Approval")

    def on_mount(self) -> None:
        self._approvals_unsubscribe = human_approval_manager().on_change(
            self.on_approvals_changed
        )

    def on_unmount(self) -> None:
        if self._approvals_unsubscribe is not None:
            self._approvals_unsubscribe()

    def on_approvals_changed(self) -> None:
        self._approvals = human_approval_manager().approval_requests()
        if len(self._approvals) > 0:
            self.set_title(f"{PANEL_TITLE} ({len(self._approvals):,})")
        else:
            self.set_title(PANEL_TITLE)
            self.deactivate()
