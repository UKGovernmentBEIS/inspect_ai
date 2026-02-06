"""Automatic compaction strategy with native-first, summary fallback.

This module provides a CompactionStrategy that tries native compaction first
and falls back to summary-based compaction for unsupported providers.
"""

from typing import Literal

from typing_extensions import override

from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._model import Model
from inspect_ai.tool._tool_info import ToolInfo

from .native import CompactionNative
from .summary import CompactionSummary
from .types import CompactionStrategy


class CompactionAuto(CompactionStrategy):
    """Automatic compaction: tries native first, falls back to summary.

    This strategy uses efficient provider-native compaction when available, and falls back to summary-based compaction for unsupported providers or models.

    This is the recommended default for most use cases, as it automatically
    adapts to the capabilities of the underlying provider and model.
    """

    def __init__(
        self,
        threshold: int | float = 0.9,
        instructions: str | None = None,
        memory: bool | Literal["auto"] = "auto",
    ) -> None:
        """Initialize automatic compaction strategy.

        Args:
            threshold: Token count or percent of context window to trigger compaction.
            instructions: Additional instructions to give the model about compaction
               (e.g. "Focus on preserving code snippets, variable names, and technical decisions.")
            memory: Whether to warn the model to save critical content to memory
                prior to compaction. Use "auto" (the default) to disable memory for
                native compaction and enable it for summary compaction.
        """
        # Don't pass memory to base - we'll handle it via property
        super().__init__(threshold=threshold, memory=False)
        self._instructions = instructions
        self._memory_setting = memory

        # Determine memory settings for each strategy
        native_memory = False if memory == "auto" else memory
        summary_memory = True if memory == "auto" else memory

        # Create internal strategies with appropriate settings
        self._native = CompactionNative(
            threshold=threshold,
            instructions=instructions,
            memory=native_memory,
        )
        self._summary = CompactionSummary(
            threshold=threshold,
            instructions=instructions,
            memory=summary_memory,
        )

        # Track whether we've fallen back to summary
        self._use_fallback = False

    @property
    def memory(self) -> bool:
        """Return memory setting based on current compaction strategy.

        For "auto" mode, returns False when using native compaction and True
        after falling back to summary compaction
        """
        if self._memory_setting == "auto":
            # Return True only after we've fallen back to summary
            return self._use_fallback
        return self._memory_setting

    @override
    async def compact(
        self, model: Model, messages: list[ChatMessage], tools: list[ToolInfo]
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        """Compact messages using native compaction with summary fallback.

        Attempts native compaction first. If the provider doesn't support
        native compaction (NotImplementedError), falls back to summary-based
        compaction and remembers this choice for subsequent calls.

        Args:
            model: Target model for compaction.
            messages: Full message history to compact.
            tools: Available tools.

        Returns:
            Tuple of (compacted messages, supplemental message or None).
        """
        # Use fallback straight away if we've had to in the past
        if self._use_fallback:
            return await self._summary.compact(model, messages, tools)

        try:
            # Try native compaction
            return await self._native.compact(model, messages, tools)
        except NotImplementedError:
            # Switch to summary and remember for future calls
            self._use_fallback = True
            return await self._summary.compact(model, messages, tools)
