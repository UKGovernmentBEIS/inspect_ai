import abc
from typing import Protocol

from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._model import Model


class CompactionStrategy(abc.ABC):
    def __init__(
        self,
        threshold: int | float = 0.9,
        model: str | Model | None = None,
    ):
        """Compaction strategy.

        Args:
            threshold: Token count or percent of context window to trigger compaction.
            model: Model used by compaction strategy (optional, defaults to compaction model).
        """
        self.threshold = threshold
        self.model = model

    @abc.abstractmethod
    async def compact(
        self, messages: list[ChatMessage]
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        """Compact messages.

        Args:
            messages: Full message history

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
