"""A sentinel beside the model refuses a reply and names its decision in a header."""

import importlib.util
import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
import tenacity
from pydantic import JsonValue

from inspect_ai import Task, eval
from inspect_ai._sentinel._header import (
    SENTINEL_DECISION_HEADER,
    SentinelRejectedError,
)
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.agent import AgentState
from inspect_ai.agent._bridge._errors import PROVIDER_ERROR_KEY
from inspect_ai.agent._bridge.sandbox.service import _forward_provider_errors
from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
from inspect_ai.dataset import Sample
from inspect_ai.model import GenerateConfig, Model, get_model
from inspect_ai.scorer import includes
from inspect_ai.solver import generate

# These tests intentionally stay with the sentinel suite and share its
# inspect_sentinel skip, even though header handling works without the package.
# Please keep this convention; extra tests without the package aren't needed.
if importlib.util.find_spec("inspect_sentinel") is None:
    pytest.skip("inspect_sentinel is not installed", allow_module_level=True)

_ANTHROPIC_EVENTS: list[dict[str, Any]] = [
    {
        "type": "message_start",
        "message": {
            "id": "test",
            "type": "message",
            "role": "assistant",
            "model": "test-model",
            "content": [],
            "stop_reason": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    },
    {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""},
    },
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "sunny"},
    },
    {"type": "content_block_stop", "index": 0},
    {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn"},
        "usage": {"output_tokens": 1},
    },
    {"type": "message_stop"},
]

_OPENAI_COMPLETION = {
    "id": "test",
    "object": "chat.completion",
    "created": 0,
    "model": "test-model",
    "choices": [
        {
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "sunny"},
        }
    ],
}


def _anthropic_reply() -> httpx2.Response:
    # the Anthropic provider streams
    return httpx2.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text="".join(
            f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
            for event in _ANTHROPIC_EVENTS
        ),
    )


def _openai_reply() -> httpx2.Response:
    return httpx2.Response(200, json=_OPENAI_COMPLETION)


PROVIDERS = pytest.mark.parametrize(
    ("name", "base_url", "reply"),
    [
        ("anthropic/claude-sonnet-4-6", "https://example.com", _anthropic_reply),
        ("openai/gpt-4o", "https://example.com/v1", _openai_reply),
    ],
    ids=["anthropic", "openai"],
)

# Both providers turn a 400 into ordinary output when its message reads like a
# content filter's, which must not hide the sentinel's decision.
REASONS = pytest.mark.parametrize(
    "reason",
    [
        "A sentinel rejected the call to bash: not allowed.",
        "A sentinel rejected the call to bash: blocked by content filtering.",
    ],
    ids=["plain", "worded_like_a_content_filter"],
)


def _refused(decision: str | None, reason: str, status: int = 400) -> httpx2.Response:
    return httpx2.Response(
        status,
        headers={SENTINEL_DECISION_HEADER: decision} if decision else {},
        json={
            "type": "error",
            "error": {"type": "invalid_request_error", "message": reason},
        },
    )


def _model(
    name: str, base_url: str, *responses: httpx2.Response, max_retries: int = 0
) -> Model:
    script = list(responses)

    async def respond(request: httpx2.Request) -> httpx2.Response:
        return script.pop(0)

    transport = httpx2.MockTransport(respond)
    return get_model(
        name,
        api_key="key",
        http_client=httpx2.AsyncClient(transport=transport),
        base_url=base_url,
        max_retries=max_retries,
        memoize=False,
    )


@PROVIDERS
@REASONS
async def test_reject_asks_the_model_again(
    name: str, base_url: str, reply: Callable[[], httpx2.Response], reason: str
) -> None:
    model = _model(name, base_url, _refused("reject", reason), reply())

    output = await model.generate("What is the weather?")

    assert output.completion == "sunny"


