import abc
from typing import Protocol

from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._model import Model


class CompactionStrategy(abc.ABC):
    """Compaction strategy."""

    def __init__(
        self,
        threshold: int | float = 0.9,
        memory: bool = True,
        preserve_prefix_user_messages: bool = True,
    ):
        """Compaction strategy.

        Args:
            threshold: Token count or percent of context window to trigger compaction.
            memory: Warn the model to save critical content to memory prior
                to compaction when the memory tool is available.
            preserve_prefix_user_messages: Whether to preserve user messages from the
                prefix after compaction. Set to True (default) for strategies that don't
                include prefix user messages in their output (summary, edit, trim).
                Set to False for native compaction where the compact endpoint already
                includes user messages in its response.
        """
        self.threshold = threshold
        self.memory = memory
        self.preserve_prefix_user_messages = preserve_prefix_user_messages

    @abc.abstractmethod
    async def compact(
        self, messages: list[ChatMessage], model: Model
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        """Compact messages.

        Args:
            messages: Full message history
            model: Target model for compaction.

        Returns: Input to present to the model and (optionally) a message to append to the history (e.g. a summarization).
        """
        ...


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
