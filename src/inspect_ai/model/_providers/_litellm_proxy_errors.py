"""Recognize context window and content policy errors from a LiteLLM proxy.

The proxy sets an error's `code` to its HTTP status (e.g. `"400"`), so the
code-based matching Inspect uses for OpenAI errors never fires. The error
class LiteLLM mapped the upstream error to survives only as a prefix of the
message (`litellm.ContextWindowExceededError: ...`). Some upstream errors
reach the client without that prefix: messages LiteLLM does not recognize
(OpenAI's current context window message, Moonshot's), and errors on paths
that skip LiteLLM's mapping (Gemini chat streaming), so the upstream
provider's wording is matched as well.
"""

import json
import re
from typing import Any

from openai.types.chat import ChatCompletion

from .._model_output import ModelOutput, StopDetails

CONTEXT_WINDOW_MARKERS = (
    "litellm.contextwindowexceedederror",
    "context_length_exceeded",
    "maximum context length",  # openai (legacy), deepseek, vllm
    "exceeds the context window",  # openai
    "prompt is too long",  # anthropic, fireworks
    "input is too long",  # bedrock
    "exceeds the maximum number of tokens allowed",  # gemini
    "exceeded model token limit",  # moonshot
    "input_too_large",  # xai
)

CONTENT_POLICY_MARKERS = ("litellm.contentpolicyviolationerror",)

XAI_REFUSAL_MARKERS = (
    # the grok provider's markers; LiteLLM does not map xAI refusals.
    # `safety_check` alone also appears in OpenAI's computer use fields
    # (`acknowledged_safety_checks`), so these apply only to xAI models
    "safety_check",
    "can't help with that request",
)

# the proxy appends routing details after the upstream message
_TRAILER = re.compile(r"\n(model=|\nLiteLLM: model group )")
# `litellm.BadRequestError: ContextWindowExceededError: ` ...
_ERROR_CLASSES = re.compile(r"^(?:(?:litellm\.)?\w+Error:\s*)+")
# `AnthropicError - `, `BedrockException: Context Window Error - `
_PROVIDER_PREFIX = re.compile(r"^\w+(?:Exception|Error)\b[^-{]*-\s*")
_BYTES_REPR = re.compile(r"^b(['\"])(.*)\1$", re.DOTALL)


def litellm_error_model_output(
    model_name: str, message: str, xai: bool = False
) -> ModelOutput | None:
    """Model output for a context window or content policy error, else None.

    Args:
        model_name: Model name for the output.
        message: The proxy's error message.
        xai: The model is an xAI model, whose refusals are recognized by
            `XAI_REFUSAL_MARKERS`.
    """
    lowered = message.lower()
    if any(marker in lowered for marker in CONTEXT_WINDOW_MARKERS):
        return ModelOutput.from_content(
            model=model_name,
            content=upstream_message(message),
            stop_reason="model_length",
        )
    policy_markers = CONTENT_POLICY_MARKERS + (XAI_REFUSAL_MARKERS if xai else ())
    if any(marker in lowered for marker in policy_markers):
        content = upstream_message(message)
        return ModelOutput.from_content(
            model=model_name,
            content=content,
            stop_reason="content_filter",
            stop_details=StopDetails(type="refusal", explanation=content),
        )
    return None


def with_upstream_refusals(completion: ChatCompletion) -> ChatCompletion:
    """The completion with each message's upstream `refusal` restored.

    On non-streamed chat, LiteLLM moves the upstream `message.refusal` into
    `message.provider_specific_fields` and returns `refusal: null` (1.96 and
    later, every route), so the refusal would read as an empty response.
    Streamed deltas keep `refusal`.
    """
    choices = []
    for choice in completion.choices:
        message = choice.message
        fields = getattr(message, "provider_specific_fields", None)
        refusal = fields.get("refusal") if isinstance(fields, dict) else None
        if message.refusal is None and isinstance(refusal, str) and refusal:
            message = message.model_copy(update={"refusal": refusal})
            choice = choice.model_copy(update={"message": message})
        choices.append(choice)
    return completion.model_copy(update={"choices": choices})


def upstream_message(message: str) -> str:
    """The upstream provider's message within a LiteLLM error message.

    Removes the routing trailer, LiteLLM's error class and provider prefixes,
    and the JSON (or bytes) wrapper of an upstream error body. Returns the
    message unchanged if nothing is left.
    """
    text = _TRAILER.split(message, maxsplit=1)[0].strip()
    text = _ERROR_CLASSES.sub("", text)
    text = _PROVIDER_PREFIX.sub("", text).strip()
    bytes_repr = _BYTES_REPR.match(text)
    if bytes_repr:
        text = bytes_repr.group(2)
    return _json_error_message(text) or text or message


def _json_error_message(text: str) -> str | None:
    try:
        body: Any = json.loads(text)
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    error = body.get("error", body)
    if isinstance(error, dict):
        # `{"error": {"message": ...}}`
        message = error.get("message")
    else:
        # `{"error": "Bad Request", "message": ...}`, or xAI's
        # `{"code": ..., "error": "..."}` with the message in `error`
        message = body.get("message") or error
    return message if isinstance(message, str) and message else None
