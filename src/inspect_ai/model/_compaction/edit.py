from typing import Literal, cast

from shortuuid import uuid
from typing_extensions import override

from inspect_ai._util.content import Content, ContentReasoning, ContentText
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._model import Model
from inspect_ai.model._trim import strip_citations
from inspect_ai.tool import ToolCall

from .memory import clear_memory_content
from .types import CompactionStrategy


class CompactionEdit(CompactionStrategy):
    """Message editing compaction.

    Compact messages by editing the history to remove tool call results
    and thinking blocks. Tool results receive placeholder to indicate
    they were removed.
    """

    def __init__(
        self,
        threshold: int | float = 0.9,
        memory: bool = True,
        keep_thinking_turns: Literal["all"] | int = 1,
        keep_tool_uses: int = 3,
        keep_tool_inputs: bool = True,
        exclude_tools: list[str] | None = None,
    ):
        """Message editing compaction.

        Args:
            threshold: Token count or percent of context window to trigger
                compaction.
            memory: Warn the model to save critical content to memory prior
                to compaction when the memory tool is available.
            keep_thinking_turns: Defines how many recent assistant turns to
                preserve thinking blocks within. Specify N to keep the thinking
                blocks within the last N turns, or "all" to keep all thinking
                blocks. Defaults to 1. Note that some providers (e.g. google)
                do not support thinking compaction.
            keep_tool_uses: Defines how many recent tool use/result pairs to
                keep after clearing occurs. The oldest tool interactions are
                removed first, preserving the most recent ones. Tool output is
                replaced with placeholder text to let the model know that tool
                result was removed.
            keep_tool_inputs: Controls whether the tool call parameters are
                cleared along with the tool results. By default, only the tool
                results are cleared while keeping the original tool calls
                visible. When False, both the tool call and result are removed
                entirely and replaced with a placeholder text.
            exclude_tools: List of tool names whose tool uses and results
                should never be cleared. Useful for preserving important
                context.
        """
        super().__init__(threshold, memory)
        self.keep_thinking_turns = keep_thinking_turns
        self.keep_tool_uses = keep_tool_uses
        self.keep_tool_inputs = keep_tool_inputs
        self.exclude_tools = exclude_tools

    @override
    async def compact(
        self, messages: list[ChatMessage], model: Model
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        """Compact messages by editing the history.

        Removes tool call results and thinking blocks from older turns.
        Tool results receive placeholder to indicate they were removed.

        Args:
            messages: Full message history
            model: Target model for compation.

        Returns: Compacted messages and None (no summary message appended).
        """
        result: list[ChatMessage] = list(messages)

        # Phase 1: Clear thinking blocks from older turns
        can_clear_thinking = (
            self.keep_thinking_turns != "all" and model.api.compact_reasoning_history()
        )
        if can_clear_thinking:
            keep_thinking_turns = cast(int, self.keep_thinking_turns)
            assistant_turn_count = 0
            for i in range(len(result) - 1, -1, -1):
                msg = result[i]
                if isinstance(msg, ChatMessageAssistant):
                    assistant_turn_count += 1
                    if assistant_turn_count > keep_thinking_turns:
                        result[i] = _clear_reasoning(msg)

        # Phase 2: Collect clearable tool pairs
        # Each pair is (assistant_idx, tool_call, tool_msg_idx)
        tool_pairs: list[tuple[int, ToolCall, int]] = []
        for i, msg in enumerate(result):
            if isinstance(msg, ChatMessageAssistant) and msg.tool_calls:
                for tc in msg.tool_calls:
                    # Skip excluded tools
                    if self.exclude_tools and tc.function in self.exclude_tools:
                        continue
                    # Find matching tool message
                    tool_msg_idx = _find_tool_message(result, tc.id, i)
                    if tool_msg_idx is not None:
                        tool_pairs.append((i, tc, tool_msg_idx))

        # Keep most recent pairs, clear oldest
        if self.keep_tool_uses > 0 and len(tool_pairs) > self.keep_tool_uses:
            pairs_to_clear = tool_pairs[: -self.keep_tool_uses]
        elif self.keep_tool_uses == 0:
            pairs_to_clear = tool_pairs
        else:
            pairs_to_clear = []

        # Phase 3: Apply clearing (process in reverse to preserve indices)
        for assistant_idx, tool_call, tool_idx in reversed(pairs_to_clear):
            if self.keep_tool_inputs:
                # Just clear the result content
                result[tool_idx] = result[tool_idx].model_copy(
                    update={"id": uuid(), "content": "(Tool result removed)"}
                )
            else:
                # Remove tool message entirely
                del result[tool_idx]
                # Update assistant message: remove tool_call, add placeholder text
                result[assistant_idx] = _replace_tool_call_with_text(
                    cast(ChatMessageAssistant, result[assistant_idx]),
                    tool_call,
                )

        # Phase 4: Clear content from memory tool calls (if memory integration active)
        if self.memory:
            result = clear_memory_content(result)

        # Phase 5: Strip citations (they reference server-side tool results that may be removed)
        result = strip_citations(result)

        return result, None


def _clear_reasoning(msg: ChatMessageAssistant) -> ChatMessageAssistant:
    """Remove ContentReasoning from message content."""
    if isinstance(msg.content, str):
        return msg  # No reasoning in string content
    new_content = [c for c in msg.content if not isinstance(c, ContentReasoning)]
    if not new_content:
        return msg.model_copy(update={"id": uuid(), "content": ""})
    return msg.model_copy(update={"id": uuid(), "content": new_content})


def _find_tool_message(
    messages: list[ChatMessage], tool_call_id: str, start_idx: int
) -> int | None:
    """Find the ChatMessageTool matching a tool_call_id after start_idx."""
    for i in range(start_idx + 1, len(messages)):
        msg = messages[i]
        if isinstance(msg, ChatMessageTool) and msg.tool_call_id == tool_call_id:
            return i
    return None


def _replace_tool_call_with_text(
    msg: ChatMessageAssistant, tool_call: ToolCall
) -> ChatMessageAssistant:
    """Remove a tool call and add placeholder text."""
    new_tool_calls = [tc for tc in (msg.tool_calls or []) if tc.id != tool_call.id]
    placeholder = ContentText(
        text=f"[Tool call: {tool_call.function} (parameters and results removed from history)]"
    )

    new_content: list[Content]
    if isinstance(msg.content, str):
        new_content = (
            [ContentText(text=msg.content), placeholder]
            if msg.content
            else [placeholder]
        )
    else:
        new_content = list(msg.content) + [placeholder]

    return msg.model_copy(
        update={
            "id": uuid(),
            "tool_calls": new_tool_calls if new_tool_calls else None,
            "content": new_content,
        }
    )
