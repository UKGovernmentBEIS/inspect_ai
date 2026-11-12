"""Asking a person about a tool call through Inspect's human approval surfaces.

A sentinel in the eval's own process asks through `human()`, and one in a sidecar asks through the sidecar's questions. Both show the call the same way and read the person's choice the same way, so what a person sees doesn't depend on where the sentinel runs.
"""

from collections.abc import Iterable, Sequence
from typing import cast

from inspect_ai.approval._approval import Approval, ApprovalDecision
from inspect_ai.model._chat_message import ChatMessageTool
from inspect_ai.review._human import (
    escape_placeholders,
    fenced,
    view_with_result,
)
from inspect_ai.tool._tool_call import ToolCallContent, ToolCallView

HUMAN_CHOICES = ("approve", "reject", "terminate")
"""What a person can be offered: Inspect's human approval surfaces can't edit a tool call."""


def offered_choices(choices: Sequence[str]) -> list[ApprovalDecision]:
    """The choices a person is offered, in the order given.

    Raises:
        ValueError: If one isn't a choice a person can be offered.
    """
    offered: list[ApprovalDecision] = []
    for choice in choices:
        if choice not in HUMAN_CHOICES:
            raise ValueError(
                f"human() cannot offer {choice!r}; the choices are "
                f"{', '.join(repr(c) for c in HUMAN_CHOICES)}."
            )
        offered.append(cast(ApprovalDecision, choice))
    return offered


def escalation_lines(escalations: Iterable[tuple[str, str | None]]) -> str:
    """The escalations a person is shown, one to a line: each escalating instance's name, and why it escalated if it said."""
    return escape_placeholders(
        "\n".join(
            f"- {name}: {explanation}" if explanation else f"- {name}"
            for name, explanation in escalations
        )
    )


def human_view(
    view: ToolCallView, escalated: str | None, result: ChatMessageTool | None
) -> ToolCallView:
    """A call's view as a person is shown it: with who escalated it above the call, and with its result below once it has run.

    Args:
        view: The call's own view.
        escalated: The escalations, as `escalation_lines` writes them, or None if there are none.
        result: The call's result, at the stage after it ran.
    """
    if escalated is not None:
        block = f"**Escalated by**\n\n{fenced(escalated)}"
        if view.call is None:
            call = ToolCallContent(format="markdown", content=block)
        elif view.call.format == "markdown":
            call = ToolCallContent(
                title=view.call.title,
                format="markdown",
                content=f"{block}\n\n{view.call.content}",
            )
        else:
            call = ToolCallContent(
                title=view.call.title,
                format="text",
                content=f"Escalated by\n\n{escalated}\n\n{view.call.content}",
            )
        view = ToolCallView(context=view.context, call=call)
    if result is not None:
        view = view_with_result(view, result)
    return view


def chosen(
    approval: Approval, offered: list[ApprovalDecision]
) -> tuple[ApprovalDecision, str | None]:
    """What the person chose, and their reason. A prompt closed without one of the choices offered fails closed: `reject` if it was offered, otherwise `terminate`."""
    if approval.decision in offered:
        return approval.decision, approval.explanation
    # the reason says the person did not choose, since later steps read
    # this decision in human_decisions
    return (
        "reject" if "reject" in offered else "terminate",
        "The person closed the prompt without choosing; failing closed "
        f"(the surface answered {approval.decision}: {approval.explanation}).",
    )
