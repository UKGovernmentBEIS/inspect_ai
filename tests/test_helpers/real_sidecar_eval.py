"""Evals run through the real sentinel sidecar, in a process of their own, for `tests/sentinel/test_sentinel_sidecar_real.py`.

The test suite keeps `inspect_sentinel` from being imported, so that Inspect never loads it for a user who configures no sentinel. This module is run as a script, in a process where it can be imported: `python -m test_helpers.real_sidecar_eval RESULTS LOG_DIR`, from the `tests` directory. It runs every case in `CASES`, and writes what came of each to `RESULTS` as JSON.

Importing this module imports nothing of `inspect_sentinel`, so the tests can read `CASES` from it.
"""

import json
import sys
import traceback
from collections.abc import Callable
from typing import Any, NamedTuple

MODELS = {
    "anthropic": ("anthropic/claude-haiku-4-5", "http://proxy.test"),
    "openai": ("openai/gpt-4.1-mini", "http://proxy.test/v1"),
    "openai-api": ("openai-api/together/meta-llama-3", "http://proxy.test/v1"),
}
"""A model of each provider family that can go through a sidecar, with the base URL its proxy has."""


class Case(NamedTuple):
    """One sample run through the sidecar."""

    name: str
    provider: str = "anthropic"
    task: str = "weather_desk"
    sample_id: int | str = 7
    change: str | None = None
    """What the proxy changes in the model request's headers before the sidecar is handed them, after Inspect signed them: `request id` or `epoch`."""


CASES = [
    # each provider family, whose calls are signed by the same request hook
    Case("anthropic"),
    Case("openai", provider="openai"),
    Case("openai-api", provider="openai-api"),
    # Values the two sides could write differently as they sign: ints and
    # strings of digits, text outside ASCII and outside the basic plane, and
    # JSON's own punctuation.
    Case("a string of digits", sample_id="7"),
    Case("a large int", sample_id=2**62),
    Case("an id outside ASCII", sample_id="Zürich-日本"),
    Case("an id outside the basic plane", sample_id="🙂"),
    Case("an id of JSON punctuation", sample_id='a,"b"]\\c'),
    Case("a task outside ASCII", task="météo_東京", sample_id="s1"),
    # the check is the sidecar's own, so it is shown to refuse as well as take
    Case("another request id", change="request id"),
    Case("another epoch", change="epoch"),
]

Headers = dict[str, str]


def _changed(headers: Headers, change: str | None) -> Headers:
    if change == "request id":
        return headers | {"x-irid": "another-request"}
    if change == "epoch":
        context = json.loads(headers["x-inspect-context"])
        return headers | {"x-inspect-context": json.dumps(context | {"epoch": 2})}
    assert change is None, change
    return headers


def _anthropic_reply(asked: dict[str, Any]) -> tuple[bytes, str]:
    message: dict[str, Any] = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-test",
        "content": [{"type": "text", "text": "Sunny."}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    if not asked.get("stream"):
        return json.dumps(message).encode(), "application/json"

    # every event of a streamed message, as the sidecar reads a reply only
    # once its stream is complete
    def event(data: dict[str, Any]) -> str:
        return f"event: {data['type']}\ndata: {json.dumps(data)}\n\n"

    start = {**message, "content": [], "stop_reason": None}
    stop = {"stop_reason": "end_turn", "stop_sequence": None}
    events: list[dict[str, Any]] = [
        {"type": "message_start", "message": start},
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Sunny."},
        },
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": stop, "usage": {"output_tokens": 1}},
        {"type": "message_stop"},
    ]
    return "".join(event(data) for data in events).encode(), "text/event-stream"


def _chat_reply(asked: dict[str, Any]) -> tuple[bytes, str]:
    assert not asked.get("stream"), "a streamed chat completion isn't answered here"
    reply = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-test",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Sunny."},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    return json.dumps(reply).encode(), "application/json"


def _responses_reply(asked: dict[str, Any]) -> tuple[bytes, str]:
    assert not asked.get("stream"), "a streamed response isn't answered here"
    reply = {
        "id": "resp_1",
        "object": "response",
        "created_at": 1,
        "model": "gpt-test",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": "Sunny.", "annotations": []}
                ],
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }
    return json.dumps(reply).encode(), "application/json"


_ROUTES: dict[str, tuple[str, Callable[[dict[str, Any]], tuple[bytes, str]]]] = {
    "/v1/messages": ("anthropic", _anthropic_reply),
    "/v1/chat/completions": ("openai", _chat_reply),
    "/v1/responses": ("openai", _responses_reply),
}
"""Each provider's route for model calls: the provider the sidecar reads it as, and the provider's reply."""


