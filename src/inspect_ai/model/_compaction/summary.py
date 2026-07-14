from textwrap import dedent
from typing import Any

from typing_extensions import override

from inspect_ai._util.list import find_last_match
from inspect_ai._util.text import truncate_string_to_bytes
from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool, ChatMessageUser
from inspect_ai.model._model import Model, get_model
from inspect_ai.model._model_info import get_model_input_tokens
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
        if output.stop_reason == "model_length" or output.error is not None:
            raise RuntimeError(
                "Compaction summary generation exceeded the model's context "
                "window. Consider lowering the compaction threshold or reducing "
                "the maximum tool output size (max_tool_output)."
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


async def _fit_summarization_input(
    model: Model, messages: list[ChatMessage]
) -> list[ChatMessage]:
    """Truncate oversized tool output so the summarization input fits the window.

    A long tool output immediately preceding compaction can push the
    summarization input past the summarization model's context window, so that
    the summary `generate()` itself overflows — crashing the run, or (on
    providers that report overflow as `stop_reason="model_length"` with the
    error text as content) silently turning that error text into the summary.
    Truncate the largest tool messages until the input fits, so summarization
    can proceed.

    Returns the input unchanged when the context window is unknown or the input
    already fits. Edits are made on copies so the transcript is left untouched.
    """
    context_window = get_model_input_tokens(model)
    if context_window is None:
        return messages

    if await model.count_tokens(messages) <= context_window:
        return messages

    # edit copies of the tool messages so the live transcript is left untouched
    messages = [
        m.model_copy(deep=True) if isinstance(m, ChatMessageTool) else m
        for m in messages
    ]

    for _ in range(_MAX_TRUNCATION_ITERATIONS):
        largest = max(
            (m for m in messages if isinstance(m, ChatMessageTool) and m.text),
            key=lambda m: len(m.text),
            default=None,
        )
        if largest is None:
            break
        largest.text = _truncate_middle(largest.text, len(largest.text) // 2)
        if await model.count_tokens(messages) <= context_window:
            break

    return messages


def _truncate_middle(text: str, max_bytes: int) -> str:
    """Middle-truncate `text` to about `max_bytes`, marking the elided region.

    Keeps the head and tail (where tool output is most informative) and drops
    the middle. Re-truncation discards a previous marker because it sits in the
    elided middle.
    """
    # reserve room for the marker so the result stays within max_bytes and
    # successive truncations converge
    budget = max_bytes - len(_TRUNCATION_MARKER)
    truncated = truncate_string_to_bytes(text, budget) if budget > 0 else None
    if truncated is None:
        return text
    half = len(truncated.output) // 2
    return truncated.output[:half] + _TRUNCATION_MARKER + truncated.output[half:]
