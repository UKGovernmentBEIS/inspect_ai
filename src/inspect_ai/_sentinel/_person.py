"""Ask a person about a tool call, or a model's whole turn, through Inspect's human approval surfaces.

A sentinel in the eval's own process asks through `human()`. A sentinel in a
sidecar asks through the sidecar's questions. Both show a call or a turn the
same way and read the person's choice the same way. One thing differs: a
sidecar holds the model's reply while it asks about it, so Inspect has shown the
person none of the turn, and the question's view holds what the turn says and
reasons too (see `_turn_content`).
"""

import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from typing import Literal, NamedTuple, cast

from shortuuid import uuid as shortuuid

from inspect_ai._util.content import ContentReasoning, ContentText, ContentToolUse
from inspect_ai._util.format import MARKER_CLOSE, MARKER_OPEN, display_safe
from inspect_ai.approval._approval import Approval, ApprovalDecision
from inspect_ai.approval._approver import Approver
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
)
from inspect_ai.review._human import (
    escape_placeholders,
    fenced,
    view_with_result,
)
from inspect_ai.tool._tool_call import (
    ToolCall,
    ToolCallContent,
    ToolCallView,
    default_tool_call_viewer,
    substitute_tool_call_content,
)
from inspect_ai.util._notify import apprise_scope, notify

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


def held_call_view(
    view: ToolCallView,
    call: ToolCall,
    escalated: str | None,
    turn: ChatMessageAssistant,
) -> ToolCallView:
    """Build the view of a call whose turn the person has seen none of.

    A sidecar holds the reply that makes the call while it asks, so the view
    shows what the turn holds besides its tool calls, between the escalations
    and the call (see `_turn_content`).

    The view is markdown, and everything in it but its labels is inside a code
    block it cannot close: what the turn holds, and what the tool's viewer
    made of the call and of its context, with the call's arguments filled in
    first (see `_contained`). So nothing an agent wrote passes for one of the
    view's labels. A viewer's plain text is in a code block too, because the
    surfaces wrap plain text to the window, and a wrapped line starts at the
    margin as a label does.

    Args:
        view: The call's own view.
        call: The call.
        escalated: The escalations, as `escalation_lines` writes them, or None
            if there are none.
        turn: The turn that made the call.
    """
    escaped = _Escaped()

    def safe(text: str) -> str:
        # The surfaces fill in the call's arguments again, after any fence
        # here is sized. So nothing here may still read as a placeholder.
        return escape_placeholders(escaped(text))

    shown = [f"**Escalated by**\n\n{fenced(safe(escalated))}"] if escalated else []
    shown.extend(section.markdown() for section in _turn_content(turn, safe))
    title: str | None = None
    made: list[str] = []
    for label, part in (("The call's context", view.context), ("The call", view.call)):
        if part is not None:
            filled = substitute_tool_call_content(part, call.arguments)
            made.append(f"**{label}**\n\n{_contained(filled, safe)}")
            if part is view.call and filled.title:
                title = " ".join(safe(filled.title).split())
    if escaped.escaped:
        shown.append(f"**{_ESCAPED_NOTICE}**")
    return ToolCallView(
        call=ToolCallContent(
            title=title, format="markdown", content="\n\n".join([*shown, *made])
        )
    )


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


async def ask_about_turn(
    approve: Approver,
    turn: ChatMessageAssistant | None,
    escalations: Sequence[tuple[str, str | None]],
    offered: list[ApprovalDecision],
    conversation: list[ChatMessage],
    content_in_view: bool = False,
) -> Approval:
    """Ask a person about a model's whole turn, as one prompt.

    Args:
        approve: The human approver to ask with.
        turn: The assistant message of the turn, or None if the model returned
            no turn.
        escalations: Each escalating instance's name, and its reason if it
            gave one.
        offered: The choices the person may pick.
        conversation: The conversation to show beside the prompt.
        content_in_view: Whether the view holds the turn's reasoning and
            text. See `turn_prompt`.
    """
    # deferred: the ACP shim imports `acp.schema`, which only matters once a
    # person is asked
    from inspect_ai.approval._human.acp import finish_approval_card

    prompt = turn_prompt(turn, escalations, content_in_view)
    status: Literal["completed", "failed"] = "failed"
    try:
        if content_in_view:
            approval = await approve_with_text_in_view(
                approve, prompt.said, prompt.call, prompt.view, conversation
            )
        else:
            approval = await approve(
                prompt.message, prompt.call, prompt.view, conversation
            )
        if approval.decision in offered:
            status = "completed"
        return approval
    finally:
        # no tool event completes the card the turn's prompt opened; a prompt
        # that ended without one of the choices failed
        finish_approval_card(prompt.call, prompt.view, status)


