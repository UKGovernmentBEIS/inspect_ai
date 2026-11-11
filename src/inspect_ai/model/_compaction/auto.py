"""Automatic compaction strategy with native-first, summary fallback.

This module provides a CompactionStrategy that tries native compaction first
and falls back to summary-based compaction for unsupported providers.
"""

from logging import getLogger
from typing import Any, Literal

from typing_extensions import override

from inspect_ai._util.error import exception_message
from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._model import Model
from inspect_ai.tool._tool_info import ToolInfo

from .native import CompactionNative
from .summary import CompactionSummary
from .types import CompactionResult, CompactionStrategy

logger = getLogger(__name__)


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
                prior to compaction. "auto" (default) enables warnings for all
                compaction paths.
        """
        # Don't pass memory to base - we'll handle it via property
        super().__init__(type="summary", threshold=threshold, memory=False)
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
        self._native._suggest_auto = False
        self._summary = CompactionSummary(
            threshold=threshold,
            instructions=instructions,
            memory=summary_memory,
        )

    @property
    def memory(self) -> bool:
        """Whether to warn the model to save content to memory before compaction."""
        if self._memory_setting == "auto":
            return True
        return self._memory_setting

    @override
    def _repr_params_(self) -> dict[str, Any]:
        params = super()._repr_params_()
        params["instructions"] = self._instructions
        params["memory"] = self._memory_setting
        return params

    async def _delegate_outcome(
        self, model: Model, messages: list[ChatMessage], tools: list[ToolInfo]
    ) -> CompactionResult:
        """Run native compaction, falling back to summary."""
        try:
            return await self._native.compact_outcome(model, messages, tools)
        except NotImplementedError as ex:
            reason = f"native compaction not supported: {str(ex)}"
        except Exception as ex:
            logger.warning(
                f"Native compaction failed: {exception_message(ex)}. "
                "Falling back to summary compaction."
            )
            reason = f"native compaction failed: {str(ex)}"

        outcome = await self._summary.compact_outcome(model, messages, tools)
        return outcome._replace(fallback_reason=reason)

    @override
    async def compact(
        self, model: Model, messages: list[ChatMessage], tools: list[ToolInfo]
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        """Compact messages using native compaction with summary fallback.

        Args:
            model: Target model for compaction.
            messages: Full message history to compact.
            tools: Available tools.

        Returns:
            Tuple of (compacted messages, supplemental message or None).
        """
        outcome = await self._delegate_outcome(model, messages, tools)
        return outcome.input, outcome.message

    @override
    async def compact_outcome(
        self, model: Model, messages: list[ChatMessage], tools: list[ToolInfo]
    ) -> CompactionResult:
        """Compact using native compaction, falling back to summary.

        Reports the delegate that actually ran so the orchestrator applies
        that delegate's prefix rule rather than this wrapper's.

        A subclass that overrides `compact()` expects it to be the seam the
        orchestrator calls, so when that's the case this defers to the base
        `CompactionStrategy.compact_outcome()`, which calls back into
        `compact()` and lets the override run. Such a subclass forfeits
        per-delegate provenance: `applied` and `preserve_prefix` describe
        this class, not the delegate, since we cannot know which delegate ran
        once the subclass has replaced the body. That matches the behaviour
        such a subclass had before `compact_outcome()` existed.

        Args:
            model: Target model for compaction.
            messages: Full message history to compact.
            tools: Available tools.

        Returns:
            The delegate's outcome, with `fallback_reason` set when native
            compaction was not used.
        """
        if type(self).compact is not CompactionAuto.compact:
            return await super().compact_outcome(model, messages, tools)
        return await self._delegate_outcome(model, messages, tools)
