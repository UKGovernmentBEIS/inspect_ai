import pprint
from textwrap import indent
from typing import Any

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text

from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.util._console import input_screen

from ._approval import Approval, ApprovalDecision
from ._approver import Approver, ApproverToolView
from ._registry import approver


@approver(name="human")
def human_approver(
    choices: list[ApprovalDecision] = ["approve", "reject", "terminate"],
) -> Approver:
    """Interactive human approver.

    Returns:
       Approver: Interactive human approver.
    """

    async def approve(
        content: str,
        call: ToolCall,
        view: ApproverToolView | None = None,
        state: TaskState | None = None,
    ) -> Approval:
        with input_screen() as console:
            renderables: list[RenderableType] = []
            if content:
                renderables.append(Text.from_markup("[bold]Assistant[/bold]\n"))
                renderables.append(Text(f"{content.strip()}\n"))
                renderables.append(Rule("", style="bold", align="left"))
            renderables.append(Text())
            renderables.append(
                Syntax(
                    code=format_function_call(call.function, call.arguments),
                    lexer="python",
                    theme="emacs",
                    background_color="default",
                ),
            )
            renderables.append(Text())

            console.print(
                Panel(
                    Group(*renderables),
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

            def render_approval(approval: Approval) -> Approval:
                console.print(f"Decision: {approval.decision.capitalize()}")
                return approval

            while True:
                decision = Prompt.ask(
                    prompt,
                    console=console,
                    choices=list(prompts.keys()),
                    default="a",
                    case_sensitive=False,
                ).lower()

                if decision == "a":
                    return render_approval(
                        Approval(
                            decision="approve",
                            explanation="Human operator approved tool call.",
                        )
                    )
                elif decision == "r":
                    return render_approval(
                        Approval(
                            decision="reject",
                            explanation="Human operator rejected the tool call.",
                        )
                    )
                elif decision == "t":
                    return render_approval(
                        Approval(
                            decision="terminate",
                            explanation="Human operator asked that the sample be terminated.",
                        )
                    )
                elif decision == "e":
                    return render_approval(
                        Approval(
                            decision="escalate",
                            explanation="Human operator escalated the tool call approval.",
                        )
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
