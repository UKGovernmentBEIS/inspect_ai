"""Ask a person about a tool call, a model's whole turn, or a model's request, through Inspect's human approval surfaces.

A sentinel in the eval's own process asks through `human()`. A sentinel in a
sidecar asks through the sidecar's questions. Both show a call, a turn or a
request the same way and read the person's choice the same way. One thing
differs: a sidecar holds the model's reply while it asks about it, so Inspect
has shown the person none of the turn, and the question's view holds what the
turn says and reasons too (see `_turn_content`).
"""

import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from typing import Literal, NamedTuple, cast

from shortuuid import uuid as shortuuid

from inspect_ai._util.content import ContentReasoning, ContentText, ContentToolUse
from inspect_ai._util.format import (
    MARKER_CLOSE,
    MARKER_OPEN,
    display_safe,
    markdown_escaped,
    safe_code_fence,
)
from inspect_ai.approval._approval import Approval, ApprovalDecision
from inspect_ai.approval._approver import Approver
from inspect_ai.approval._human.util import arguments_view
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
from inspect_ai.tool._tool_choice import ToolChoice, ToolFunction
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
        conversation: The conversation to give the approval surface.
        content_in_view: Whether the view holds the turn's reasoning and
            text. See `turn_prompt`.
    """
    return await _ask_with(
        approve, turn_prompt(turn, escalations, content_in_view), offered, conversation
    )


async def ask_about_request(
    approve: Approver,
    model: str,
    sent: int,
    shown: Sequence[tuple[int, ChatMessage]],
    tools: Sequence[str],
    tool_choice: ToolChoice,
    escalations: Sequence[tuple[str, str | None]],
    offered: list[ApprovalDecision],
    conversation: list[ChatMessage],
) -> Approval:
    """Ask a person about the request a model is about to be sent, as one prompt.

    Args:
        approve: The human approver to ask with.
        model: The model the request is for.
        sent: How many messages the request sends.
        shown: The messages the model has not been sent before, each with its
            position in the request, counting from 1.
        tools: The names of the tools the request offers the model.
        tool_choice: Which tool the model is to call: `auto`, `any` or
            `none`, or the one function it must call.
        escalations: Each escalating instance's name, and its reason if it
            gave one.
        offered: The choices the person may pick.
        conversation: The conversation to give the approval surface.
    """
    return await _ask_with(
        approve,
        request_prompt(model, sent, shown, tools, tool_choice, escalations),
        offered,
        conversation,
    )


class Prompt(NamedTuple):
    """A whole turn or a request, as the arguments a human approver takes."""

    message: str
    call: ToolCall
    view: ToolCallView
    said: str | None = None
    """What the operator's notification says when `message` is empty: the turn's text, which the view holds, or a line that says a request waits. None when `message` carries it."""


async def _ask_with(
    approve: Approver,
    prompt: Prompt,
    offered: list[ApprovalDecision],
    conversation: list[ChatMessage],
) -> Approval:
    # deferred: the ACP shim imports `acp.schema`, which only matters once a
    # person is asked
    from inspect_ai.approval._human.acp import finish_approval_card

    status: Literal["completed", "failed"] = "failed"
    try:
        if prompt.said is not None:
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
        # no tool event completes the card the prompt opened; a prompt that
        # ended without one of the choices failed
        finish_approval_card(prompt.call, prompt.view, status)


def request_prompt(
    model: str,
    sent: int,
    shown: Sequence[tuple[int, ChatMessage]],
    tools: Sequence[str],
    tool_choice: ToolChoice,
    escalations: Sequence[tuple[str, str | None]],
) -> Prompt:
    """The request a model is about to be sent, as one prompt for the human approval surfaces.

    The surfaces show one tool call, so the request becomes a single view, as
    a turn does in `turn_prompt`: the escalations, how many messages the
    request sends, the tools it offers and which the model must call, then
    each message the model has not been sent before, numbered by its place in
    the request.

    The view has to stand on its own. The console and the approval panel show
    none of the conversation, so a message that is not in the view is one the
    person can't read here. That is why the messages shown are those not sent
    before, and not only those after the model's last turn: a message the
    scaffold rewrote, and words it put in the model's mouth, are shown too.
    What the view leaves out is said in it: how many messages were sent
    before, and how many parts of a message are not shown.

    A message can hold a tool's output or a document the agent read, so its
    text is untrusted, as a turn's is, and gets the same treatment. Each
    message's text is inside a code block it cannot close, everything outside
    the blocks is written here, and characters that act rather than show are
    shown as markers.

    The call handed to the surfaces stands for the whole request, as a turn's
    does.
    """
    safe = _Escaped()
    blocks: list[str] = []
    if escalations:
        escalated = safe(escalation_lines(escalations))
        blocks.append(f"**Escalated by**\n\n{_code_block(escalated, _SAID)}")
    shown_blocks = [
        _message_markdown(message, position, sent, safe) for position, message in shown
    ]
    before = sent - len(shown)
    if before == 0:
        which = "none of which the model was sent before"
    elif not shown:
        which = "all of which the model was sent before"
    else:
        which = (
            f"{before} of which the model was sent before. "
            f"The other {len(shown)} {'is' if len(shown) == 1 else 'are'} below"
        )
    count = (
        f"**The request sends {_messages(sent)} to "
        f"{_markdown_text(model, safe)}, {which}.**"
    )
    count = f"{count}\n\n**{_tools_offered(tools, tool_choice, safe)}**"
    if safe.escaped:
        count = f"{count}\n\n**{_ESCAPED_REQUEST_NOTICE}**"
    blocks.append(count)
    blocks.extend(shown_blocks)
    stands_for_request = ToolCall(
        id=f"request_{shortuuid()}",
        function=(f"Model request: {_messages(sent)} ({len(shown)} not sent before)"),
        arguments={},
    )
    view = ToolCallView(
        call=ToolCallContent(format="markdown", content="\n\n---\n\n".join(blocks))
    )
    waiting = (
        f"A request to {model} waits for a decision: {stands_for_request.function}."
    )
    return Prompt("", stands_for_request, view, waiting)


def _messages(count: int) -> str:
    return "1 message" if count == 1 else f"{count} messages"


def _tools_offered(
    tools: Sequence[str], tool_choice: ToolChoice, safe: "_Escaped"
) -> str:
    # The tools the request offers, and which the model is to call. Each name
    # is counted and in a code span, so it can't pass for two tools or for the
    # words around it. A function the model must call is told from the three
    # words by its type, since a tool can be named `auto`, `any` or `none`.
    forced = isinstance(tool_choice, ToolFunction)
    if isinstance(tool_choice, ToolFunction):
        choice = (
            f"The model must call the function {_code_span(tool_choice.name, safe)}."
        )
    elif tool_choice == "auto":
        choice = "The model may call any of them, or none."
    elif tool_choice == "any":
        choice = "The model must call one of them."
    else:
        choice = "The model may call none of them."
    if not tools:
        # a call the model is forced to make is said even with no tool to make it
        return f"No tools are offered.{' ' + choice if forced else ''}"
    offered = ", ".join(_code_span(name, safe) for name in tools)
    return f"Tools offered ({len(tools)}): {offered}. {choice}"


def _message_markdown(
    message: ChatMessage, position: int, sent: int, safe: "_Escaped"
) -> str:
    """One message: a header written here, then what it says in code blocks.

    A tool's message is named for its function, and shows its error and its
    output when it has both. An assistant message also shows its reasoning and
    each call it makes, as a turn does. Any other content, such as an image or
    a tool the provider ran, is counted beneath, never rendered.
    """
    header = f"**Message {position} of {sent}:** {message.role}"
    if isinstance(message, ChatMessageTool) and message.function:
        header = f"{header} ({_markdown_text(message.function, safe)})"
    text = message.text
    error = message.error if isinstance(message, ChatMessageTool) else None
    if error is not None:
        header = f"{header}, an error"
    parts = [header]
    shown_types = {"text"}
    if isinstance(message, ChatMessageAssistant):
        shown_types.add("reasoning")
        reasoned = _reasoning(message)
        if reasoned.readable:
            thought = safe("\n\n".join(reasoned.readable))
            parts.append(f"**Its reasoning**\n\n{_code_block(thought, _SAID)}")
        if reasoned.withheld:
            parts.append(
                f"**The provider withheld the text of {reasoned.withheld} "
                f"{'block' if reasoned.withheld == 1 else 'blocks'} of its reasoning.**"
            )
    if error is not None:
        # a provider sends the model the error or the output, so both are shown
        parts.append(_code_block(safe(error.message), _SAID))
        if text:
            output = _code_block(safe(text), _SAID)
            parts.append(f"**The tool's output**\n\n{output}")
    elif text:
        parts.append(_code_block(safe(text), _SAID))
    calls = (
        message.tool_calls if isinstance(message, ChatMessageAssistant) else None
    ) or []
    if calls:
        parts.append(f"**It makes {_calls(len(calls))}.**")
        parts.extend(
            _call_markdown(call, index, len(calls), safe, _SAID)
            for index, call in enumerate(calls, 1)
        )
    content = message.content
    other = (
        sum(1 for part in content if part.type not in shown_types)
        if isinstance(content, list)
        else 0
    )
    if other:
        parts.append(
            f"**{other} {'part' if other == 1 else 'parts'} of this message "
            f"{'is' if other == 1 else 'are'} not shown: content that is not "
            "text, or a tool the provider ran.**"
        )
    return "\n\n".join(parts)


async def approve_with_text_in_view(
    approve: Approver,
    said: str,
    call: ToolCall,
    view: ToolCallView,
    conversation: list[ChatMessage],
) -> Approval:
    """Ask a person with a view that already holds what is asked about.

    The prompt's message is empty, so that no surface shows the text twice.
    The human approver notifies the operator with the message, so `said` is
    sent from here instead and the approver's own notification is turned off:
    the operator is told what a turn that reached Inspect would have told them.

    Args:
        approve: The human approver to ask with.
        said: What the notification says: the turn's text, or a line that says
            a request waits.
        call: The call to ask about.
        view: The view, which holds the text.
        conversation: The conversation to give the approval surface.
    """
    await notify(said)
    with apprise_scope(None):
        return await approve("", call, view, conversation)


def turn_prompt(
    turn: ChatMessageAssistant | None,
    escalations: Sequence[tuple[str, str | None]],
    content_in_view: bool = False,
) -> Prompt:
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
    if content_in_view:
        return Prompt("", stands_for_turn, view, text)
    return Prompt(text, stands_for_turn, view)


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
            head = f"{head} {markdown_escaped(self.name)}"
        return head if self.body is None else f"{head}\n\n{fenced(self.body)}"


class _Reasoning(NamedTuple):
    """An assistant message's reasoning, as a person can read it."""

    readable: list[str]
    """The text of each block that has some."""

    withheld: int
    """How many blocks have no text a person can read."""


