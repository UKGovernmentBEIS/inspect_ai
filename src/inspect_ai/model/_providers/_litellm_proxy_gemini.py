"""Gemini upstreams through the LiteLLM proxy.

Tool call signatures on replay, the function-calling hint and
MALFORMED_FUNCTION_CALL recovery.

LiteLLM maps Gemini's MALFORMED_FUNCTION_CALL finish reason to `stop` and drops
the `finishMessage` that holds the attempted call, so the client sees a turn
with reasoning but neither text nor a tool call (or, on older versions, no
choice at all). Newer LiteLLM reports the raw reason as
`provider_specific_fields.native_finish_reason` on non-streamed choices; older
versions and streams report nothing, so such a turn is recognized by its
shape. The recovery mirrors the native Google provider's: a corrective
exchange, tool calling forced if it was `auto`, and words in the model's
mouth when the attempts run out.

LiteLLM embeds each Gemini tool call's thought signature in its id
(`call_x__thought__<signature>`). Its pre-call hook strips that suffix
whenever the proxy alias does not contain "gemini" (it checks the alias, not
the deployment), and the Gemini converter then sends a placeholder signature
that Google documents as degrading the model. The tool call's
`provider_specific_fields.thought_signature` is never stripped, so replayed
tool calls carry their signature there as well.

LiteLLM parses a tool result's content as JSON when it begins with `{` and
sends an object as Gemini's function response itself rather than under
`content`. Vertex reads `$ref` keys in that object (an OpenAPI document, say)
as references to multimodal response parts and rejects the request with a
400. Tool results that are JSON objects are therefore wrapped as
`{"content": text}` before they reach the proxy, which is how the native
Google provider sends every tool result.
"""

import json
import re
from typing import Any, cast

from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
)

from inspect_ai._util.content import ContentText

from .._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from .._model_output import ChatCompletionChoice, ModelOutput, ModelUsage
from ._gemini_function_calling import (
    DEFAULT_MALFORMED_FUNCTION_MESSAGE,
    FUNCTION_CALLING_HINT,
    MALFORMED_FUNCTION_RETRY_PROMPT,
    malformed_function_apology,
    malformed_function_attempt,
)

THOUGHT_SIGNATURE_SEPARATOR = "__thought__"

MALFORMED_FINISH_REASONS = {"MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL"}

# A function call written as text: Gemini's `call:default_api:bash{...}` and
# the Python-ish `print(default_api.bash(...))` forms.
_TEXT_FUNCTION_CALL = re.compile(
    r"(?m)^\s*(?:call:)?default_api[.:]|print\(\s*default_api\."
)

# How much of a text function call is quoted back to the model on a retry
_MAX_QUOTED_TEXT = 1000


def with_tool_call_signatures(
    messages: list[ChatCompletionMessageParam],
) -> list[ChatCompletionMessageParam]:
    """Carry each tool call's id-embedded thought signature in its own field too."""
    result: list[ChatCompletionMessageParam] = []
    for message in messages:
        if message["role"] == "assistant" and message.get("tool_calls"):
            calls: list[Any] = []
            for call in message["tool_calls"]:
                updated: dict[str, Any] = dict(call)
                _, separator, signature = str(updated.get("id", "")).partition(
                    THOUGHT_SIGNATURE_SEPARATOR
                )
                if (
                    separator
                    and signature
                    and "provider_specific_fields" not in updated
                ):
                    updated["provider_specific_fields"] = {
                        "thought_signature": signature
                    }
                calls.append(updated)
            message = cast(
                ChatCompletionAssistantMessageParam, message | {"tool_calls": calls}
            )
        result.append(message)
    return result


