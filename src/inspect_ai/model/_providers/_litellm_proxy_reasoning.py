"""Reasoning round trips through a LiteLLM proxy's chat completions endpoint.

Besides `reasoning_content`, LiteLLM returns each provider's reasoning in two
documented message fields, and reads both back from assistant messages on the
next request:

- `thinking_blocks`: Anthropic-style `{"type": "thinking", "thinking",
  "signature"}` and `{"type": "redacted_thinking", "data"}` blocks (Anthropic,
  Bedrock, and Gemini thought parts).
- `provider_specific_fields.thought_signatures`: Gemini thought signatures.
  On replay LiteLLM attaches the first one to the text part unless a tool call
  already carries it (tool call signatures travel in the tool call id).

Reasoning read from these fields is marked with the field name in
`ContentReasoning.internal` and is replayed through the same field.
"""

from collections.abc import AsyncIterable, AsyncIterator
from logging import getLogger
from typing import Any, cast

from openai.types.chat import (
    ChatCompletion,
    ChatCompletionAssistantMessageParam,
    ChatCompletionChunk,
    ChatCompletionMessage,
    ChatCompletionMessageParam,
)
from openai.types.chat.chat_completion_chunk import ChoiceDelta

from inspect_ai._util.content import Content, ContentReasoning, ContentText
from inspect_ai._util.logger import warn_once

from .._chat_message import ChatMessage
from .._model_output import ChatCompletionChoice
from .._openai import default_reasoning_handler, openai_chat_message

logger = getLogger(__name__)

THINKING_BLOCKS = "thinking_blocks"
THOUGHT_SIGNATURES = "thought_signatures"
PROVIDER_SPECIFIC_FIELDS = "provider_specific_fields"


def choice_with_litellm_reasoning(
    choice: ChatCompletionChoice, message: ChatCompletionMessage
) -> ChatCompletionChoice:
    """Replace the reasoning parsed from `reasoning_content` with LiteLLM's fields.

    LiteLLM's `reasoning_content` is the text of the `thinking_blocks`, so
    when blocks are present the reasoning parsed from it is dropped rather
    than kept as a duplicate.
    """
    blocks = _reasoning_from_thinking_blocks(message)
    signatures = _reasoning_from_thought_signatures(message)
    if not blocks and not signatures:
        return choice

    content: list[Content] = (
        [ContentText(text=choice.message.content)]
        if isinstance(choice.message.content, str)
        else list(choice.message.content)
    )
    if blocks:
        content = [c for c in content if not isinstance(c, ContentReasoning)]
    reasoning: list[Content] = [*blocks, *signatures]
    return choice.model_copy(
        update={
            "message": choice.message.model_copy(
                update={"content": [*reasoning, *content]}
            )
        }
    )


def _reasoning_from_thinking_blocks(
    message: ChatCompletionMessage,
) -> list[ContentReasoning]:
    blocks = (message.model_extra or {}).get(THINKING_BLOCKS)
    if not isinstance(blocks, list):
        return []
    reasoning: list[ContentReasoning] = []
    for block in blocks:
        match block:
            case {"type": "thinking"}:
                text = block.get("thinking")
                signature = block.get("signature")
                if text or signature:
                    reasoning.append(
                        ContentReasoning(
                            reasoning=text if isinstance(text, str) else "",
                            signature=signature if isinstance(signature, str) else None,
                            internal=THINKING_BLOCKS,
                        )
                    )
            case {"type": "redacted_thinking", "data": str(data)}:
                reasoning.append(
                    ContentReasoning(
                        reasoning=data, redacted=True, internal=THINKING_BLOCKS
                    )
                )
            case _:
                warn_once(
                    logger,
                    f"Ignoring unrecognized LiteLLM thinking block: {block!r:.200}",
                )
    return reasoning


def _reasoning_from_thought_signatures(
    message: ChatCompletionMessage,
) -> list[ContentReasoning]:
    fields = (message.model_extra or {}).get(PROVIDER_SPECIFIC_FIELDS)
    signatures = fields.get(THOUGHT_SIGNATURES) if isinstance(fields, dict) else None
    if not isinstance(signatures, list):
        return []
    return [
        ContentReasoning(
            reasoning=signature, redacted=True, internal=THOUGHT_SIGNATURES
        )
        for signature in signatures
        if isinstance(signature, str) and signature
    ]


async def litellm_messages_to_openai(
    input: list[ChatMessage],
) -> list[ChatCompletionMessageParam]:
    return [await _litellm_message_to_openai(message) for message in input]


async def _litellm_message_to_openai(
    message: ChatMessage,
) -> ChatCompletionMessageParam:
    param = await openai_chat_message(message, "system", _reasoning_handler)
    if message.role != "assistant":
        return param
    text = _litellm_text(message.content)
    if text is not None:
        param = cast(ChatCompletionAssistantMessageParam, param | {"content": text})
    if param.get("tool_calls") and _is_empty(param.get("content")):
        # LiteLLM replaces empty text sent to Anthropic with a placeholder
        # ("[System: Empty message content sanitised ...]") that the model
        # then sees; null content with tool calls passes through unchanged
        param = cast(ChatCompletionAssistantMessageParam, param | {"content": None})
    if isinstance(message.content, str):
        return param

    reasoning = [c for c in message.content if isinstance(c, ContentReasoning)]
    blocks = [_thinking_block(r) for r in reasoning if r.internal == THINKING_BLOCKS]
    signatures = [r.reasoning for r in reasoning if r.internal == THOUGHT_SIGNATURES]

    fields: dict[str, Any] = {}
    if blocks:
        fields[THINKING_BLOCKS] = blocks
        # what LiteLLM returned alongside the blocks; providers that take
        # reasoning text rather than blocks (e.g. Gemini) read it
        text = "".join(str(b.get("thinking") or "") for b in blocks)
        if text:
            fields["reasoning_content"] = text
    if signatures:
        fields[PROVIDER_SPECIFIC_FIELDS] = {THOUGHT_SIGNATURES: signatures}
    return cast(ChatCompletionAssistantMessageParam, param | fields)


