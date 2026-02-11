import abc
from typing import Protocol

from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._model import Model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool_info import ToolInfo


class CompactionStrategy(abc.ABC):
    """Compaction strategy."""

    def __init__(
        self,
        threshold: int | float = 0.9,
        memory: bool = True,
    ):
        """Compaction strategy.

        Args:
            threshold: Token count or percent of context window to trigger compaction.
            memory: Warn the model to save critical content to memory prior
                to compaction when the memory tool is available.
        """
        self.threshold = threshold
        self._memory = memory

    @property
    def memory(self) -> bool:
        """Whether to warn the model to save content to memory before compaction."""
        return self._memory

    @property
    def preserve_prefix(self) -> bool:
        """Instruction to orchestrator: preserve prefix messages in compacted output.

        When True (default), the orchestration layer will prepend any prefix
        messages not already in the compacted output.

        When False (native compaction), only system messages are prepended
        since user content is either preserved by the provider (OpenAI) or
        semantically encoded in the compaction block (Anthropic).
        """
        return True

    @abc.abstractmethod
    async def compact(
        self, model: Model, messages: list[ChatMessage], tools: list[ToolInfo]
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        """Compact messages.

        Args:
            model: Target model for compaction.
            messages: Full message history
            tools: Available tools

        Returns: Input to present to the model and (optionally) a message to append to the history (e.g. a summarization).
        """
        ...


class Compact(Protocol):
    """Interface for compaction strategies."""

    async def compact_input(
        self, messages: list[ChatMessage]
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        """Compact messages for input to the model.

        Args:
            messages: Full message history

        Returns: Input to present to the model and (optionally) a message to append to the history (e.g. a summarization).
        """
        ...

    def record_output(self, output: ModelOutput) -> None:
        """Record the output from a generate call.

        After each generate call, pass the ModelOutput to calibrate
        the compaction's token estimation. This accounts for API-level
        overhead (tool definitions, system messages, thinking
        configuration) that per-message counting cannot capture.

        Args:
            output: The ModelOutput from the generate call.
        """
        ...