def with_json_tool_results_wrapped(
    messages: list[ChatCompletionMessageParam],
) -> list[ChatCompletionMessageParam]:
    """Tool results that are JSON objects, wrapped so LiteLLM sends them as text.

    LiteLLM's Gemini converter would otherwise send the parsed object as the
    function response, and Vertex rejects `$ref` keys in it (see the module
    docstring). Wrapped as `{"content": text}`, the result is sent exactly as a
    plain-text result is.
    """
    result: list[ChatCompletionMessageParam] = []
    for message in messages:
        if message["role"] == "tool":
            content = message.get("content")
            if isinstance(content, str) and _is_json_object(content):
                message = message | {"content": json.dumps({"content": content})}
        result.append(message)
    return result


def _is_json_object(text: str) -> bool:
    if not text.lstrip().startswith("{"):
        return False
    try:
        return isinstance(json.loads(text), dict)
    except ValueError:
        return False


def with_function_calling_hint(input: list[ChatMessage]) -> list[ChatMessage]:
    """The request's messages with the function-calling hint in the system prompt."""
    if input and isinstance(input[0], ChatMessageSystem):
        system = input[0]
        content: str | list[Any] = (
            f"{system.content}\n{FUNCTION_CALLING_HINT}"
            if isinstance(system.content, str)
            else [*system.content, ContentText(text=FUNCTION_CALLING_HINT)]
        )
        return [system.model_copy(update={"content": content}), *input[1:]]
    return [ChatMessageSystem(content=FUNCTION_CALLING_HINT.strip()), *input]


def malformed_function_call(
    output: ModelOutput, response: dict[str, Any] | None
) -> str | None:
    """What the model produced instead of a function call, or None for a sound turn.

    Recognizes LiteLLM's `native_finish_reason` when it reports one, and
    otherwise a `stop` turn that has neither text nor a tool call (or no
    choice at all), or whose text is a function call written as code.
    """
    if output.empty:
        return DEFAULT_MALFORMED_FUNCTION_MESSAGE
    choice = output.choices[0]
    message = choice.message
    text = message.text.strip()
    if _native_finish_reason(response) in MALFORMED_FINISH_REASONS:
        return text[:_MAX_QUOTED_TEXT] or DEFAULT_MALFORMED_FUNCTION_MESSAGE
    if message.tool_calls:
        return None
    if _TEXT_FUNCTION_CALL.search(text):
        return text[:_MAX_QUOTED_TEXT]
    if not text and choice.stop_reason == "stop":
        return DEFAULT_MALFORMED_FUNCTION_MESSAGE
    return None


def _native_finish_reason(response: dict[str, Any] | None) -> str | None:
    choices = (response or {}).get("choices") or []
    fields = choices[0].get("provider_specific_fields") if choices else None
    reason = fields.get("native_finish_reason") if isinstance(fields, dict) else None
    return reason if isinstance(reason, str) else None


def malformed_function_retry(message: str) -> list[ChatMessage]:
    """The corrective exchange appended to the request before a retry."""
    return [
        ChatMessageAssistant(content=malformed_function_attempt(message)),
        ChatMessageUser(content=MALFORMED_FUNCTION_RETRY_PROMPT),
    ]


def with_malformed_function_apology(output: ModelOutput, message: str) -> ModelOutput:
    """The exhausted output with the model acknowledging its malformed call."""
    apology = ContentText(text=malformed_function_apology(message))
    if output.empty:
        return output.model_copy(
            update={
                "choices": [
                    ChatCompletionChoice(
                        message=ChatMessageAssistant(
                            content=[apology], model=output.model, source="generate"
                        ),
                        stop_reason="unknown",
                    )
                ]
            }
        )
    assistant = output.message
    content = (
        [ContentText(text=assistant.content), apology]
        if isinstance(assistant.content, str) and assistant.content
        else [apology]
        if isinstance(assistant.content, str)
        else [*assistant.content, apology]
    )
    choice = output.choices[0].model_copy(
        update={"message": assistant.model_copy(update={"content": content})}
    )
    return output.model_copy(update={"choices": [choice, *output.choices[1:]]})


def add_usage(total: ModelUsage | None, usage: ModelUsage | None) -> ModelUsage | None:
    """Token usage of all attempts, so discarded attempts are still counted."""
    if total is None or usage is None:
        return usage if total is None else total
    return total + usage
