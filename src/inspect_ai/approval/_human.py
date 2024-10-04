import pprint
from textwrap import indent
from typing import Any

from rich import print
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax

from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.util._console import input_screen

from ._approval import Approval, ApprovalDecision
from ._approver import Approver
from ._registry import approver


@approver(name="human")
def human_approver(
    choices: list[ApprovalDecision] = ["approve", "reject"],
) -> Approver:
    """Interactive human approver.

    Returns:
       Approver: Interactive human approver.
    """

    async def approve(
        tool_call: ToolCall, tool_view: str, state: TaskState | None = None
    ) -> Approval:
        with input_screen() as console:
            console.print(
                Panel(
                    Syntax(
                        code=format_function_call(
                            tool_call.function, tool_call.arguments
                        ),
                        lexer="python",
                        theme="emacs",
                        background_color="default",
                    ),
                    title="[bold][blue]Tool Call Approval[/blue][/bold]",
                    highlight=True,
                    expand=True,
                )
            )

            # provide choices
            prompts: dict[str, str] = {}
            for choice in choices:
                prompts[choice[0]] = f"{choice.capitalize()} ({choice[0]})"
            values = list(prompts.values())
            prompt = ", ".join(values[:-1])
            prompt = f"{prompt}, or {values[-1]}"

            while True:
                decision = Prompt.ask(
                    prompt,
                    console=console,
                    choices=list(prompts.keys()),
                    default="a",
                ).lower()

                if decision == "a":
                    return Approval(
                        decision="approve",
                        explanation="Human operator approved tool call.",
                        interactive=True,
                    )
                elif decision == "r":
                    return Approval(
                        decision="reject",
                        explanation="Human operator rejected the tool call.",
                        interactive=True,
                    )
                elif decision == "t":
                    return Approval(
                        decision="terminate",
                        explanation="Human operator asked that the evaluation be terminated.",
                        interactive=True,
                    )
                elif decision == "e":
                    return Approval(
                        decision="escalate",
                        explanation="Human operator escalated the tool call approval.",
                        interactive=True,
                    )

    return approve


def format_function_call(
    func_name: str, args_dict: dict[str, Any], indent_spaces: int = 4
) -> str:
    formatted_args = []
    for key, value in args_dict.items():
        formatted_value = format_value(value)
        formatted_args.append(f"{key}={formatted_value}")

    args_str = ", ".join(formatted_args)

    if len(args_str) <= 79 - len(func_name) - 2:  # 2 for parentheses
        return f"{func_name}({args_str})"
    else:
        indented_args = indent(",\n".join(formatted_args), " " * indent_spaces)
        return f"{func_name}(\n{indented_args}\n)"


def format_value(value: object) -> str:
    if isinstance(value, str):
        return f"'{value}'"
    elif isinstance(value, list | tuple | dict):
        return pprint.pformat(value)
    return str(value)
