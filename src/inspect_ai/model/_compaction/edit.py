from shortuuid import uuid
from typing_extensions import override

from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool, ChatMessageUser

from .types import CompactionStrategy


class CompactionEdit(CompactionStrategy):
    """Message editing compaction.

    Compact messages by editing the history to remove tool call results. Tool results receive placeholder to indicate that the result was removed.
    """

    def __init__(self, threshold: int | float = 0.9):
        """Message editing compaction.

        Args:
            threshold: Token count or percent of context window to trigger compaction.
        """
        super().__init__(threshold)

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
