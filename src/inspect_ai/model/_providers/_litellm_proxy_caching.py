"""Prompt caching for Claude models behind a LiteLLM proxy.

LiteLLM adds cache breakpoints itself only for models its map marks as
supporting prompt caching, so a model it doesn't know (e.g. a predeployment
codename) is never cached. It does forward breakpoints the client sends
(`cache_control` on content blocks and tools, as `cachePoint` for Bedrock),
so the provider marks the same places the native Anthropic provider does.
"""

from typing import Any, Literal, cast

from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam

CACHE_CONTROL: dict[str, Any] = {"type": "ephemeral"}
"""A breakpoint with the default TTL (the proxy may change the TTL)."""

_CACHEABLE_BLOCKS = ("text", "image_url")
"""Content block types LiteLLM keeps `cache_control` on."""


def with_cache_breakpoints(
    messages: list[ChatCompletionMessageParam],
) -> list[ChatCompletionMessageParam]:
    """`messages` with breakpoints on the system prompt and the last two turns.

    The last marks the whole prompt for the next request; the one before it
    is a fallback when the last changes (as the native provider does).
    Anthropic allows four breakpoints; the fourth is on the tools.
    """
    result = [cast(dict[str, Any], dict(message)) for message in messages]
    system = [
        i for i, m in enumerate(result) if m.get("role") in ("system", "developer")
    ]
    if system:
        _mark(result[system[-1]])
    marked = 0
    for message in reversed(result):
        if marked == 2 or message.get("role") in ("system", "developer"):
            break
        if _mark(message):
            marked += 1
    return cast(list[ChatCompletionMessageParam], result)


def with_tool_cache_breakpoint(
    tools: list[ChatCompletionToolParam],
) -> list[ChatCompletionToolParam]:
    """`tools` with a breakpoint on the last (caching all tool definitions)."""
    if not tools:
        return tools
    last = cast(dict[str, Any], dict(tools[-1]))
    last["function"] = dict(last["function"]) | {"cache_control": CACHE_CONTROL}
    return [*tools[:-1], cast(ChatCompletionToolParam, last)]


def _mark(message: dict[str, Any]) -> bool:
    """Add a breakpoint to the message's last content block, if it has one."""
    content = message.get("content")
    if isinstance(content, str):
        if not content:
            return False
        message["content"] = [
            {"type": "text", "text": content, "cache_control": CACHE_CONTROL}
        ]
        return True
    if isinstance(content, list) and content:
        last = content[-1]
        if isinstance(last, dict) and last.get("type") in _CACHEABLE_BLOCKS:
            message["content"] = [
                *content[:-1],
                last | {"cache_control": CACHE_CONTROL},
            ]
            return True
    return False


def cache_write_ttl(usage: dict[str, Any]) -> Literal["5m", "1h"] | None:
    """The TTL of the cache writes a response's usage reports.

    LiteLLM reports Anthropic's split of cache writes by TTL in
    `prompt_tokens_details.cache_creation_token_details`. A proxy can change
    the TTL of the breakpoints it forwards, so this (not what was sent) is
    what is billed. When both TTLs were written, the larger share is used.
    None when the response has no split.
    """
    details = (usage.get("prompt_tokens_details") or {}).get(
        "cache_creation_token_details"
    )
    if not isinstance(details, dict):
        return None
    five_minute = details.get("ephemeral_5m_input_tokens") or 0
    one_hour = details.get("ephemeral_1h_input_tokens") or 0
    if not isinstance(five_minute, int) or not isinstance(one_hour, int):
        return None
    if one_hour == 0 and five_minute == 0:
        return None
    return "1h" if one_hour > five_minute else "5m"