async def approve_with_text_in_view(
    approve: Approver,
    said: str,
    call: ToolCall,
    view: ToolCallView,
    conversation: list[ChatMessage],
) -> Approval:
    """Ask a person with a view that already holds the turn's text.

    The prompt's message is empty, so that no surface shows the text twice.
    The human approver notifies the operator with the message, so the text is
    sent from here instead and the approver's own notification is turned off:
    the operator is told what a turn that reached Inspect would have told them.

    Args:
        approve: The human approver to ask with.
        said: The turn's text, for the notification.
        call: The call to ask about.
        view: The view, which holds the text.
        conversation: The conversation to show beside the prompt.
    """
    await notify(said)
    with apprise_scope(None):
        return await approve("", call, view, conversation)


class TurnPrompt(NamedTuple):
    """A model's whole turn, as the arguments a human approver takes."""

    message: str
    call: ToolCall
    view: ToolCallView
    said: str
    """The turn's text. It is `message`, unless the view holds it."""


def turn_prompt(
    turn: ChatMessageAssistant | None,
    escalations: Sequence[tuple[str, str | None]],
    content_in_view: bool = False,
) -> TurnPrompt:
    """The assistant turn as one prompt for the human approval surfaces.

    The surfaces show one tool call, so the turn becomes a single view: the
    escalations, how many calls the turn makes, then each call. Two things
    keep a call from hiding, merging into or passing for another:

    - Markdown: a call's content is shown only inside a code block it cannot
      close (see `_call_markdown`), and everything outside the code blocks is
      written here, so the count says how many calls there are.
    - Characters that act rather than show (terminal escape sequences, which
      could move the cursor over another call's lines, bidi overrides, and
      zero-width and tag characters): everything the agent wrote in the view,
      the calls, the escalations quoting it and the title, goes through
      `display_safe`, which shows each as a marker, and the view says so when
      it did. So does the assistant text, which the panel and the console show
      above the view; an ACP client shows the turn's streamed text and
      reasoning instead, which the Inspect ACP TUI makes safe the same way,
      as `--display conversation` does for the turn it prints.

    What a call's own viewer makes of its arguments inside its code block is
    the viewer's; a call can still garble its own content there. Earlier
    tool output in the ACP TUI's stream and the conversation display is not
    made safe yet.

    The call handed to the surfaces stands for the whole turn, and its
    function is the turn's title, which carries the count too. Its id is its
    own, unlike any tool call's or another prompt's, since an ACP client opens
    a card under it; its empty arguments leave the view as rendered here.

    With `content_in_view`, what the turn holds besides its calls goes into
    the view, above the count, and the prompt's message is empty (see
    `_turn_content`). A sentinel in a sidecar asks before the turn reaches
    Inspect, so none of it has streamed to the person: an ACP client shows no
    message of its own, and no surface has shown the rest.
    """
    safe = _Escaped()
    message = turn
    calls = (message.tool_calls if message else None) or []
    shown = [
        _call_markdown(call, index, len(calls), safe)
        for index, call in enumerate(calls, 1)
    ]
    tally = Counter(_one_line(call.function, safe) for call in calls)
    tools = ", ".join(
        function if count == 1 else f"{function} ×{count}"
        for function, count in tally.items()
    )
    text = safe(message.text) if message else ""
    blocks: list[str] = []
    if escalations:
        escalated = safe(escalation_lines(escalations))
        blocks.append(f"**Escalated by**\n\n{fenced(escalated)}")
    if content_in_view and message is not None:
        blocks.extend(section.markdown() for section in _turn_content(message, safe))
    count = f"**The turn makes {_calls(len(calls))}.**"
    if safe.escaped:
        count = f"{count}\n\n**{_ESCAPED_NOTICE}**"
    blocks.append(count)
    blocks.extend(shown)
    stands_for_turn = ToolCall(
        id=f"turn_{shortuuid()}",
        function=f"Assistant turn: {_calls(len(calls))}"
        + (f" ({tools})" if tools else ""),
        arguments={},
    )
    view = ToolCallView(
        call=ToolCallContent(format="markdown", content="\n\n---\n\n".join(blocks))
    )
    return TurnPrompt("" if content_in_view else text, stands_for_turn, view, text)


class _Section(NamedTuple):
    """One thing a view shows above a call: a label written here, then its content.

    The content is shown inside a code block it cannot close, so nothing an
    agent wrote adds structure to the view. A section with no content is a
    notice.
    """

    label: str
    """What the section is, in words written here."""

    body: str | None = None
    """The content, already made safe to display."""

    name: str = ""
    """Text an agent wrote that completes the label, such as a tool's name."""

    def markdown(self) -> str:
        head = f"**{self.label}**"
        if self.name:
            head = f"{head} {_markdown_escaped(self.name)}"
        return head if self.body is None else f"{head}\n\n{fenced(self.body)}"


