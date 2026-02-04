"""Native compaction strategy using provider-specific compaction APIs.

This module provides a CompactionStrategy that delegates to provider-native
compaction endpoints (e.g., OpenAI Codex's responses.compact API).
"""

from typing_extensions import override

from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import Model

from .types import CompactionStrategy


class CompactionNative(CompactionStrategy):
    """Compaction strategy using provider-native compaction APIs.

    This strategy delegates compaction to the model provider's native compaction
    endpoint when available (e.g., OpenAI Codex models). For providers without
    native compaction support, this will raise NotImplementedError.

    The native compaction approach differs from other strategies (edit, summary, trim)
    in that:
    - Compaction is performed server-side by the provider
    - The compacted representation is opaque (encrypted) and provider-specific
    - Token savings may be more aggressive while preserving semantic meaning

    Note: Logging is handled by the provider's compact() method.
    """

    def __init__(
        self,
        threshold: int | float = 0.9,
        memory: bool = False,
        config: GenerateConfig | None = None,
    ) -> None:
        """Initialize native compaction strategy.

        Args:
            threshold: Token count or percent of context window to trigger compaction.
            memory: Whether to warn the model to save critical content to memory
                prior to compaction. Default is False since native compaction
                preserves context server-side.
            config: Optional generation config for provider-specific settings
                (e.g., reasoning parameters for OpenAI models).
        """
        # preserve_system_message=True to ensure system prompt survives compaction
        # (compact endpoint doesn't return system messages)
        super().__init__(
            threshold=threshold, memory=memory, preserve_system_message=True
        )
        self._config = config

    @override
    async def compact(
        self, messages: list[ChatMessage], model: Model
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        """Compact messages using the provider's native compaction API.

        Args:
            messages: Full message history to compact.
            model: Target model for compaction (must support native compaction).

        Returns:
            Tuple of (compacted messages, None). The second element is always None
            since native compaction doesn't produce a supplemental message for history.

        Raises:
            NotImplementedError: If the model's provider doesn't support native compaction.
        """
        # Delegate to the Model wrapper's compact method
        # This provides retry logic, concurrency management, and usage tracking
        compacted_messages, _ = await model.compact(messages, self._config)

        # Return compacted messages with no supplemental message
        # (native compaction doesn't produce summaries or side-effect messages)
        return compacted_messages, None
