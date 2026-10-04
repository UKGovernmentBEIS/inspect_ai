"""Fake upstream errors and refusals for LiteLLM proxy error handling tests.

Each scenario is a proxy deployment whose fake upstream answers with one
provider-native error (or a 200 response carrying a refusal). The scenario
name is the deployment alias and the upstream model id, which is how the
fake upstream finds it in a request.
"""

from collections.abc import Callable
from typing import Any, NamedTuple

from .stubs import SSE, Reply, StubRequest

USAGE = {"input_tokens": 10, "output_tokens": 5}


def _anthropic_error(error_type: str, message: str) -> dict[str, Any]:
    return {"type": "error", "error": {"type": error_type, "message": message}}


def _openai_error(
    message: str, error_type: str | None, code: str | None, param: str | None = None
) -> dict[str, Any]:
    return {
        "error": {"message": message, "type": error_type, "param": param, "code": code}
    }


def _gemini_error(code: int, message: str, status: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "status": status}}


def _anthropic_message(text: str, stop_reason: str) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": USAGE,
    }


def _anthropic_sse(message: dict[str, Any]) -> SSE:
    [block] = message["content"]
    return SSE(
        [
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {**message, "content": [], "stop_reason": None},
                },
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": block["text"]},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {
                        "stop_reason": message["stop_reason"],
                        "stop_sequence": None,
                    },
                    "usage": {"output_tokens": USAGE["output_tokens"]},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
    )


def _anthropic_reply(
    message: dict[str, Any],
) -> Callable[[StubRequest], dict[str, Any] | SSE]:
    def reply(request: StubRequest) -> dict[str, Any] | SSE:
        return _anthropic_sse(message) if request.body.get("stream") else message

    return reply


def _anthropic_overloaded_mid_stream(request: StubRequest) -> dict[str, Any] | SSE:
    message = _anthropic_message("Hello", "end_turn")
    if not request.body.get("stream"):
        return message
    start = {**message, "content": [], "stop_reason": None}
    return SSE(
        [
            ("message_start", {"type": "message_start", "message": start}),
            (
                "error",
                {
                    "type": "error",
                    "error": {"type": "overloaded_error", "message": "Overloaded"},
                },
            ),
        ]
    )


def _gemini_safety(request: StubRequest) -> dict[str, Any] | SSE:
    response = {
        "candidates": [
            {
                "finishReason": "SAFETY",
                "index": 0,
                "safetyRatings": [
                    {
                        "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                        "probability": "HIGH",
                        "blocked": True,
                    }
                ],
            }
        ],
        "usageMetadata": {"promptTokenCount": 5, "totalTokenCount": 5},
    }
    return (
        SSE([(None, response)]) if "streamGenerateContent" in request.path else response
    )


class ErrorScenario(NamedTuple):
    provider: str
    """Upstream provider format: anthropic, openai, gemini, bedrock, deepseek,
    moonshot or azure."""

    respond: Reply | dict[str, Any] | Callable[[StubRequest], dict[str, Any] | SSE]
    """An error `Reply`, a 200 body, or a function from the request to a body."""


