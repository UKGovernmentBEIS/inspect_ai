"""Native compaction strategy using provider-specific compaction APIs.

This module provides a CompactionStrategy that delegates to provider-native
compaction endpoints (e.g., OpenAI Codex's responses.compact API).
"""

from typing_extensions import override

from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._model import Model
from inspect_ai.tool._tool_info import ToolInfo

from .types import CompactionStrategy


class CompactionNative(CompactionStrategy):
    """Compaction strategy using provider-native compaction APIs.

    This strategy delegates compaction to the model provider's native compaction
    endpoint when available (e.g., OpenAI Codex models). For providers without
    native compaction support, this will raise NotImplementedError. Use
    `CompactionAuto` for automatic fallback to summary-based compaction.

    The native compaction approach differs from other strategies (edit, summary, trim)
    in that:
    - Compaction is performed server-side by the provider
    - The compacted representation is opaque (encrypted) and provider-specific
    - Token savings may be more aggressive while preserving semantic meaning
    """

    def __init__(
        self,
        threshold: int | float = 0.9,
        instructions: str | None = None,
        memory: bool = False,
    ) -> None:
        """Initialize native compaction strategy.

        Args:
            threshold: Token count or percent of context window to trigger compaction.
            instructions: Additional instructions to give the model about compaction
               (e.g. "Focus on preserving code snippets, variable names, and technical decisions.")
            memory: Whether to warn the model to save critical content to memory
                prior to compaction. Default is False.
        """
        super().__init__(type="summary", threshold=threshold, memory=memory)
        self._instructions = instructions

    @property
    @override
    def preserve_prefix(self) -> bool:
        """Instruction to orchestrator: do not preserve prefix messages.

        For native compaction, only system messages are prepended since user
        content is either preserved by the provider (OpenAI) or semantically
        encoded in the compaction block (Anthropic).
        """
        return False

    @override
    async def compact(
        self, model: Model, messages: list[ChatMessage], tools: list[ToolInfo]
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        """Compact messages using the provider's native compaction API.

        Args:
            model: Target model for compaction.
            messages: Full message history to compact.
            tools: Available tools.

        Returns:
            Tuple of (compacted messages, None). Native compaction does not
            produce supplemental messages.

        Raises:
            NotImplementedError: If the model's provider doesn't support native compaction.
        """
        # Delegate to the Model wrapper's compact method
        # This provides retry logic, concurrency management, and usage tracking
        compacted_messages, _ = await model.compact(messages, tools, self._instructions)

        # Return compacted messages with no supplemental message
        # (native compaction doesn't produce summaries or side-effect messages)
        return compacted_messages, None