def _run(case: Case, log_dir: str) -> dict[str, Any]:
    """Run a case's sample through a sidecar of its own, and give what came of it."""
    # imported here, so that importing this module imports nothing of the
    # sidecar
    import httpx2
    from inspect_sentinel import (
        Context,
        Decision,
        Escalations,
        Protocol,
        Step,
        protocol,
    )
    from inspect_sentinel.sidecar import Handler, Refuse, Replace, Reply, Request
    from inspect_sentinel.sidecar._eval_endpoint import eval_routes
    from starlette.applications import Starlette
    from starlette.requests import Request as HttpRequest
    from starlette.responses import Response
    from starlette.routing import Route

    from inspect_ai import Task, eval
    from inspect_ai.dataset import Sample
    from inspect_ai.model import get_model
    from inspect_ai.solver import generate

    seen: list[dict[str, Any]] = []
    proxy_errors: list[str] = []

    @protocol
    def notes_each_sample() -> Protocol:
        """Keep the sample the sidecar says each step is of, and let every step go on."""

        async def decide(
            context: Context, step: Step, escalations: Escalations
        ) -> Decision | None:
            named = context.proxy.inspect if context.proxy is not None else None
            seen.append(
                {
                    "eval_id": named.eval_id,
                    "task": named.task,
                    "sample_id": named.sample_id,
                    "sample_id_type": type(named.sample_id).__name__,
                    "sample_uuid": named.sample_uuid,
                    "epoch": named.epoch,
                }
                if named is not None
                else {}
            )
            return Decision.proceed()

        return decide

    handler = Handler(notes_each_sample())
    ids = iter(range(1_000))

    def refusal(status: int, message: str) -> Response:
        return Response(
            json.dumps({"error": {"type": "error", "message": message}}),
            status_code=status,
            media_type="application/json",
        )

    async def model_call(http: HttpRequest) -> Response:
        # A model request and its reply are put to the handler, as a proxy
        # hook does, with the stand-in provider's reply between them.
        try:
            id = str(next(ids))
            provider, reply = _ROUTES[http.url.path]
            body = await http.body()
            asked = await handler.request(
                Request(
                    id=id,
                    provider=provider,
                    model="m",
                    user=None,
                    body=body,
                    headers=_changed(dict(http.headers), case.change),
                )
            )
            if isinstance(asked, Refuse):
                return refusal(asked.status, asked.message)
            sent = json.loads(asked.body if isinstance(asked, Replace) else body)
            answered, content_type = reply(sent)
            replied = await handler.reply(
                Reply(
                    id=id,
                    provider=provider,
                    model="m",
                    user=None,
                    status=200,
                    content_type=content_type,
                    body=answered,
                )
            )
            if isinstance(replied, Refuse):
                return refusal(replied.status, replied.message)
            passed_on = replied.body if isinstance(replied, Replace) else answered
            return Response(passed_on, media_type=content_type)
        except Exception:
            # Kept for the test, and answered with a status no client
            # retries: a 500 here would be retried, with a backoff, for as
            # long as the sample ran.
            proxy_errors.append(traceback.format_exc())
            return refusal(400, "The stand-in for a model proxy failed.")

    proxy = Starlette(
        routes=[
            *eval_routes(handler, max_body_bytes=1_000_000),
            *(Route(path, model_call, methods=["POST"]) for path in _ROUTES),
        ]
    )
    name, base_url = MODELS[case.provider]
    model = get_model(
        name,
        base_url=base_url,
        api_key="test-key",
        memoize=False,
        http_client=httpx2.AsyncClient(transport=httpx2.ASGITransport(app=proxy)),
    )
    [log] = eval(
        Task(
            dataset=[Sample(input="Hi.", id=case.sample_id)],
            solver=generate(),
            name=case.task,
        ),
        model=model,
        # a call the sidecar didn't judge fails the sample
        sentinel_proxy="required",
        # bounded, so that a call that keeps failing ends the sample
        max_retries=1,
        time_limit=60,
        log_dir=log_dir,
        display="none",
    )
    sample = log.samples[0] if log.samples else None
    return {
        "status": log.status,
        "error": log.error.message if log.error is not None else None,
        "eval_id": log.eval.eval_id,
        "sample_uuid": sample.uuid if sample is not None else None,
        "sample_error": (
            sample.error.message
            if sample is not None and sample.error is not None
            else None
        ),
        "seen": seen,
        "proxy_errors": proxy_errors,
    }


def main(results: str, log_dir: str) -> None:
    import inspect_sentinel

    found: dict[str, Any] = {"sidecar": inspect_sentinel.__file__, "cases": {}}
    for case in CASES:
        try:
            found["cases"][case.name] = _run(case, log_dir)
        except Exception:
            # every case is reported, so one that can't run doesn't hide the rest
            found["cases"][case.name] = {"raised": traceback.format_exc()}
    with open(results, "w", encoding="utf-8") as file:
        json.dump(found, file)


if __name__ == "__main__":
    main(*sys.argv[1:])
