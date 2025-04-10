from typing import Protocol

from ._chat_message import ChatMessage
from ._model_output import ModelOutput


class ModelConversation(Protocol):
    """Model conversation."""

    @property
    def messages(self) -> list[ChatMessage]:
        """Conversation history."""
        ...

    @property
    def output(self) -> ModelOutput:
        """Model output."""
        ...