def _reasoning(message: ChatMessageAssistant) -> _Reasoning:
    # As the transcript shows it: a provider may return reasoning encrypted,
    # with a summary, or with nothing readable.
    readable: list[str] = []
    withheld = 0
    content = message.content if isinstance(message.content, list) else []
    for block in content:
        if isinstance(block, ContentReasoning):
            thought = (
                block.summary if block.redacted else (block.reasoning or block.summary)
            )
            if thought:
                readable.append(thought)
            else:
                withheld += 1
    return _Reasoning(readable, withheld)


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
    readable, withheld = _reasoning(turn)
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


_ESCAPED_REQUEST_NOTICE = (
    "This request contains hidden or control characters, "
    f"shown as {MARKER_OPEN}U+…{MARKER_CLOSE}."
)

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


def _call_markdown(
    call: ToolCall, index: int, count: int, safe: _Escaped, text_label: str = ""
) -> str:
    """One call: a header written here, then its content as a code block.

    The content is what the transcript shows (`ToolCall.view`, which
    `Model.generate` sets from the tool's viewer, or the default rendering),
    with the call's placeholders filled in (see `_contained`). `text_label`
    labels the block of content that has no language of its own. A view other
    than the call's default view is followed by the call's arguments, as a
    call's own approval shows them (see `arguments_view`).
    """
    view = call.view or cast(ToolCallContent, default_tool_call_viewer(call).call)
    content = substitute_tool_call_content(view, call.arguments)
    header = f"**Call {index} of {count}:** {_markdown_text(call.function, safe)}"
    if content.title and content.title != call.function:
        header = f"{header} ({_markdown_text(content.title, safe)})"
    shown = f"{header}\n\n{_contained(content, safe, text_label)}"
    arguments = arguments_view(call, ToolCallView(call=view))
    if arguments is not None:
        shown = f"{shown}\n\n**Full tool call**\n\n{_contained(arguments, safe)}"
    return shown


