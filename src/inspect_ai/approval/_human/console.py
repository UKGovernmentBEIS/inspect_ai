from rich.console import RenderableType
from rich.highlighter import ReprHighlighter
from rich.prompt import Prompt
from rich.rule import Rule
from rich.text import Text

from inspect_ai._util.transcript import transcript_markdown, transcript_panel
from inspect_ai.tool._tool_call import ToolCallContent, ToolCallView
from inspect_ai.util._trace import trace_enabled

from .._approval import Approval, ApprovalDecision


def console_approval(
    message: str, view: ToolCallView, choices: list[ApprovalDecision]
) -> Approval:
    from inspect_ai._display.core.active import task_screen

    with task_screen().input_screen(width=None) as console:
        renderables: list[RenderableType] = []
        text_highlighter = ReprHighlighter()

        # ignore content if trace enabled
        message = message if not trace_enabled() else ""

        def add_view_content(view_content: ToolCallContent) -> None:
            if view_content.title:
                renderables.append(
                    Text.from_markup(f"[bold]{view_content.title}[/bold]\n")
                )
            if view_content.format == "markdown":
                renderables.append(transcript_markdown(view_content.content))
            else:
                text_content = text_highlighter(Text(view_content.content))
                renderables.append(text_content)

        # assistant content (don't add if trace_enabled as we already have it in that case)
        if message:
            renderables.append(Text.from_markup("[bold]Assistant[/bold]\n"))
            renderables.append(Text(f"{message.strip()}"))

        # extra context provided by tool view
        if view.context:
            renderables.append(Text())
            add_view_content(view.context)
            renderables.append(Text())

        # tool call view
        if view.call:
            if message or view.context:
                renderables.append(Rule("", style="bold", align="left"))
            renderables.append(Text())
            add_view_content(view.call)
            renderables.append(Text())

        console.print(transcript_panel(title="Approve Tool", content=renderables))

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
                prompt=prompt,
                console=console,
                choices=list(prompts.keys()),
                default="a",
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
