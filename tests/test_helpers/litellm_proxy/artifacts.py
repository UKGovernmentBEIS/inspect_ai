"""Check that upstream reasoning survives a round trip through the LiteLLM proxy.

Each checker takes the raw upstream response for turn N and the raw upstream
request for turn N+1 (as captured by `proxy.upstream_exchange`) and asserts
that every piece of reasoning the provider returned is sent back unchanged,
in the place the provider requires:

- Anthropic Messages: `thinking` (text and signature) and `redacted_thinking`
  blocks, in order, in the matching assistant message, before any `tool_use`.
- Gemini `generateContent`: each `thoughtSignature`, on the matching
  `functionCall` part (other signatures anywhere in the matching turn), and
  never LiteLLM's placeholder signature.
- OpenAI Responses: each reasoning item's `encrypted_content`, before the
  function calls of the same turn.
- Bedrock Converse: `reasoningContent` blocks, in order, in the matching
  assistant message, before any `toolUse`.
- OpenAI-compatible chat (open models): the assistant message's
  `reasoning_content` (or `reasoning`) text.

Each checker returns the number of reasoning pieces it verified, so a test can
also assert the provider returned reasoning at all.
"""

import base64
import json
from typing import Any, Callable

# LiteLLM substitutes this when a Gemini thought signature is missing so the
# request is accepted (the reasoning state is still lost).
GEMINI_PLACEHOLDER_SIGNATURE = base64.b64encode(
    b"skip_thought_signature_validator"
).decode()


class ReplayError(AssertionError):
    pass


def _fail(message: str, **context: Any) -> ReplayError:
    details = "\n".join(
        f"{key}: {json.dumps(value, indent=1, default=str)[:4000]}"
        for key, value in context.items()
    )
    return ReplayError(f"{message}\n{details}" if details else message)


# Anthropic ------------------------------------------------------------------

ANTHROPIC_REASONING_TYPES = ("thinking", "redacted_thinking")


def _anthropic_reasoning_block(block: dict[str, Any]) -> dict[str, Any]:
    if block["type"] == "thinking":
        return {
            "type": "thinking",
            "thinking": block.get("thinking"),
            "signature": block.get("signature"),
        }
    return {"type": "redacted_thinking", "data": block.get("data")}


def check_anthropic_replay(
    response: dict[str, Any], next_request: dict[str, Any]
) -> int:
    returned = [
        _anthropic_reasoning_block(block)
        for block in response["content"]
        if block["type"] in ANTHROPIC_REASONING_TYPES
    ]
    tool_ids = [b["id"] for b in response["content"] if b["type"] == "tool_use"]
    message = _matching_message(
        next_request["messages"],
        role="assistant",
        matches=lambda content: bool(tool_ids)
        and any(
            isinstance(b, dict)
            and b.get("type") == "tool_use"
            and b.get("id") in tool_ids
            for b in content
        ),
    )
    content = _content_blocks(message)
    replayed = [
        _anthropic_reasoning_block(block)
        for block in content
        if block.get("type") in ANTHROPIC_REASONING_TYPES
    ]
    if replayed != returned:
        raise _fail(
            "Anthropic reasoning blocks were not replayed unchanged",
            returned=returned,
            replayed=replayed,
        )
    _check_before_tool_use(content, ANTHROPIC_REASONING_TYPES, "tool_use", "Anthropic")
    return len(returned)


# Gemini ---------------------------------------------------------------------


def _function_call(part: dict[str, Any]) -> dict[str, Any] | None:
    # the API accepts both spellings; LiteLLM sends snake case
    call = part.get("functionCall") or part.get("function_call")
    return call if isinstance(call, dict) else None


def check_gemini_replay(response: dict[str, Any], next_request: dict[str, Any]) -> int:
    parts: list[dict[str, Any]] = response["candidates"][0]["content"]["parts"]
    call_names = [call["name"] for p in parts if (call := _function_call(p))]
    content = _matching_message(
        next_request["contents"],
        role="model",
        matches=lambda replayed_parts: bool(call_names)
        and any(
            (call := _function_call(p)) is not None and call["name"] in call_names
            for p in replayed_parts
            if isinstance(p, dict)
        ),
        content_key="parts",
    )
    replayed_parts: list[dict[str, Any]] = content["parts"]

    placeholders = [
        p
        for p in replayed_parts
        if p.get("thoughtSignature") == GEMINI_PLACEHOLDER_SIGNATURE
    ]
    if placeholders:
        raise _fail(
            "Gemini thought signature was replaced by LiteLLM's placeholder",
            replayed=replayed_parts,
        )

    checked = 0
    replayed_signatures = {p.get("thoughtSignature") for p in replayed_parts}
    for part in parts:
        signature = part.get("thoughtSignature")
        if signature is None:
            continue
        checked += 1
        call = _function_call(part)
        if call is not None:
            match = next(
                (
                    p
                    for p in replayed_parts
                    if (replayed_call := _function_call(p)) is not None
                    and replayed_call["name"] == call["name"]
                    and replayed_call.get("args") == call.get("args")
                ),
                None,
            )
            if match is None or match.get("thoughtSignature") != signature:
                raise _fail(
                    f"Gemini thought signature for functionCall {call['name']!r} "
                    "was not replayed on that part",
                    returned=part,
                    replayed=replayed_parts,
                )
        elif signature not in replayed_signatures:
            raise _fail(
                "Gemini thought signature was not replayed",
                returned=part,
                replayed=replayed_parts,
            )
    return checked


