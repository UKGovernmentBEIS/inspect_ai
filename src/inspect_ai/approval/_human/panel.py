from textual.app import ComposeResult
from textual.widgets import Static
from typing_extensions import override

from inspect_ai._display.core.input import InputPanel
from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall, ToolCallView

from .._approval import Approval, ApprovalDecision
from .queue import ApprovalRequest, human_approval_manager


async def panel_approval(
    message: str,
    call: ToolCall,
    view: ToolCallView,
    state: TaskState | None,
    choices: list[ApprovalDecision],
) -> Approval:
    from inspect_ai._display.core.active import task_screen

    # ensure the approvals panel is shown and activate it
    panel = task_screen().input_panel("Approvals", ApprovalInputPanel)
    panel.activate()

    # submit to human approval manager (will be picked up by panel)
    return await human_approval_manager().approve(
        ApprovalRequest(
            message=message, call=call, view=view, state=state, choices=choices
        )
    )


class ApprovalInputPanel(InputPanel):
    @override
    def compose(self) -> ComposeResult:
        yield Static("Approval")

    def on_mount(self) -> None:
        # TODO: hookup to events from approval manager
        pass

    @override
    def update(self) -> None:
        # don't think we need to poll here?
        pass