ERROR_SCENARIOS: dict[str, ErrorScenario] = {
    "anthropic-context": ErrorScenario(
        "anthropic",
        Reply(
            400,
            _anthropic_error(
                "invalid_request_error",
                "prompt is too long: 250000 tokens > 200000 maximum",
            ),
        ),
    ),
    "anthropic-blocked": ErrorScenario(
        "anthropic",
        Reply(
            400,
            _anthropic_error(
                "invalid_request_error", "Output blocked by content filtering policy"
            ),
        ),
    ),
    "anthropic-rate-limit": ErrorScenario(
        "anthropic",
        Reply(
            429,
            _anthropic_error("rate_limit_error", "Rate limit exceeded"),
            {"retry-after": "7"},
        ),
    ),
    "anthropic-overloaded": ErrorScenario(
        "anthropic", Reply(529, _anthropic_error("overloaded_error", "Overloaded"))
    ),
    "anthropic-overloaded-mid-stream": ErrorScenario(
        "anthropic", _anthropic_overloaded_mid_stream
    ),
    "anthropic-refusal": ErrorScenario(
        "anthropic",
        _anthropic_reply(_anthropic_message("I can't help with that.", "refusal")),
    ),
    "anthropic-context-stop": ErrorScenario(
        "anthropic",
        _anthropic_reply(
            _anthropic_message("partial", "model_context_window_exceeded")
        ),
    ),
    "openai-context": ErrorScenario(
        "openai",
        Reply(
            400,
            _openai_error(
                "Your input exceeds the context window of this model. Please "
                "adjust your input and try again.",
                "invalid_request_error",
                "context_length_exceeded",
                "input",
            ),
        ),
    ),
    "openai-invalid-prompt": ErrorScenario(
        "openai",
        Reply(
            400,
            _openai_error(
                "Invalid prompt: your prompt was flagged as potentially violating "
                "our usage policy. Please try again with a different prompt.",
                "invalid_request_error",
                "invalid_prompt",
            ),
        ),
    ),
    "openai-cyber": ErrorScenario(
        "openai",
        Reply(
            400,
            _openai_error(
                "This request was blocked under our cyber policy.",
                "invalid_request_error",
                "cyber_policy",
            ),
        ),
    ),
    "gemini-context": ErrorScenario(
        "gemini",
        Reply(
            400,
            _gemini_error(
                400,
                "The input token count (1200000) exceeds the maximum number of "
                "tokens allowed (1048576).",
                "INVALID_ARGUMENT",
            ),
        ),
    ),
    "gemini-rate-limit": ErrorScenario(
        "gemini",
        Reply(
            429,
            _gemini_error(429, "Resource has been exhausted.", "RESOURCE_EXHAUSTED"),
        ),
    ),
    "gemini-unavailable": ErrorScenario(
        "gemini",
        Reply(503, _gemini_error(503, "The model is overloaded.", "UNAVAILABLE")),
    ),
    "gemini-safety": ErrorScenario("gemini", _gemini_safety),
    "bedrock-context": ErrorScenario(
        "bedrock",
        Reply(
            400,
            {"message": "Input is too long for requested model."},
            {"x-amzn-ErrorType": "ValidationException"},
        ),
    ),
    "bedrock-guardrail": ErrorScenario(
        "bedrock",
        {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "Sorry, I can't answer that."}],
                }
            },
            "stopReason": "guardrail_intervened",
            "usage": {"inputTokens": 5, "outputTokens": 5, "totalTokens": 10},
            "metrics": {"latencyMs": 1},
        },
    ),
    "deepseek-context": ErrorScenario(
        "deepseek",
        Reply(
            400,
            _openai_error(
                "This model's maximum context length is 65536 tokens. However, you "
                "requested 80000 tokens.",
                "invalid_request_error",
                "invalid_request_error",
            ),
        ),
    ),
    "moonshot-context": ErrorScenario(
        "moonshot",
        Reply(
            400,
            _openai_error(
                "Invalid request: Your request exceeded model token limit: 262144",
                "invalid_request_error",
                None,
            ),
        ),
    ),
    "azure-content-filter": ErrorScenario(
        "azure",
        Reply(
            400,
            {
                "error": {
                    "message": "The response was filtered due to the prompt "
                    "triggering Azure OpenAI's content management policy.",
                    "type": None,
                    "param": "prompt",
                    "code": "content_filter",
                    "status": 400,
                }
            },
        ),
    ),
}


def error_route(request: StubRequest) -> dict[str, Any] | SSE | Reply | None:
    """Fake upstream router for `ERROR_SCENARIOS`."""
    scenario = ERROR_SCENARIOS.get(_scenario_name(request))
    if scenario is None:
        return None
    respond = scenario.respond
    return respond(request) if callable(respond) else respond


def _scenario_name(request: StubRequest) -> str:
    path = request.path.split("?")[0]
    for marker in ("/model/", "/models/", "/deployments/"):
        if marker in path:
            return path.split(marker)[1].split("/")[0].split(":")[0]
    return str((request.body or {}).get("model"))


def error_deployments(upstream_url: str) -> list[dict[str, Any]]:
    """Proxy deployments for `ERROR_SCENARIOS`, served from `upstream_url`."""
    return [
        {"model_name": name, "litellm_params": _params(name, scenario, upstream_url)}
        for name, scenario in ERROR_SCENARIOS.items()
    ]


def _params(name: str, scenario: ErrorScenario, url: str) -> dict[str, Any]:
    match scenario.provider:
        case "anthropic":
            return {"model": f"anthropic/{name}", "api_base": url, "api_key": "fake"}
        case "gemini":
            return {
                "model": f"gemini/{name}",
                "api_base": f"{url}/v1beta",
                "api_key": "fake",
            }
        case "bedrock":
            return {
                "model": f"bedrock/converse/{name}",
                "api_base": url,
                "aws_access_key_id": "fake",
                "aws_secret_access_key": "fake",
                "aws_region_name": "us-east-1",
            }
        case "azure":
            return {
                "model": f"azure/{name}",
                "api_base": url,
                "api_key": "fake",
                "api_version": "2024-10-21",
            }
        case provider:
            return {
                "model": f"{provider}/{name}",
                "api_base": f"{url}/v1",
                "api_key": "fake",
            }