def _contained(
    content: ToolCallContent, safe: Callable[[str], str], text_label: str = ""
) -> str:
    """What a tool's viewer made, as one code block it cannot close.

    Viewers interpolate arguments into markdown unescaped, so an argument could
    close the viewer's code fence and write a label of the view, or open an
    HTML comment that swallows what follows. A viewer's single code block keeps
    its language and is fenced again by a fence longer than any backtick run in
    it. Any other content is shown as source.

    Args:
        content: The viewer's content, with the call's placeholders filled in.
        safe: Makes text an agent wrote safe to display.
        text_label: The label of the block when the content is plain text.
    """
    block = _CODE_BLOCK.fullmatch(content.content)
    if content.format == "markdown" and block is not None:
        language, code = block.group("language").strip(), block.group("code")
    else:
        language = "markdown" if content.format == "markdown" else text_label
        code = content.content
    return _code_block(safe(code), language)


# a viewer's single fenced code block, e.g. `code_viewer`'s and the default's
_CODE_BLOCK = re.compile(
    r"(?P<fence>`{3,})(?P<language>[\w+.-]*)\n(?P<code>.*)\n(?P=fence)[ \t]*\n?",
    re.DOTALL,
)


# The label of a code block that holds what a message says. The ACP TUI draws
# a labelled block on a background, and an unlabelled one as plain text, where
# a tool's output could pass for the view's own lines.
_SAID = "output"


def _code_block(code: str, language: str) -> str:
    fence = safe_code_fence(code)
    return f"{fence}{language}\n{code}\n{fence}"


def _code_span(text: str, safe: _Escaped) -> str:
    # one line of literal text, in a code span it cannot close
    line = _one_line(text, safe)
    longest = max((len(run) for run in re.findall("`+", line)), default=0)
    ticks = "`" * (longest + 1)
    return f"{ticks} {line} {ticks}"


def _markdown_text(text: str, safe: _Escaped) -> str:
    # one line of literal text: markdown punctuation escaped, so a function
    # name or viewer title cannot add structure
    return markdown_escaped(_one_line(text, safe))


def _one_line(text: str, safe: _Escaped) -> str:
    return " ".join(safe(text).split())
