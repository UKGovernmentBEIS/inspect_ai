from inspect_ai.approval._approval import Approval, ApprovalDecision
from inspect_ai.approval._human.acp import _safe_code_fence
from inspect_ai.approval._human.approver import human_approver
from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool
from inspect_ai.tool._tool import ToolResult
from inspect_ai.tool._tool_call import ToolCall, ToolCallContent, ToolCallView

from ._registry import reviewer
from ._review import Review, ReviewDecision
from ._reviewer import Reviewer

HUMAN_CONTINUED = "Human operator reviewed the tool result and let the sample continue."
HUMAN_TERMINATED = (
    "Human operator reviewed the tool result and asked that the sample be terminated."
)
HUMAN_ESCALATED = "Human operator escalated the tool result review."

# The review is collected by `human_approver`, so it reaches the operator on
# the approval surfaces (ACP, panel, console), which speak approval decisions:
# `continue` is offered as `approve`.
_APPROVAL_CHOICE: dict[ReviewDecision, ApprovalDecision] = {
    "continue": "approve",
    "terminate": "terminate",
    "escalate": "escalate",
}
_REVIEW_DECISION: dict[ApprovalDecision, ReviewDecision] = {
    approval: review for review, approval in _APPROVAL_CHOICE.items()
}
_EXPLANATION: dict[ReviewDecision, str] = {
    "continue": HUMAN_CONTINUED,
    "terminate": HUMAN_TERMINATED,
    "escalate": HUMAN_ESCALATED,
}


@reviewer(name="human")
def human_reviewer(
    choices: list[ReviewDecision] = ["continue", "terminate"],
) -> Reviewer:
    """Interactive human reviewer.

    Shows the operator the tool call together with the result it returned, on
    the same surfaces as `human_approver()` (an attached ACP client, the
    approvals panel in the full-screen display, or the console), and asks for
    a review decision. `continue` is offered as the surfaces' "approve" choice.

    Args:
       choices: Choices to present to human.

    Returns:
       Reviewer: Interactive human reviewer.
    """
    approval_choices = [_APPROVAL_CHOICE[choice] for choice in choices]
    approve = human_approver(choices=approval_choices)

    async def review(
        message: str,
        call: ToolCall,
        result: ChatMessageTool,
        output: ToolResult,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Review:
        approval = await approve(message, call, view_with_result(view, result), history)
        return review_from_approval(approval, approval_choices)

    return review


def view_with_result(view: ToolCallView, result: ChatMessageTool) -> ToolCallView:
    """The call's view with the result it returned appended to the call content."""
    if result.error is not None:
        outcome = f"Error ({result.error.type}): {result.error.message}"
    else:
        outcome = _result_text(result)
    # The surfaces substitute `{{param}}` placeholders from the call's
    # arguments into the view; tool output is evidence, not a template.
    outcome = outcome.replace("{{", "{ {")
    result_block = f"**Result**\n\n{_fenced(outcome)}"
    if view.call is None:
        call = ToolCallContent(format="markdown", content=result_block)
    elif view.call.format == "markdown":
        call = ToolCallContent(
            title=view.call.title,
            format="markdown",
            content=f"{view.call.content}\n\n{result_block}",
        )
    else:
        # A text view stays text. The surfaces substitute `{{param}}` into the
        # content after this runs, so a fence sized here cannot contain what
        # the substitution puts inside it, and the panel and console render
        # text without interpreting markdown at all.
        call = ToolCallContent(
            title=view.call.title,
            format="text",
            content=f"{view.call.content}\n\nResult\n\n{outcome}",
        )
    return ToolCallView(context=view.context, call=call)


def review_from_approval(approval: Approval, offered: list[ApprovalDecision]) -> Review:
    """The operator's choice as a review; anything else fails closed.

    A surface can end without a choice (an ACP client dismissing the request
    reports `reject`); the call has already run, so the safe outcome is to
    stop the sample.
    """
    decision = _REVIEW_DECISION.get(approval.decision)
    if approval.decision not in offered or decision is None:
        return Review(
            decision="terminate",
            explanation=(
                "Human review ended without one of the offered choices "
                f"({approval.decision}: {approval.explanation}); the sample is "
                "terminated."
            ),
        )
    return Review(decision=decision, explanation=_EXPLANATION[decision])


def _result_text(result: ChatMessageTool) -> str:
    """The result's text, with content the surfaces cannot render named.

    `ChatMessageTool.text` drops image, audio and video parts, and the three
    surfaces render text only. Naming the part keeps a screenshot-returning
    tool from reaching the operator as an empty result.
    """
    return "\n".join(
        content.text if content.type == "text" else f"[{content.type}]"
        for content in result.content_list
    )


def _fenced(text: str) -> str:
    fence = _safe_code_fence(text)
    return f"{fence}\n{text}\n{fence}"
