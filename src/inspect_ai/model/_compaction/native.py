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

    ::: {.callout-note appearance="minimal"}
    The native compaction strategy is available only in the development version of Inspect. To install the development version from GitHub:

    ``` bash
    pip install git+https://github.com/UKGovernmentBEIS/inspect_ai
    ```
    :::

    This strategy delegates compaction to the model provider's native compaction
    endpoint when available (e.g., OpenAI Codex models). For providers without
    native compaction support, this will raise NotImplementedError. Provide a
    `fallback` strategy to use an alternate strategy when compaction isn't
    supported.

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
        fallback: CompactionStrategy | None = None,
        memory: bool = False,
    ) -> None:
        """Initialize native compaction strategy.

        Args:
            threshold: Token count or percent of context window to trigger compaction.
            instructions: Additional instructions to give the model about compaction
               (e.g. "Focus on preserving code snippets, variable names, and technical decisions.")
            fallback: Fallback strategy if native compaction is not available
                for this provider.
            memory: Whether to warn the model to save critical content to memory
                prior to compaction. Default is False since native compaction
                preserves context server-side.
        """
        super().__init__(threshold=threshold, memory=memory)
        self._instructions = instructions
        self._fallback = fallback
        self._use_fallback = False

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
            Tuple of (compacted messages, supplemental message or None). The second
            element is None for native compaction, but may be non-None when a
            fallback strategy is used (e.g., CompactionSummary returns a summary).

        Raises:
            NotImplementedError: If the model's provider doesn't support native compaction.
        """
        # use fallback straight away if we've had to in the past
        if self._use_fallback and self._fallback is not None:
            return await self._fallback.compact(model, messages, tools)

        # otherwise normal processing
        else:
            try:
                # Delegate to the Model wrapper's compact method
                # This provides retry logic, concurrency management, and usage tracking
                compacted_messages, _ = await model.compact(
                    messages, tools, self._instructions
                )

                # Return compacted messages with no supplemental message
                # (native compaction doesn't produce summaries or side-effect messages)
                return compacted_messages, None
            except NotImplementedError:
                # if we have a fallback then use it and update state to use it going forward
                if self._fallback is not None:
                    result = await self._fallback.compact(model, messages, tools)
                    self._use_fallback = True
                    return result
                else:
                    raise
