"""Ask a person about a tool call through Inspect's human approval surfaces.

A sentinel in the eval's own process asks through `human()`. A sentinel in a
sidecar asks through the sidecar's questions. Both show the call the same way
and read the person's choice the same way, so what the person sees doesn't
depend on where the sentinel runs.
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
"""The choices a person can be offered.

There is no `modify`, because Inspect's human approval surfaces can't edit a tool
call.
"""


def offered_choices(choices: Sequence[str]) -> list[ApprovalDecision]:
    """Check the choices to offer a person, and return them in the order given.

    Raises:
        ValueError: If a choice is not one of `HUMAN_CHOICES`.
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
    """The escalations to show a person, one per line.

    Each line has the name of the instance that escalated, and its reason if it
    gave one.
    """
    return escape_placeholders(
        "\n".join(
            f"- {name}: {explanation}" if explanation else f"- {name}"
            for name, explanation in escalations
        )
    )


def human_view(
    view: ToolCallView, escalated: str | None, result: ChatMessageTool | None
) -> ToolCallView:
    """Build the view of a call that a person is shown.

    The escalations go above the call. The call's result goes below it, once
    the call has run.

    Args:
        view: The call's own view.
        escalated: The escalations, as `escalation_lines` writes them, or None
            if there are none.
        result: The call's result, when the person is asked after the call ran.
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


def chosen_decision(
    approval: Approval, offered: list[ApprovalDecision]
) -> tuple[ApprovalDecision, str | None]:
    """Return what the person chose, and their reason.

    If the prompt closed without one of the offered choices, the answer fails
    closed: `reject` if it was offered, otherwise `terminate`.
    """
    if approval.decision in offered:
        return approval.decision, approval.explanation
    # the reason says the person did not choose, since later steps read
    # this decision in human_decisions
    return (
        "reject" if "reject" in offered else "terminate",
        "The person closed the prompt without choosing; failing closed "
        f"(the surface answered {approval.decision}: {approval.explanation}).",
    )
