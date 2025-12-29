from textwrap import dedent

from typing_extensions import override

from inspect_ai._util.list import find_last_match
from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._model import Model, get_model
from inspect_ai.model._trim import partition_messages

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
        prompt: str | None = None,
    ):
        """Conversation summary compaction.

        Args:
            threshold: Token count or percent of context window to trigger compaction.
            memory: Warn the model to save critical content to memory prior
                to compaction when the memory tool is available.
            model: Model to use for summarization (defaults to compaction target model).
            prompt: Prompt to use for summarization.
        """
        super().__init__(threshold=threshold, memory=memory)
        self.model = get_model(model) if model is not None else model
        self.prompt = prompt or self.DEFAULT_SUMMARY_PROMPT

    @override
    async def compact(
        self, messages: list[ChatMessage], model: Model
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        """Compact messages by summarizing the conversation.

        Args:
            messages: Full message history
            model: Target model for compation.

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

        # build summarization input: system + input + conversation + prompt
        prompt = self.prompt
        if self.memory and has_memory_calls(partitioned.conversation):
            prompt = prompt + self.MEMORY_SUMMARY_ADDENDUM

        summarization_input: list[ChatMessage] = (
            partitioned.system
            + partitioned.input
            + partitioned.conversation[conversation_start_index:]
            + [ChatMessageUser(content=prompt)]
        )

        # use model explicitly passed to us or fall back to compation model
        model = self.model or model

        # perform summary
        output = await model.generate(input=summarization_input)

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

    1. Task Overview
    The user's core request and success criteria
    Any clarifications or constraints they specified

    2. Current State
    What has been completed so far
    Files created, modified, or analyzed (with paths if relevant)
    Key outputs or artifacts produced

    3. Important Discoveries
    Technical constraints or requirements uncovered
    Decisions made and their rationale
    Errors encountered and how they were resolved
    What approaches were tried that didn't work (and why)

    4. Next Steps
    Specific actions needed to complete the task
    Any blockers or open questions to resolve
    Priority order if multiple steps remain

    5. Context to Preserve
    User preferences or style requirements
    Domain-specific details that aren't obvious
    Any promises made to the user

    Be concise but complete—err on the side of including information that would prevent duplicate work or repeated mistakes. Write in a way that enables immediate resumption of the task.
    """)

    MEMORY_SUMMARY_ADDENDUM = dedent("""
    6. Memory Files
    List any files you saved to memory during this conversation.
    For each file, include the path and a brief description of what
    information it contains and when to reference it.
    """)
