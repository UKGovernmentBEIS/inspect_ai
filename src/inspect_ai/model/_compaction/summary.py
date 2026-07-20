from textwrap import dedent
from typing import Any, NamedTuple

from typing_extensions import override

from inspect_ai._util.content import (
    Content,
    ContentAudio,
    ContentDocument,
    ContentImage,
    ContentText,
    ContentVideo,
)
from inspect_ai._util.list import find_last_match
from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool, ChatMessageUser
from inspect_ai.model._model import Model, get_model
from inspect_ai.model._model_info import get_model_input_tokens
from inspect_ai.model._tokens import count_media_tokens
from inspect_ai.model._trim import partition_messages
from inspect_ai.tool._tool_info import ToolInfo

from .memory import has_memory_calls
from .types import CompactionStrategy


class CompactionSummary(CompactionStrategy):
    """Conversation summary compaction.

    Compact messages by summarizing the conversation.
    """

    def __init__(
        self,
        *,
        threshold: int | float = 0.9,
        memory: bool = True,
        model: str | Model | None = None,
        instructions: str | None = None,
        prompt: str | None = None,
    ):
        """Conversation summary compaction.

        Args:
            threshold: Token count or percent of context window to trigger compaction.
            memory: Warn the model to save critical content to memory prior
                to compaction when the memory tool is available.
            model: Model to use for summarization (defaults to compaction target model).
            instructions: Additional instructions to give the model about compaction
                (e.g. "Focus on preserving code snippets, variable names, and technical decisions.").
                These instructions will be inserted into the `prompt`.
            prompt: Prompt to use for summarization (fully replaces the summarization prompt).
                Include an `{addendums}` placeholder in your prompt to include custom
                `instructions` and a prompt to use the `memory()` tool when its available.
        """
        super().__init__(type="summary", threshold=threshold, memory=memory)
        self.model = get_model(model) if model is not None else model
        self.instructions = instructions
        self.prompt = prompt or self.DEFAULT_SUMMARY_PROMPT

    @override
    def _repr_params_(self) -> dict[str, Any]:
        params = super()._repr_params_()
        params.update(
            {
                "model": self.model.name if self.model is not None else None,
                "instructions": self.instructions,
                "prompt": self.prompt,
            }
        )
        return params

    @override
    async def compact(
        self, model: Model, messages: list[ChatMessage], tools: list[ToolInfo]
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        """Compact messages by summarizing the conversation.

        Args:
            model: Target model for compaction.
            messages: Full message history
            tools: Available tools

        Returns: Input to present to the model and (optionally) a message to append to the history (e.g. a summarization).
        """
        # partition messages into 'system', 'input', and 'conversation'
        partitioned = partition_messages(messages)

        # if there is an existing summary in the 'conversation' then take only
        # the summary and subsequent messages
        conversation_start_index = (
            find_last_match(
                partitioned.conversation, lambda m: "summary" in (m.metadata or {})
            )
            or 0
        )

        # create addendums
        addendums: list[str] = []
        if self.instructions is not None:
            addendums.append(self.instructions)

        if self.memory and has_memory_calls(partitioned.conversation):
            addendums.append(self.MEMORY_SUMMARY_ADDENDUM)

        # build summarization input: system + input + conversation + prompt
        prompt = self.prompt.format(addendums="\n\n".join(addendums))
        summarization_input: list[ChatMessage] = (
            partitioned.system
            + partitioned.input
            + partitioned.conversation[conversation_start_index:]
            + [ChatMessageUser(content=prompt)]
        )

        # use model explicitly passed to us or fall back to compaction model
        model = self.model or model

        # a long tool output right before compaction can push the summarization
        # input past the model's context window; truncate it so the summary
        # generate below doesn't itself overflow
        summarization_input = await _fit_summarization_input(model, summarization_input)

        # perform summary
        output = await model.generate(input=summarization_input)
        if output.stop_reason == "model_length":
            raise RuntimeError(
                "Compaction summary generation exceeded the model's context "
                "window (tool output is truncated automatically to fit, so the "
                "overflow comes from content that truncation cannot reach). "
                "Consider lowering the compaction threshold."
            )

        # create summary message
        summary = ChatMessageUser(
            content=(
                f"[CONTEXT COMPACTION SUMMARY]\n\n"
                f"The following is a summary of work completed on this task so far:\n\n"
                "<summary>\n"
                f"{output.completion}\n"
                "</summary>\n\n"
                f"Please continue working on this task from where you left off."
            ),
            metadata={"summary": True},
        )

        # input for model should be preamble + summary
        input = partitioned.system + partitioned.input + [summary]
        return input, summary

    DEFAULT_SUMMARY_PROMPT = dedent("""
    You have been working on the task described above but have not yet completed it. Write a continuation summary that will allow you (or another instance of yourself) to resume work efficiently in a future context window where the conversation history will be replaced with this summary. Your summary should be structured, concise, and actionable. Include:

    - Task Overview
    The user's core request and success criteria
    Any clarifications or constraints they specified

    - Current State
    What has been completed so far
    Files created, modified, or analyzed (with paths if relevant)
    Key outputs or artifacts produced

    - Important Discoveries
    Technical constraints or requirements uncovered
    Decisions made and their rationale
    Errors encountered and how they were resolved
    What approaches were tried that didn't work (and why)

    - Next Steps
    Specific actions needed to complete the task
    Any blockers or open questions to resolve
    Priority order if multiple steps remain

    - Context to Preserve
    User preferences or style requirements
    Domain-specific details that aren't obvious
    Any promises made to the user
    {addendums}

    Be concise but complete—err on the side of including information that would prevent duplicate work or repeated mistakes. Write in a way that enables immediate resumption of the task.
    """)

    MEMORY_SUMMARY_ADDENDUM = dedent("""
    - Memory Files
    List any files you saved to memory during this conversation.
    For each file, include the path and a brief description of what
    information it contains and when to reference it.
    """)


# maximum passes when shrinking oversized tool output to fit the window
_MAX_TRUNCATION_ITERATIONS = 12

# marker left in place of tool output elided to fit the summarization window
_TRUNCATION_MARKER = "\n\n...[tool output truncated for summarization]...\n\n"

# output headroom to reserve when the model's max_tokens cannot be determined
_DEFAULT_OUTPUT_RESERVE = 4096

# approximate characters per token, for weighing media against text content
_CHARS_PER_TOKEN = 4


async def _fit_summarization_input(
    model: Model, messages: list[ChatMessage]
) -> list[ChatMessage]:
    """Shrink oversized tool output so the summarization input fits the window.

    A long tool output immediately preceding compaction can push the
    summarization input past the summarization model's context window, so that
    the summary `generate()` itself overflows — crashing the run, or (on
    providers that report overflow as `stop_reason="model_length"` with the
    error text as content) silently turning that error text into the summary.
    Shrink the largest pieces of tool output — middle-truncating text parts and
    replacing media parts with a text placeholder — until the input fits, so
    summarization can proceed.

    The fit target reserves output headroom below the context window because
    providers that send an explicit `max_tokens` reject requests whose input
    and output budget together exceed the window.

    Returns the input unchanged when the context window is unknown or the input
    already fits. Edited messages are replaced with copies so the live
    transcript is left untouched.
    """
    context_window = get_model_input_tokens(model)
    if context_window is None:
        return messages

    target = context_window - _output_reserve(model, context_window)
    tokens = await model.count_tokens(messages)
    if tokens <= target:
        return messages

    messages = list(messages)
    for _ in range(_MAX_TRUNCATION_ITERATIONS):
        candidate = _largest_shrinkable(messages)
        if candidate is None:
            break
        _shrink(messages, candidate)
        shrunk_tokens = await model.count_tokens(messages)
        if shrunk_tokens >= tokens:
            break
        tokens = shrunk_tokens
        if tokens <= target:
            break

    return messages


def _output_reserve(model: Model, context_window: int) -> int:
    """Tokens to reserve for the summary output when fitting the input.

    Mirrors the `max_tokens` resolution in `Model.generate()` (explicit config,
    then provider defaults), capped at half the window so that small-window
    models keep room for input.
    """
    max_tokens = (
        model.config.max_tokens
        or model.api.max_tokens_for_config(model.config)
        or model.api.max_tokens()
        or _DEFAULT_OUTPUT_RESERVE
    )
    return min(max_tokens, context_window // 2)


class _ShrinkCandidate(NamedTuple):
    """A piece of tool output (one content part) that shrinking would reduce."""

    message_index: int
    part_index: int
    weight: int
    """Estimated size in characters (media weighed via its token estimate)."""


def _largest_shrinkable(messages: list[ChatMessage]) -> _ShrinkCandidate | None:
    """Find the largest shrinkable content part across all tool messages.

    Media parts are always shrinkable (they collapse to a placeholder); text
    parts only when they are large enough for middle-truncation to make
    progress. Media is weighed by its estimated token cost so that it competes
    with text on a common scale; the estimate only orders the shrinking, the
    caller's token count decides when the input actually fits.
    """
    candidates: list[_ShrinkCandidate] = []
    for message_index, message in enumerate(messages):
        if not isinstance(message, ChatMessageTool):
            continue
        for part_index, part in enumerate(message.content_list):
            if isinstance(part, ContentText):
                if len(part.text) // 2 > len(_TRUNCATION_MARKER):
                    candidates.append(
                        _ShrinkCandidate(message_index, part_index, len(part.text))
                    )
            elif isinstance(
                part, (ContentImage, ContentAudio, ContentVideo, ContentDocument)
            ):
                candidates.append(
                    _ShrinkCandidate(
                        message_index,
                        part_index,
                        count_media_tokens(part) * _CHARS_PER_TOKEN,
                    )
                )
    return max(candidates, key=lambda c: c.weight, default=None)


def _shrink(messages: list[ChatMessage], candidate: _ShrinkCandidate) -> None:
    """Shrink the candidate part, replacing its message with an edited copy.

    Text parts are middle-truncated to half their size; media parts are
    replaced with a text placeholder (the summarizer doesn't need the media
    itself, only the fact that the tool returned it). Parts are edited at
    their index so the structure and ordering of the message content is
    preserved. The original message and its parts are never mutated.
    """
    message = messages[candidate.message_index]
    content: str | list[Content]
    if isinstance(message.content, str):
        content = _truncate_middle(message.content, len(message.content) // 2)
    else:
        content = list(message.content)
        part = content[candidate.part_index]
        if isinstance(part, ContentText):
            part = ContentText(text=_truncate_middle(part.text, len(part.text) // 2))
        else:
            part = ContentText(text=f"[{part.type} elided for summarization]")
        content[candidate.part_index] = part
    messages[candidate.message_index] = message.model_copy(update={"content": content})


def _truncate_middle(text: str, max_bytes: int) -> str:
    """Middle-truncate `text` to about `max_bytes`, marking the elided region.

    Keeps the head and tail (where tool output is most informative) and drops
    the middle, splitting at byte offsets so the marker sits exactly at the
    elision seam. Re-truncation discards a previous marker because it sits in
    the elided middle. Returns the text unchanged when it already fits or when
    `max_bytes` leaves no room for the marker.
    """
    budget = max_bytes - len(_TRUNCATION_MARKER)
    if budget <= 0:
        return text
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= budget:
        return text
    front = encoded[: budget // 2].decode("utf-8", errors="replace")
    back = encoded[len(encoded) - (budget - budget // 2) :].decode(
        "utf-8", errors="replace"
    )
    return front + _TRUNCATION_MARKER + back
