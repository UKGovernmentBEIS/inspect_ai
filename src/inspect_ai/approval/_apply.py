import pprint
from contextvars import ContextVar
from textwrap import indent
from typing import Any

from inspect_ai.approval._approval import Approval
from inspect_ai.tool._tool_call import (
    ToolCall,
    ToolCallContent,
    ToolCallView,
    ToolCallViewer,
)

from ._approver import Approver
from ._policy import ApprovalPolicy, policy_approver


async def apply_tool_approval(
    message: str, call: ToolCall, viewer: ToolCallViewer | None
) -> tuple[bool, Approval | None]:
    from inspect_ai.solver._task_state import sample_state

    approver = _tool_approver.get(None)
    if approver:
        # resolve view
        if viewer:
            view = viewer(call)
            if not view.call:
                view.call = default_tool_call_viewer(call).call
        else:
            view = default_tool_call_viewer(call)

        # current sample state
        state = sample_state()

        # call approver
        approval = await approver(
            message=message,
            call=call,
            view=view,
            state=state,
        )

        # process decision
        match approval.decision:
            case "approve":
                return True, approval
            case "reject":
                return False, approval
            case _:
                if state:
                    state.completed = True
                return False, approval

    # no approval system registered
    else:
        return True, None


def default_tool_call_viewer(call: ToolCall) -> ToolCallView:
    return ToolCallView(
        call=ToolCallContent(
            format="markdown",
            content="```python\n"
            + format_function_call(call.function, call.arguments)
            + "\n```\n",
        )
    )


def format_function_call(
    func_name: str, args_dict: dict[str, Any], indent_spaces: int = 4, width: int = 80
) -> str:
    formatted_args = []
    for key, value in args_dict.items():
        formatted_value = format_value(value, width)
        formatted_args.append(f"{key}={formatted_value}")

    args_str = ", ".join(formatted_args)

    if len(args_str) <= width - 1 - len(func_name) - 2:  # 2 for parentheses
        return f"{func_name}({args_str})"
    else:
        indented_args = indent(",\n".join(formatted_args), " " * indent_spaces)
        return f"{func_name}(\n{indented_args}\n)"


def format_value(value: object, width: int) -> str:
    if isinstance(value, str):
        return f"'{value}'"
    elif isinstance(value, list | tuple | dict):
        return pprint.pformat(value, width=width)
    return str(value)


def init_tool_approval(approval: list[ApprovalPolicy] | None) -> None:
    if approval:
        _tool_approver.set(policy_approver(approval))
    else:
        _tool_approver.set(None)


_tool_approver: ContextVar[Approver | None] = ContextVar("tool_approver", default=None)