@PROVIDERS
@REASONS
async def test_terminate_raises_with_the_reason(
    name: str,
    base_url: str,
    reply: Callable[[], httpx2.Response],
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model(name, base_url, _refused("terminate", reason), reply())
    monkeypatch.setattr(model.api, "should_retry", lambda ex: True)

    with pytest.raises(TerminateSampleError) as raised:
        await model.generate("hello", config=GenerateConfig(max_retries=1))

    # Anthropic's provider lowercases an error it turns into output
    told = raised.value.reason
    assert told == reason or reason.lower() in told


@PROVIDERS
async def test_reject_stops_at_max_retries(
    name: str, base_url: str, reply: Callable[[], httpx2.Response]
) -> None:
    reason = "A sentinel rejected the call to bash: not allowed."
    model = _model(
        name, base_url, _refused("reject", reason), _refused("reject", reason)
    )

    with pytest.raises(tenacity.RetryError) as raised:
        await model.generate("hello", config=GenerateConfig(max_retries=1))

    last = raised.value.last_attempt.exception()
    assert isinstance(last, SentinelRejectedError) and str(last) == reason


@PROVIDERS
@pytest.mark.parametrize(
    ("reason", "status"),
    [
        ("A sentinel rejected the call to bash: not allowed.", 400),
        ("A sentinel rejected the call to bash: blocked by content filtering.", 400),
        ("A sentinel rejected the call to bash: not allowed.", 503),
    ],
    ids=["plain", "worded_like_a_content_filter", "503"],
)
async def test_exhausted_reject_is_forwarded_without_warning(
    name: str,
    base_url: str,
    reply: Callable[[], httpx2.Response],
    reason: str,
    status: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    model = _model(name, base_url, _refused("reject", reason, status=status))
    bridge = SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
    )

    async def request(json_data: dict[str, JsonValue]) -> dict[str, JsonValue]:
        await model.generate("hello", config=GenerateConfig(max_retries=0))
        raise AssertionError("rejected generation unexpectedly succeeded")

    result = await _forward_provider_errors(request, bridge)({})

    payload = result[PROVIDER_ERROR_KEY]
    assert isinstance(payload, dict)
    assert payload["status"] == status
    message = payload["message"]
    assert isinstance(message, str) and reason.lower() in message.lower()
    assert not bridge._failure_requested.is_set()
    assert not any("non-provider error" in record.message for record in caplog.records)


@PROVIDERS
@pytest.mark.parametrize("decision", [None, "continue"])
async def test_error_that_asks_nothing_is_handled_as_before(
    name: str, base_url: str, reply: Callable[[], httpx2.Response], decision: str | None
) -> None:
    reason = "A sentinel rejected the call to bash: blocked by content filtering."
    model = _model(name, base_url, _refused(decision, reason))

    output = await model.generate("hello")

    assert output.stop_reason == "content_filter"


@PROVIDERS
async def test_decision_on_an_attempt_the_sdk_retried_is_dropped(
    name: str, base_url: str, reply: Callable[[], httpx2.Response]
) -> None:
    model = _model(
        name,
        base_url,
        _refused("terminate", "not the last word", status=503),
        reply(),
        max_retries=1,
    )

    output = await model.generate("What is the weather?")

    assert output.completion == "sunny"


def _run(model: Model) -> Any:
    task = Task(
        dataset=[Sample(input="What is the weather?", target="sunny")],
        solver=generate(),
        scorer=includes(),
    )
    return eval(task, model=model, display="none")[0]


@PROVIDERS
def test_rejected_attempt_is_logged_and_the_sample_carries_on(
    name: str, base_url: str, reply: Callable[[], httpx2.Response]
) -> None:
    reason = "A sentinel rejected the call to bash: not allowed."
    log = _run(_model(name, base_url, _refused("reject", reason), reply()))

    assert log.status == "success", log.error
    sample = log.samples[0]
    assert sample.scores["includes"].value == "C"
    errors = [e.error for e in sample.events if e.event == "model" and e.error]
    assert len(errors) == 1 and reason in errors[0]


@PROVIDERS
def test_terminated_sample_keeps_the_reason_and_is_scored(
    name: str, base_url: str, reply: Callable[[], httpx2.Response]
) -> None:
    reason = "A sentinel ended this run at the call to bash."
    log = _run(_model(name, base_url, _refused("terminate", reason)))

    assert log.status == "success", log.error
    sample = log.samples[0]
    assert sample.limit is not None
    assert (sample.limit.type, sample.limit.reason) == ("operator", reason)
    assert sample.scores["includes"].value == "I"
