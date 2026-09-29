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
)

CONTENT_POLICY_MARKERS = ("litellm.contentpolicyviolationerror",)

# the proxy appends routing details after the upstream message
_TRAILER = re.compile(r"\n(model=|\nLiteLLM: model group )")
# `litellm.BadRequestError: ContextWindowExceededError: ` ...
_ERROR_CLASSES = re.compile(r"^(?:(?:litellm\.)?\w+Error:\s*)+")
# `AnthropicError - `, `BedrockException: Context Window Error - `
_PROVIDER_PREFIX = re.compile(r"^\w+(?:Exception|Error)\b[^-{]*-\s*")
_BYTES_REPR = re.compile(r"^b(['\"])(.*)\1$", re.DOTALL)


def litellm_error_model_output(model_name: str, message: str) -> ModelOutput | None:
    """Model output for a context window or content policy error, else None."""
    lowered = message.lower()
    if any(marker in lowered for marker in CONTEXT_WINDOW_MARKERS):
        return ModelOutput.from_content(
            model=model_name,
            content=upstream_message(message),
            stop_reason="model_length",
        )
    if any(marker in lowered for marker in CONTENT_POLICY_MARKERS):
        content = upstream_message(message)
        return ModelOutput.from_content(
            model=model_name,
            content=content,
            stop_reason="content_filter",
            stop_details=StopDetails(type="refusal", explanation=content),
        )
    return None


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
    error = body.get("error", body) if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return message if isinstance(message, str) and message else None