def _turn_content(
    turn: ChatMessageAssistant, safe: Callable[[str], str]
) -> list[_Section]:
    """What a turn holds besides its tool calls, for a person who has seen none of it.

    In order: the reasoning, the text, each tool the provider ran itself (a
    web search, an MCP call, code execution) with its arguments and what it
    returned, then a count of anything else, such as an image. Reasoning whose
    text the provider withheld is counted too. So the person is shown, or
    told of, everything in the turn.

    Args:
        turn: The assistant message of the turn.
        safe: Makes text an agent wrote safe to display.
    """
    content = turn.content if isinstance(turn.content, list) else []
    sections: list[_Section] = []
    readable: list[str] = []
    withheld = 0
    for block in content:
        if isinstance(block, ContentReasoning):
            # as the transcript shows it: a provider may return reasoning
            # encrypted, with a summary, or with nothing readable
            thought = (
                block.summary if block.redacted else (block.reasoning or block.summary)
            )
            if thought:
                readable.append(thought)
            else:
                withheld += 1
    if readable:
        sections.append(_Section("The turn's reasoning", safe("\n\n".join(readable))))
    if withheld:
        sections.append(
            _Section(
                f"The provider withheld the text of {withheld} "
                f"{'block' if withheld == 1 else 'blocks'} of the turn's reasoning."
            )
        )
    if turn.text:
        sections.append(_Section("The turn says", safe(turn.text)))
    ran = [block for block in content if isinstance(block, ContentToolUse)]
    for index, use in enumerate(ran, 1):
        name = f"{use.name} ({use.tool_type}"
        name += f", {use.context})" if use.context else ")"
        sections.append(
            _Section(
                f"Tool {index} of {len(ran)} that the provider ran:",
                safe(use.arguments) if use.arguments else None,
                " ".join(safe(name).split()),
            )
        )
        if use.result:
            sections.append(_Section("It returned", safe(use.result)))
        if use.error:
            sections.append(_Section("It failed with", safe(use.error)))
    other = Counter(
        block.type
        for block in content
        if not isinstance(block, (ContentReasoning, ContentText, ContentToolUse))
    )
    if other:
        counted = ", ".join(f"{count} {type}" for type, count in other.items())
        sections.append(
            _Section(f"The turn also holds content that is not shown here: {counted}.")
        )
    return sections


_ESCAPED_NOTICE = (
    "This turn contains hidden or control characters, "
    f"shown as {MARKER_OPEN}U+…{MARKER_CLOSE}."
)


class _Escaped:
    """`display_safe` for one turn, remembering whether it escaped anything."""

    def __init__(self) -> None:
        self.escaped = False

    def __call__(self, text: str) -> str:
        shown = display_safe(text)
        self.escaped = self.escaped or shown.escaped
        return shown.text


def _calls(count: int) -> str:
    if count == 0:
        return "no tool calls"
    return "1 tool call" if count == 1 else f"{count} tool calls"


def _call_markdown(call: ToolCall, index: int, count: int, safe: _Escaped) -> str:
    """One call: a header written here, then its content as a code block.

    The content is what the transcript shows (`ToolCall.view`, which
    `Model.generate` sets from the tool's viewer, or the default rendering),
    with the call's placeholders filled in (see `_contained`).
    """
    content = substitute_tool_call_content(
        call.view or cast(ToolCallContent, default_tool_call_viewer(call).call),
        call.arguments,
    )
    header = f"**Call {index} of {count}:** {_markdown_text(call.function, safe)}"
    if content.title and content.title != call.function:
        header = f"{header} ({_markdown_text(content.title, safe)})"
    return f"{header}\n\n{_contained(content, safe)}"


def _contained(content: ToolCallContent, safe: Callable[[str], str]) -> str:
    """What a tool's viewer made, as one code block it cannot close.

    Viewers interpolate arguments into markdown unescaped, so an argument could
    close the viewer's code fence and write a label of the view, or open an
    HTML comment that swallows what follows. A viewer's single code block keeps
    its language and is fenced again by a fence longer than any backtick run in
    it. Any other content is shown as source.

    Args:
        content: The viewer's content, with the call's placeholders filled in.
        safe: Makes text an agent wrote safe to display.
    """
    block = _CODE_BLOCK.fullmatch(content.content)
    if content.format == "markdown" and block is not None:
        language, code = block.group("language").strip(), block.group("code")
    else:
        language = "markdown" if content.format == "markdown" else ""
        code = content.content
    return _code_block(safe(code), language)


# a viewer's single fenced code block, e.g. `code_viewer`'s and the default's
_CODE_BLOCK = re.compile(
    r"(?P<fence>`{3,})(?P<language>[\w+.-]*)\n(?P<code>.*)\n(?P=fence)[ \t]*\n?",
    re.DOTALL,
)


def _code_block(code: str, language: str) -> str:
    # deferred: the ACP shim imports `acp.schema`, which only matters once a
    # person is asked
    from inspect_ai.approval._human.acp import _safe_code_fence

    fence = _safe_code_fence(code)
    return f"{fence}{language}\n{code}\n{fence}"


def _markdown_text(text: str, safe: _Escaped) -> str:
    # one line of literal text: markdown punctuation escaped, so a function
    # name or viewer title cannot add structure
    return _markdown_escaped(_one_line(text, safe))


def _markdown_escaped(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|<>~&])", r"\\\1", text)


def _one_line(text: str, safe: _Escaped) -> str:
    return " ".join(safe(text).split())