# OpenAI Responses -----------------------------------------------------------


def check_openai_responses_replay(
    response: dict[str, Any], next_request: dict[str, Any]
) -> int:
    returned = [
        item["encrypted_content"]
        for item in response["output"]
        if item.get("type") == "reasoning" and item.get("encrypted_content")
    ]
    input_items = next_request["input"]
    if not isinstance(input_items, list):
        raise _fail("Responses request input is not a list of items", input=input_items)
    replayed = [
        item.get("encrypted_content")
        for item in input_items
        if isinstance(item, dict) and item.get("type") == "reasoning"
    ]
    missing = [value for value in returned if value not in replayed]
    if missing:
        raise _fail(
            "OpenAI encrypted reasoning was not replayed",
            missing_count=len(missing),
            replayed_count=len(replayed),
        )
    call_ids = {
        item["call_id"]
        for item in response["output"]
        if item.get("type") == "function_call"
    }
    for index, item in enumerate(input_items):
        if (
            isinstance(item, dict)
            and item.get("type") == "function_call"
            and item.get("call_id") in call_ids
        ):
            before = [
                i.get("encrypted_content")
                for i in input_items[:index]
                if isinstance(i, dict) and i.get("type") == "reasoning"
            ]
            if not all(value in before for value in returned):
                raise _fail(
                    "OpenAI reasoning items were not replayed before the function call",
                    call_id=item.get("call_id"),
                )
            break
    return len(returned)


# Bedrock Converse -----------------------------------------------------------


def check_bedrock_converse_replay(
    response: dict[str, Any], next_request: dict[str, Any]
) -> int:
    content: list[dict[str, Any]] = response["output"]["message"]["content"]
    returned = [
        block["reasoningContent"] for block in content if "reasoningContent" in block
    ]
    tool_ids = [
        block["toolUse"]["toolUseId"] for block in content if "toolUse" in block
    ]
    message = _matching_message(
        next_request["messages"],
        role="assistant",
        matches=lambda replayed_content: bool(tool_ids)
        and any(
            isinstance(b, dict) and b.get("toolUse", {}).get("toolUseId") in tool_ids
            for b in replayed_content
        ),
    )
    replayed_content = _content_blocks(message)
    replayed = [
        b["reasoningContent"] for b in replayed_content if "reasoningContent" in b
    ]
    if replayed != returned:
        raise _fail(
            "Bedrock reasoning blocks were not replayed unchanged",
            returned=returned,
            replayed=replayed,
        )
    seen_tool_use = False
    for block in replayed_content:
        if "toolUse" in block:
            seen_tool_use = True
        elif "reasoningContent" in block and seen_tool_use:
            raise _fail(
                "Bedrock reasoning block replayed after toolUse",
                content=replayed_content,
            )
    return len(returned)


# OpenAI-compatible chat (reasoning_content) ---------------------------------

REASONING_TEXT_FIELDS = ("reasoning_content", "reasoning")


def check_reasoning_content_replay(
    response: dict[str, Any], next_request: dict[str, Any]
) -> int:
    message = response["choices"][0]["message"]
    returned = next(
        (message[field] for field in REASONING_TEXT_FIELDS if message.get(field)), None
    )
    if returned is None:
        return 0
    tool_ids = [call["id"] for call in message.get("tool_calls") or []]
    replayed_message = _matching_message(
        next_request["messages"],
        role="assistant",
        matches=lambda _: False,
        tool_call_ids=tool_ids,
    )
    replayed = next(
        (replayed_message[f] for f in REASONING_TEXT_FIELDS if replayed_message.get(f)),
        None,
    )
    if replayed != returned:
        raise _fail(
            "Reasoning text was not replayed unchanged",
            returned=returned,
            replayed=replayed,
        )
    return 1


# Helpers --------------------------------------------------------------------


def _content_blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message.get("content")
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return []


def _matching_message(
    messages: list[dict[str, Any]],
    *,
    role: str,
    matches: Callable[[list[Any]], bool],
    content_key: str = "content",
    tool_call_ids: list[str] | None = None,
) -> dict[str, Any]:
    """The replayed message for the turn being checked.

    The first message of `role` whose content satisfies `matches` (or whose
    `tool_calls` carry one of `tool_call_ids`); otherwise the last message of
    `role`, which is the previous turn in a plain multi-turn conversation.
    """
    candidates = [m for m in messages if m.get("role") == role]
    if not candidates:
        raise _fail(f"No {role!r} message in the replayed request", messages=messages)
    for message in candidates:
        content = message.get(content_key)
        if isinstance(content, list) and matches(content):
            return message
        if tool_call_ids and any(
            call.get("id") in tool_call_ids for call in message.get("tool_calls") or []
        ):
            return message
    return candidates[-1]


def _check_before_tool_use(
    content: list[dict[str, Any]],
    reasoning_types: tuple[str, ...],
    tool_type: str,
    provider: str,
) -> None:
    seen_tool_use = False
    for block in content:
        if block.get("type") == tool_type:
            seen_tool_use = True
        elif block.get("type") in reasoning_types and seen_tool_use:
            raise _fail(
                f"{provider} reasoning block replayed after {tool_type}",
                content=content,
            )
