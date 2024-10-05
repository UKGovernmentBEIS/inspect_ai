from rich.console import Group, RenderableType
from rich.highlighter import ReprHighlighter
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.text import Text

from inspect_ai.solver._task_state import TaskState
from inspect_ai.tool._tool_call import ToolCall, ToolCallContent, ToolCallView
from inspect_ai.util._console import input_screen

from ._approval import Approval, ApprovalDecision
from ._approver import Approver
from ._registry import approver


@approver(name="human")
def human_approver(
    choices: list[ApprovalDecision] = ["approve", "reject", "terminate"],
) -> Approver:
    """Interactive human approver.

    Returns:
       Approver: Interactive human approver.
    """
    # text highlither
    text_highlighter = ReprHighlighter()

    async def approve(
        content: str,
        call: ToolCall,
        view: ToolCallView,
        state: TaskState | None = None,
    ) -> Approval:
        with input_screen(width=None) as console:
            renderables: list[RenderableType] = []

            def add_view_content(view_content: ToolCallContent) -> None:
                if view_content.format == "markdown":
                    renderables.append(Markdown(view_content.content, code_theme="vs"))
                else:
                    text_content = text_highlighter(Text(view_content.content))
                    renderables.append(text_content)

            if content:
                renderables.append(Text.from_markup("[bold]Assistant[/bold]\n"))
                renderables.append(Text(f"{content.strip()}\n"))
            if view.context:
                add_view_content(view.context)
                renderables.append(Text())

            if view.call:
                if content or view.context:
                    renderables.append(Rule("", style="bold", align="left"))
                renderables.append(Text())
                add_view_content(view.call)
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
