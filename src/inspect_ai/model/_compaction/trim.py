from typing_extensions import override

from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._model import Model
from inspect_ai.model._trim import trim_messages

from .types import CompactionStrategy


class CompactionTrim(CompactionStrategy):
    """Message trimming compaction.

    Compact messages by trimming the history to preserve a percentage of messages:
    - Retain all system messages.
    - Retain the 'input' messages from the sample.
    - Preserve a proportion of the remaining messages (`preserve=0.8` by default).
    - Ensure that all assistant tool calls have corresponding tool messages.
    - Ensure that the sequence of messages doesn't end with an assistant message.
    """

    def __init__(self, *, threshold: int | float = 0.9, preserve: float = 0.8):
        """Message trimming compaction.

        Args:
            threshold: Token count or percent of context window to trigger compaction.
            preserve: Ratio of conversation messages to preserve (defaults to 0.8).
        """
        super().__init__(threshold=threshold)
        self.preserve = preserve

    @override
    async def compact(
        self, messages: list[ChatMessage], model: Model
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        """Compact messages by trimming the history to preserve a percentage of messages.

        Args:
            messages: Full message history
            model: Target model for compation.

        Returns: Input to present to the model and (optionally) a message to append to the history (e.g. a summarization).
        """
        return await trim_messages(messages, preserve=self.preserve), None
