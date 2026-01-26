from __future__ import annotations

import functools
from logging import getLogger
from typing import Sequence

from inspect_ai._util._async import tg_collect
from inspect_ai.tool import Tool, ToolDef, ToolInfo, ToolSource

from .._call_tools import get_tools_info, resolve_tools
from .._chat_message import ChatMessage, ChatMessageUser
from .._model import Model, get_model
from .._model_info import get_model_info
from .memory import MEMORY_TOOL, memory_warning_message
from .types import Compact, CompactionStrategy

logger = getLogger(__name__)


def compaction(
    strategy: CompactionStrategy,
    prefix: list[ChatMessage],
    tools: Sequence[Tool | ToolDef | ToolInfo | ToolSource] | ToolSource | None = None,
    model: str | Model | None = None,
) -> Compact:
    """Create a conversation compaction handler.

    Call the `Compact` handler with the full conversation history before sending input to the model. Send the returned `input` and append the supplemental message returned (if any) to the full history.

    See the [Compaction](ttps://inspect.aisi.org.uk/compaction.html) for additional details on using compaction.

    Args:
        strategy: Compaction strategy (e.g. editing, trimming, summary, etc.)
        prefix: Chat messages to always preserve in compacted conversations.
        tools: Tool definitions (included in token count as they consume context).
        model: Target model for compacted input (defaults to active model).

    Returns:
        `Compact` function which takes a full message history and returns the
        Input to present to the model and (optionally) a message to append to
        the history (e.g. a summarization).
    """
    from inspect_ai.log._transcript import transcript

    # state: compacted input to send to the model
    compacted_input: list[ChatMessage] = []

    # state: whether we've issued a memory warning for the current window
    memory_warning_issued: bool = False

    # state: IDs of messages we've already processed (added to input)
    processed_message_ids: set[str] = set()

    # state: cache of message_id -> token_count
    token_count_cache: dict[str, int] = {}

    # snapshot the prefix in case it changes
    prefix = prefix.copy()

    # resolve target model
    target_model = get_model(model)

    # resolve thresholds
    threshold = _resolve_threshold(target_model, strategy.threshold)
    memory_warning_threshold = int(0.9 * threshold)

    # resolve tool info and count tool/prefix tokens once (they don't change during conversation)
    tools_info: list[ToolInfo] = []
    tool_tokens: int | None = None
    prefix_tokens: int | None = None

    # helper to get message ID (assert away id == None)
    def message_id(message: ChatMessage) -> str:
        if message.id is None:
            raise RuntimeError("Message must have an ID")
        return message.id

    # count tokens with caching
    async def count_tokens(message: ChatMessage) -> int:
        # check cache
        id = message_id(message)
        count = token_count_cache.get(id, None)
        if count is not None:
            return count

        # count tokens and update cache
        count = await target_model.count_tokens([message])
        token_count_cache[id] = count

        # return count
        return count

    async def compact_fn(
        messages: list[ChatMessage],
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        # state variables we modify
        nonlocal tool_tokens, tools_info, prefix_tokens, memory_warning_issued

        # one time resolution of tool_tokens and prefix_tokens
        # (must be done here b/c calls are async)
        if tool_tokens is None:
            tools_info = get_tools_info(await resolve_tools(tools or []))
            tool_tokens = await target_model.count_tool_tokens(tools_info)
        if prefix_tokens is None:
            prefix_tokens = await target_model.count_tokens(prefix) if prefix else 0

        # determine unprocessed messages (messages not yet added to input).
        # we allow unprocessed messages to accumulate in the input until
        # the compaction 'threshold' is reached.
        unprocessed: list[ChatMessage] = [
            m for m in messages if message_id(m) not in processed_message_ids
        ]

        # check to see whether the tokens exceeds the compaction 'threshold'
        target_messages = compacted_input + unprocessed
        message_tokens = sum(
            await tg_collect(
                [functools.partial(count_tokens, m) for m in target_messages]
            )
        )
        total_tokens = tool_tokens + message_tokens
        if total_tokens > threshold:
            # perform compaction (with iteration if needed)
            c_input, c_message = await _perform_compaction(
                strategy=strategy,
                messages=target_messages,
                model=target_model,
                threshold=threshold,
                tool_tokens=tool_tokens,
                prefix_tokens=prefix_tokens,
            )

            # track all messages that were processed in this compaction pass
            for m in compacted_input + unprocessed:
                processed_message_ids.add(message_id(m))

            # c_message is a compaction side effect to append to the history
            # (e.g. a summary). track it as processed as well
            if c_message is not None:
                processed_message_ids.add(message_id(c_message))

            # ensure we preserve the prefix (could have been wiped out by a summarization)
            input_ids = {message_id(m) for m in c_input}
            prepend_prefix = [m for m in prefix if message_id(m) not in input_ids]
            c_input = prepend_prefix + c_input

            # update input
            compacted_input.clear()
            compacted_input.extend(c_input)

            # log compaction
            compacted_tokens = await target_model.count_tokens(compacted_input)
            transcript().info(
                {
                    "Compaction": strategy.__class__.__name__,
                    "Tokens": f"{total_tokens:,} ⟶ {compacted_tokens:,}",
                    "Messages": f"{len(target_messages):,} ⟶ {len(compacted_input):,}",
                }
            )

            # clear memory warning state
            memory_warning_issued = False

            # return input and any extra message to append
            return list(c_input), c_message

        else:
            # track unprocessed messages as now processed
            for m in unprocessed:
                processed_message_ids.add(message_id(m))

            # extend input with unprocessed messages
            compacted_input.extend(unprocessed)

            # check if we need to do a memory warning
            if (
                strategy.memory is True
                and MEMORY_TOOL in [t.name for t in tools_info]
                and total_tokens > memory_warning_threshold
                and not memory_warning_issued
            ):
                memory_message = memory_warning_message()
                compacted_input.append(memory_message)
                processed_message_ids.add(message_id(memory_message))
                memory_warning_issued = True

            # return
            return list(compacted_input), None

    return compact_fn


DEFAULT_CONTEXT_WINDOW = 128_000


async def _perform_compaction(
    strategy: CompactionStrategy,
    messages: list[ChatMessage],
    model: Model,
    threshold: int,
    tool_tokens: int,
    prefix_tokens: int,
) -> tuple[list[ChatMessage], ChatMessageUser | None]:
    """Perform compaction, iterating if necessary to get under threshold.

    Args:
        strategy: Compaction strategy to use.
        messages: Messages to compact.
        model: Target model for compaction.
        threshold: Token threshold to stay under.
        tool_tokens: Token count for tool definitions.
        prefix_tokens: Token count for prefix messages (for error reporting).

    Returns:
        Tuple of (compacted messages, optional summary message).

    Raises:
        RuntimeError: If compaction cannot reduce tokens below threshold.
    """
    MAX_ITERATIONS = 3
    c_input, c_message = await strategy.compact(messages, model)
    compacted_tokens = await model.count_tokens(c_input)
    total_compacted = tool_tokens + compacted_tokens

    for _ in range(MAX_ITERATIONS):
        if total_compacted <= threshold:
            break  # Success

        prev_tokens = compacted_tokens

        # Try compacting again
        c_input, c_message = await strategy.compact(list(c_input), model)
        compacted_tokens = await model.count_tokens(c_input)
        total_compacted = tool_tokens + compacted_tokens

        # Stop if no progress (can't reduce further)
        if compacted_tokens >= prev_tokens:
            break

    # Final validation
    if total_compacted > threshold:
        raise RuntimeError(
            f"Compaction insufficient: {total_compacted:,} tokens "
            f"still exceeds threshold of {threshold:,} "
            f"(tools: {tool_tokens:,}, prefix: {prefix_tokens:,}, "
            f"messages: {compacted_tokens:,}). "
            f"Consider using a lower compaction threshold to accommodate "
            f"tool definitions and prefix."
        )

    return c_input, c_message


def _resolve_threshold(model: Model, threshold: int | float) -> int:
    """Resolve compaction threshold to an absolute token count.

    Args:
        model: Target model for compacted input.
        threshold: Token count (int) or fraction of context window (float <= 1.0).

    Returns:
        Absolute token threshold for triggering compaction.
    """
    if isinstance(threshold, int) or threshold > 1.0:
        return int(threshold)
    else:
        # Look up the model's context window
        info = get_model_info(model)
        if info and info.context_length:
            context_window = info.context_length
        else:
            logger.warning(
                f"Unable to determine context window for {model} (falling back to default of {DEFAULT_CONTEXT_WINDOW})"
            )
            context_window = DEFAULT_CONTEXT_WINDOW

        # compute threshold
        return int(threshold * context_window)
