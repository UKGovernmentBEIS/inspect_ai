import abc
from textwrap import dedent
from typing import Protocol

from shortuuid import uuid
from typing_extensions import override

from inspect_ai._util.list import find_last_match
from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool, ChatMessageUser
from inspect_ai.model._model import Model, get_model
from inspect_ai.model._trim import partition_messages, trim_messages


class CompactionStrategy(abc.ABC):
    """Compaction strategy."""

    def __init__(self, *, threshold: int):
        self.threshold = threshold

    threshold: int
    """Token count threshold for compaction."""

    @abc.abstractmethod
    async def compact(
        self, messages: list[ChatMessage]
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        """Compact messages.

        Args:
            messages: Full message history.

        Returns: Input to present to the model and (optionally) a message to append to the history (e.g. a summarization).
        """
        ...


class CompactionEdit(CompactionStrategy):
    """Message editing compaction.

    Compact messages by editing the history to remove tool call results. Tool results receive placeholder to indicate that the result was removed.
    """

    def __init__(self, *, threshold: int = 100_000):
        super().__init__(threshold=threshold)

    @override
    async def compact(
        self, messages: list[ChatMessage]
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        """Compact messages by removing tool call results.

        Args:
            messages: Full message history

        Returns: Input to present to the model and (optionally) a message to append to the history (e.g. a summarization).
        """
        compacted: list[ChatMessage] = []
        for message in messages:
            if isinstance(message, ChatMessageTool):
                compacted.append(
                    message.model_copy(
                        update={"id": uuid(), "content": "(Tool result removed)"}
                    )
                )
            else:
                compacted.append(message)
        return compacted, None


class CompactionTrim(CompactionStrategy):
    """Message trimming compaction.

    Compact messages by trimming the history to preserve a percentage of messages:
    - Retain all system messages.
    - Retain the 'input' messages from the sample.
    - Preserve a proportion of the remaining messages (`preserve=0.8` by default).
    - Ensure that all assistant tool calls have corresponding tool messages.
    - Ensure that the sequence of messages doesn't end with an assistant message.
    """

    def __init__(self, *, threshold: int = 100_000, preserve: float = 0.8):
        super().__init__(threshold=threshold)
        self.preserve = preserve

    preserve: float
    """Ratio of conversation messages to preserve (defaults to 0.8)"""

    @override
    async def compact(
        self, messages: list[ChatMessage]
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        """Compact messages by trimming the history to preserve a percentage of messages.

        Args:
            messages: Full message history

        Returns: Input to present to the model and (optionally) a message to append to the history (e.g. a summarization).
        """
        return await trim_messages(messages, preserve=self.preserve), None


class CompactionSummary(CompactionStrategy):
    """Conversation summary compaction.

    Compact messages by summarizing the conversation.
    """

    def __init__(
        self,
        *,
        threshold: int = 100_000,
        prompt: str | None = None,
        model: str | Model | None = None,
    ):
        super().__init__(threshold=threshold)
        self.prompt = prompt or self.DEFAULT_SUMMARY_PROMPT
        self.model = get_model(model)

    prompt: str
    """Prompt to use for summarization."""

    model: Model
    """Model to use for summarization."""

    @override
    async def compact(
        self, messages: list[ChatMessage]
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        """Compact messages by summarizing the conversation.

        Args:
            messages: Full message history

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
        summarization_input: list[ChatMessage] = (
            partitioned.system
            + partitioned.input
            + partitioned.conversation[conversation_start_index:]
            + [ChatMessageUser(content=self.prompt)]
        )

        # perform summary
        output = await self.model.generate(input=summarization_input)

        # create summary message
        summary = ChatMessageUser(
            content=f"[CONTEXT COMPACTION SUMMARY]\n\n{output.completion}",
            metadata={"summary": True},
        )

        # input for model should be preamble + summary
        input = partitioned.system + partitioned.input + [summary]
        return input, summary

    DEFAULT_SUMMARY_PROMPT = dedent("""
    You will be summarizing the conversation above to create a handoff document that allows work to continue seamlessly. The summary needs to capture all critical information required to pick up where the conversation left off, as the conversation history will be discarded after this summary.

    Your task is to create a comprehensive summary that focuses on preserving actionable information. Structure your summary to include the following elements:

    **What we're trying to accomplish:**
    - Clearly state the main goal or objective of the work
    - Include any sub-goals or related tasks that were identified

    **Actions taken and their results:**
    - List the steps that were attempted or completed
    - Note the outcome of each action (success, failure, partial completion)
    - Include any commands run, functions called, or operations performed IF THEY ARE IMPORTANT TO SOLVING THE PROBLEM.

    **Key findings and technical details:**
    - File paths, directory structures, or locations referenced
    - Specific values, parameters, or configuration settings discovered or used
    - Error messages (include the full text if important for debugging)
    - Code snippets or configuration blocks that are critical to understanding the current state
    - Data structures, variable names, or API endpoints involved
    - Any constraints, limitations, or requirements identified

    **Current state:**
    - Where things stand now
    - What's working and what isn't
    - Any blockers or issues that need resolution

    **What to do next:**
    - Clear next steps or recommendations
    - Outstanding questions that need answers
    - Alternative approaches to consider if applicable

    When writing your summary:
    - Be verbose enough to preserve all critical details needed to continue the work
    - Be concise with background information or non-essential context
    - Use specific technical terminology, exact names, and precise values rather than generalizations
    - If there are important code snippets, error messages, or configuration details, include them verbatim
    - Organize information logically so someone can quickly understand the situation and take action
    - Assume the person reading this summary was not part of the original conversation
    Please output the complete summary. The summary should be self-contained and actionable, allowing work to continue effectively from this point.""")


class Compact(Protocol):
    async def __call__(
        self, messages: list[ChatMessage]
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        """Compact messages.

        Args:
            messages: Full message history

        Returns: Input to present to the model and (optionally) a message to append to the history (e.g. a summarization).
        """
        ...


def compaction(
    strategy: CompactionStrategy,
    prefix: list[ChatMessage],
    model: str | Model | None = None,
) -> Compact:
    """Create a conversation compaction handler.

    Call the `Compact` handler with the full conversation history before sending input to the model. Send the returned `input` and append the supplemental message returned (if any) to the full history.

    For example, in a simple agent loop:

    ```python
    compact = compaction(CompactionTrim(), prefix=state.messages)

    while True:
        # perform compaction
        input, message = await compact(state.messages)
        if message:
            state.messages.append(message)

        # call model and append to messages
        state.output = await get_model().generate(
            input=input,
            tools=tools,
        )
        state.messages.append(state.output.message)

        # make tool calls or terminate if there are none
        if state.output.message.tool_calls:
            messages, state.output = await execute_tools(
                state.messages, tools
            )
            state.messages.extend(messages)
        else:
            break
    ```

    Note: The returned handler maintains internal state and is designed for sequential use within a single conversation's agent loop. Do not call concurrently.

    Args:
        strategy: Compaction strategy (e.g. editing, trimming, summary, etc.)
        prefix: Chat messages to always preserve in compacted conversations.
        model: Target model for compacted input (defaults to active model).

    Returns:
        `Compact` function which takes a full message history and returns the
        Input to present to the model and (optionally) a message to append to
        the history (e.g. a summarization).
    """
    # state: compacted input to send to the model
    input: list[ChatMessage] = []

    # state: IDs of messages we've already processed (added to input)
    processed_message_ids: set[str] = set()

    # state: cache of message_id -> token_count
    token_count_cache: dict[str, int] = {}

    # resolve target model
    target_model = get_model(model)

    # helper to get message ID (assert away id == None)
    def message_id(message: ChatMessage) -> str:
        assert message.id is not None
        return message.id

    # count tokens with caching
    async def count_tokens(message: ChatMessage) -> int:
        # check cache
        id = message_id(message)
        count = token_count_cache.get(id, None)
        if count is not None:
            return count

        # count tokens and update cache
        count = await target_model.count_tokens(message)
        token_count_cache[id] = count

        # return count
        return count

    async def compact(
        messages: list[ChatMessage],
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        # determine unprocessed messages (messages not yet added to input).
        # we allow unprocessed messages to accumulate in the input until
        # the compaction 'threshold' is reached.
        unprocessed: list[ChatMessage] = [
            m for m in messages if message_id(m) not in processed_message_ids
        ]

        # check to see whether the tokens exceeds the compaction 'threshold'
        total_tokens = sum([await count_tokens(m) for m in (input + unprocessed)])
        if total_tokens > strategy.threshold:
            # perform compaction
            c_input, c_message = await strategy.compact(input + unprocessed)

            # track all messages that were processed in this compaction pass
            for m in input + unprocessed:
                processed_message_ids.add(message_id(m))

            # c_message is a compaction side effect to append to the history
            # (e.g. a summary). track it as processed as well
            if c_message is not None:
                processed_message_ids.add(message_id(c_message))

            # ensure we preserve the prefix (could have been wiped out by a summarization)
            input_ids = set([m.id for m in c_input])
            prepend_prefix = [m for m in prefix if m.id not in input_ids]
            c_input = prepend_prefix + c_input

            # update input
            input.clear()
            input.extend(c_input)

            # return input and any extra message to append
            return list(c_input), c_message

        else:
            # track unprocessed messages as now processed
            for m in unprocessed:
                processed_message_ids.add(message_id(m))

            # extend input with unprocessed messages
            input.extend(unprocessed)

            # return
            return list(input), None

    return compact