def _litellm_text(content: str | list[Content]) -> str | None:
    """The message text as LiteLLM returned it, if it can be rebuilt exactly.

    LiteLLM joins a response's text blocks with no separator, so joining the
    text parts reproduces it. The base conversion instead puts a newline
    before each part, which would change the model's earlier text on replay.
    None when some content must go through the base conversion (reasoning
    not carried in LiteLLM's fields, or text with Inspect internal data).
    """
    if isinstance(content, str):
        return None
    texts: list[str] = []
    for part in content:
        if isinstance(part, ContentReasoning):
            if part.internal not in (THINKING_BLOCKS, THOUGHT_SIGNATURES):
                return None
        elif isinstance(part, ContentText):
            if part.internal is not None:
                return None
            texts.append(part.text)
    return "".join(texts)


def _is_empty(content: Any) -> bool:
    """Whether message content has no text (or other) blocks to send."""
    if content is None:
        return True
    if isinstance(content, str):
        return not content.strip()
    return all(
        not block
        or (block.get("type") == "text" and not str(block.get("text") or "").strip())
        for block in content
    )


def _reasoning_handler(content: ContentReasoning) -> dict[str, Any] | str:
    if content.internal in (THINKING_BLOCKS, THOUGHT_SIGNATURES):
        return {}
    return default_reasoning_handler(content)


def _thinking_block(reasoning: ContentReasoning) -> dict[str, Any]:
    if reasoning.redacted:
        return {"type": "redacted_thinking", "data": reasoning.reasoning}
    block: dict[str, Any] = {"type": "thinking", "thinking": reasoning.reasoning}
    if reasoning.signature is not None:
        block["signature"] = reasoning.signature
    return block


class ThinkingBlocksAccumulator:
    """Merge the `thinking_blocks` entries LiteLLM streams into whole blocks.

    LiteLLM streams one entry per thinking delta, then one carrying the
    block's signature, and each redacted block as a single entry. Entries have
    no `index`, so the OpenAI SDK's stream accumulator cannot merge them.

    LiteLLM currently repeats the block's full text in the signature entry.
    That entry is taken as the whole block when its text starts with the text
    accumulated so far; a signature entry with no text closes the accumulated
    block, and any other text is appended to it.
    """

    def __init__(self) -> None:
        self._blocks: list[dict[str, Any]] = []
        self._text: str | None = None

    def add(self, entry: object) -> None:
        if not isinstance(entry, dict) or not isinstance(entry.get("type"), str):
            warn_once(
                logger,
                f"Ignoring unrecognized LiteLLM thinking block delta: {entry!r:.200}",
            )
            return
        if entry["type"] != "thinking":
            self._close()
            self._blocks.append(dict(entry))
            return

        text = entry.get("thinking")
        text = text if isinstance(text, str) else ""
        signature = entry.get("signature")
        if not signature:
            if text:
                self._text = (self._text or "") + text
            return
        accumulated = self._text or ""
        if not (text and text.startswith(accumulated)):
            text = accumulated + text
        self._blocks.append(
            {"type": "thinking", "thinking": text, "signature": signature}
        )
        self._text = None

    def blocks(self) -> list[dict[str, Any]]:
        self._close()
        return list(self._blocks)

    def _close(self) -> None:
        if self._text is not None:
            self._blocks.append({"type": "thinking", "thinking": self._text})
            self._text = None


async def without_thinking_block_deltas(
    stream: AsyncIterable[ChatCompletionChunk],
    accumulators: dict[int, ThinkingBlocksAccumulator],
) -> AsyncIterator[ChatCompletionChunk]:
    """Pass chunks through, moving `thinking_blocks` entries to `accumulators`.

    Entries are keyed by choice index. They are removed from both places
    LiteLLM puts them: the delta and its `provider_specific_fields`.
    """
    async for chunk in stream:
        for choice in chunk.choices:
            entries = _pop_thinking_blocks(choice.delta)
            if entries:
                accumulator = accumulators.setdefault(
                    choice.index, ThinkingBlocksAccumulator()
                )
                for entry in entries:
                    accumulator.add(entry)
        yield chunk


def _pop_thinking_blocks(delta: ChoiceDelta) -> list[object]:
    extra = delta.model_extra
    if not extra:
        return []
    entries = extra.pop(THINKING_BLOCKS, None)
    fields = extra.get(PROVIDER_SPECIFIC_FIELDS)
    if isinstance(fields, dict) and THINKING_BLOCKS in fields:
        nested = fields[THINKING_BLOCKS]
        extra[PROVIDER_SPECIFIC_FIELDS] = {
            key: value for key, value in fields.items() if key != THINKING_BLOCKS
        }
        if entries is None:
            entries = nested
    return list(entries) if isinstance(entries, list) else []


def with_streamed_thinking_blocks(
    completion: ChatCompletion, accumulators: dict[int, ThinkingBlocksAccumulator]
) -> ChatCompletion:
    """Set each choice's accumulated `thinking_blocks` on the final completion."""
    for choice in completion.choices:
        accumulator = accumulators.get(choice.index)
        if accumulator is not None:
            blocks = accumulator.blocks()
            if blocks:
                setattr(choice.message, THINKING_BLOCKS, blocks)
    return completion
