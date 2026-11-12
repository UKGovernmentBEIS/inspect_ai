"""A person's review of a call that a sentinel in a sidecar asks for, and what a call with no sidecar is spared of it.

The stand-in here keeps a call a person is asked about as one model call under its `x-irid`, as the sidecar does: it answers the call's request with an error while the question is open, and afterwards answers the same request, sent to its held-reply path, with the provider's reply it held.
"""

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, cast

import anyio
import httpx2
import pytest
from test_helpers.stand_in_sidecar import (
    _MODEL_ROUTES,
    ENDPOINT,
    UNAUTHORIZED,
    StandInSidecar,
    Turn,
)

from inspect_ai import Task
from inspect_ai import eval as inspect_eval
from inspect_ai._sentinel._sidecar import _review as review_module
from inspect_ai._sentinel._sidecar._act import refused_output
from inspect_ai._sentinel._sidecar._endpoint import QUESTION_ANSWERED
from inspect_ai._sentinel._sidecar._received import (
    HELD_REPLY_PATH,
    ReceivedCall,
    _received,
    receiving_call,
    request_id_to_reuse,
    use_held_reply_path,
)
from inspect_ai._sentinel._sidecar._review import FAILED_TRY, FAILURE_FETCHES
from inspect_ai.approval import Approval
from inspect_ai.approval._approval import ApprovalDecision
from inspect_ai.approval._human import acp as acp_module
from inspect_ai.approval._human import approver as approver_module
from inspect_ai.dataset import Sample
from inspect_ai.event import InfoEvent, LoggerEvent, ModelEvent, SentinelEvent
from inspect_ai.log import EvalLog, EvalSample
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.model._providers.util.hooks import HttpxHooks
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver, use_tools
from inspect_ai.tool import Tool, ToolCall, ToolCallView, tool

_LOOKED_UP: list[str] = []


@tool
def weather() -> Tool:
    async def execute(city: str) -> str:
        """Look up the weather.

        Args:
            city: The city.
        """
        _LOOKED_UP.append(city)
        return f"Sunny in {city}."

    return execute


@dataclass
class _Paused:
    """A model call the stand-in asked a person about, kept as one model call under its `x-irid`."""

    stage: str
    """`tool_call` for a call paused at its reply, which the stand-in holds; `tool_result` for one paused at its request, which went to no provider yet."""
    route: str
    state: str = "awaiting_review"
    turn: Turn | None = None
    """The provider's reply, once the provider was called."""
    judgment: dict[str, Any] | None = None
    failure: dict[str, Any] | None = None
    reason: str | None = None
    tries: int = 0
    reviews: list[dict[str, Any]] = field(default_factory=list)
    """What became of each question asked about the call, as `request_result` gives it."""


@dataclass
class ReviewingSidecar(StandInSidecar):
    """A stand-in whose sentinel asks a person about model calls, as a sidecar that pauses the model call does."""

    pauses: list[str] = field(default_factory=list)
    """Where each new model call is paused, in order: `tool_call` or `tool_result`. A call past the last isn't paused."""
    paused: dict[str, _Paused] = field(default_factory=dict)
    cancelled: list[str] = field(default_factory=list)
    held_reply_statuses: list[int] = field(default_factory=list)
    """Error statuses the held-reply path answers with first, in order, before it answers with what it holds. They are the sidecar's own refusals, without the header that marks a provider's error."""
    expires: bool = False
    """Whether a question times out at the sidecar before the person answers: the sentinel is given the cautious answer, a rejection, and the person's answer is refused as one for a question that has closed."""
    judged_step: bool = False
    """Whether the judgment of a call a person approved has the step that asked, naming its question."""
    records_dropped: bool = False
    """Whether the sidecar no longer holds the call's records once a person has answered."""
    error_passing_asks: int = 0
    """How many times, once the provider has failed a try, `request_result` still says the sidecar awaits the reply: the error's body is passing, and the sidecar tells of the error only once it is whole."""
    failure_message: str | None = None
    """The message of the provider's error that the held-reply path serves, in Anthropic's format, in place of the stand-in's own."""
    error_cut_off: int = 0
    """How many times the held-reply path's answer with the provider's error has its connection fail part way through the body, after its headers, the sidecar's marker among them, have come."""
    error_lost: bool = False
    """Whether the try that is sent on is answered with the sidecar's own "pending review" when the provider fails it, and not with the provider's error: what Inspect holds when a try of its was answered while another was with the provider."""

    def __post_init__(self) -> None:
        assert self.info is not None
        self.info["review"] = True
        self.methods.setdefault("pending_questions", self._pending_questions)
        self.methods.setdefault("answer_question", self._answer_question)
        self.methods.setdefault("cancel_request", self._cancel_request)

    @property
    def held_reply_requests(self) -> list[httpx2.Request]:
        return [r for r in self.requests if r.url.path == HELD_REPLY_PATH]

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        context = request.headers.get("x-inspect-context")
        if path == HELD_REPLY_PATH:
            self.requests.append(request)
            return self._held_reply(request)
        if path in _MODEL_ROUTES and context is not None:
            irid = request.headers.get("x-irid")
            if irid in self.paused or self.pauses:
                self.requests.append(request)
                unread = self._unread(context, irid)
                if unread is not None:
                    self.refused.append(unread)
                    return _refusal(unread)
                assert irid is not None
                return self._paused_call(request, irid)
        if path == ENDPOINT:
            call = json.loads(request.content)
            if (
                call["method"] == "request_result"
                and call["params"].get("id") in self.paused
            ):
                self.methods["request_result"] = self._request_result
            else:
                self.methods.pop("request_result", None)
        return super()._handle(request)

    def _paused_call(self, request: httpx2.Request, irid: str) -> httpx2.Response:
        asked = json.loads(request.content)
        paused = self.paused.get(irid)
        if paused is None:
            paused = self.paused[irid] = _Paused(self.pauses.pop(0), request.url.path)
            paused.tries = 1
            if paused.stage == "tool_call":
                # the provider replied, and the stand-in holds the reply
                paused.turn = self.turns.pop(0) if self.turns else Turn()
            return _refusal("pending review")
        paused.tries += 1
        if paused.state != "awaiting_request":
            # no other try is sent on, and a call that has ended is read
            # with `request_result`
            return _refusal("pending review")
        turn = self.turns.pop(0) if self.turns else Turn()
        if turn.status != 200:
            paused.reason = "provider_error"
            paused.failure = {
                "try_number": paused.tries,
                "reply": {"status": turn.status, "headers": {}, "body": ""},
            }
            if self.error_lost:
                return _refusal("pending review")
        else:
            paused.turn = turn
            paused.state = "decided"
            paused.judgment = {"outcome": "proceed", "steps": []}
        return _MODEL_ROUTES[paused.route](turn, bool(asked.get("stream")), asked)

    def _held_reply(self, request: httpx2.Request) -> httpx2.Response:
        context = request.headers.get("x-inspect-context")
        irid = request.headers.get("x-irid")
        unread = (
            self._unread(context, irid)
            if context is not None
            else "the request has no x-inspect-context"
        )
        if unread is not None:
            self.refused.append(unread)
            return _refusal(unread)
        if self.held_reply_statuses:
            return httpx2.Response(
                self.held_reply_statuses.pop(0),
                json={"error": {"type": "error", "message": "Not now."}},
            )
        paused = self.paused.get(irid or "")
        asked = json.loads(request.content)
        if (
            paused is not None
            and paused.state == "awaiting_request"
            and paused.reason == "provider_error"
            and paused.failure is not None
        ):
            # the provider's error, marked with the try it is of, and not to
            # be sent again for by the SDK itself
            failed = _MODEL_ROUTES[paused.route](
                Turn(status=paused.failure["reply"]["status"]),
                bool(asked.get("stream")),
                asked,
            )
            if self.failure_message is not None:
                failed = httpx2.Response(
                    paused.failure["reply"]["status"],
                    json={
                        "type": "error",
                        "error": {
                            "type": "invalid_request_error",
                            "message": self.failure_message,
                        },
                    },
                )
            failed.headers[FAILED_TRY] = str(paused.failure["try_number"])
            failed.headers["x-should-retry"] = "false"
            if self.error_cut_off > 0:
                self.error_cut_off -= 1
                return httpx2.Response(
                    failed.status_code, headers=failed.headers, stream=_CutOff()
                )
            return failed
        if (
            paused is None
            or paused.turn is None
            or paused.state != "decided"
            or (paused.judgment or {}).get("outcome") != "proceed"
        ):
            return _refusal("no held reply")
        return _MODEL_ROUTES[paused.route](
            paused.turn, bool(asked.get("stream")), asked
        )

    def _unaccepted(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if method != "answer_question":
            return super()._unaccepted(method, params)
        # an answer's signature covers the answer
        held = self.tokens.get(params.get("eval_id", ""))
        if held is None:
            return self._refuse(UNAUTHORIZED, "no token held for the eval")
        why = self._signed(
            held,
            [
                method,
                params["eval_id"],
                params["timestamp"],
                params["id"],
                params["decision"],
                params.get("reason") or "",
            ],
            params["timestamp"],
            params["mac"],
        )
        if why is not None:
            return self._refuse(UNAUTHORIZED, why)
        if self.expires:
            paused = self.paused[params["id"].removeprefix("question_")]
            if paused.state == "awaiting_review":
                # it timed out twelve minutes before the person answered
                ended = time.time() - 12 * 60
                paused.reviews.append(
                    {
                        "id": params["id"],
                        "try_number": 1,
                        "stage": paused.stage,
                        "call": "call_1",
                        "asked": ended - 60,
                        "resolution": "timed_out",
                        "resolved": ended,
                    }
                )
                self._rejected(paused, "No person answered in time.")
            return self._refuse(QUESTION_ANSWERED, "The question has closed.")
        return None

    def _rejected(self, paused: _Paused, reason: str) -> None:
        message = ChatMessageAssistant(
            content="Checking.",
            tool_calls=[ToolCall(id="call_1", function="weather", arguments={})],
        )
        paused.state = "decided"
        paused.judgment = {
            "outcome": "reject",
            "steps": [],
            "withheld": {
                "message": message.model_dump(mode="json", exclude_none=True),
                "results": {"call_1": reason},
                "redacted": ["call_1"],
            },
        }

    def _request_result(self, params: dict[str, Any]) -> dict[str, Any]:
        paused = self.paused[params["id"]]
        if self.records_dropped and paused.reviews:
            return {"id": params["id"], "records": "dropped"}
        if paused.failure is not None and self.error_passing_asks > 0:
            self.error_passing_asks -= 1
            return {"id": params["id"], "records": "held", "state": "awaiting_reply"}
        result: dict[str, Any] = {
            "id": params["id"],
            "records": "held",
            "state": paused.state,
        }
        if paused.state == "decided":
            result["judgment"] = paused.judgment
        elif paused.reason is not None:
            result["reason"] = paused.reason
            if paused.failure is not None:
                result["failure"] = paused.failure
        if paused.reviews:
            result["reviews"] = paused.reviews
        return result

    def _pending_questions(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "questions": [
                {
                    "id": f"question_{irid}",
                    "sample_uuid": params.get("sample_uuid"),
                    "request_id": irid,
                    "stage": paused.stage,
                    "call": {
                        "id": "call_1",
                        "function": "weather",
                        "arguments": {"city": "Oslo"},
                        "type": "function",
                    },
                    "message": "Checking.",
                    "view": {},
                    "escalations": [
                        {"name": "risk_monitor", "explanation": "A new city."}
                    ],
                    "choices": ["approve", "reject", "terminate"],
                    "asked": 0.0,
                }
                for irid, paused in self.paused.items()
                if paused.state == "awaiting_review"
            ]
        }

    def _answer_question(self, params: dict[str, Any]) -> dict[str, Any]:
        paused = self.paused[params["id"].removeprefix("question_")]
        now = time.time()
        paused.reviews.append(
            {
                "id": params["id"],
                "try_number": 1,
                "stage": paused.stage,
                "call": "call_1",
                "asked": now,
                "decision": params["decision"],
                "answered": now,
                "resolution": "answered",
                "resolved": now,
            }
        )
        if params["decision"] != "approve":
            self._rejected(paused, params.get("reason") or "Rejected.")
        elif paused.stage == "tool_call":
            paused.state = "decided"
            step = {
                "stage": "tool_call",
                "call": "call_1",
                "decision": {"action": "proceed"},
                "reviews": [params["id"]],
            }
            paused.judgment = {
                "outcome": "proceed",
                "steps": [step] if self.judged_step else [],
            }
        else:
            paused.state = "awaiting_request"
        return {"id": params["id"], "decision": params["decision"]}

    def _cancel_request(self, params: dict[str, Any]) -> dict[str, Any]:
        self.cancelled.append(params["id"])
        paused = self.paused.get(params["id"])
        if paused is not None:
            if paused.state == "awaiting_review":
                now = time.time()
                paused.reviews.append(
                    {
                        "id": f"question_{params['id']}",
                        "try_number": 1,
                        "stage": paused.stage,
                        "call": "call_1",
                        "asked": now,
                        "resolution": "cancelled",
                        "cause": "cancelled",
                        "resolved": now,
                    }
                )
            paused.state, paused.reason = "not_judged", "cancelled"
        return {"id": params["id"], "cancelled": paused is not None}


class _CutOff(httpx2.AsyncByteStream):
    # a body whose connection fails part way
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"type": "err'
        raise httpx2.ReadError("The connection was lost.")


def _refusal(message: str) -> httpx2.Response:
    return httpx2.Response(400, json={"error": {"type": "error", "message": message}})


class Person:
    """A person at Inspect's approval panel, who picks the same choice each time they are asked."""

    def __init__(
        self, decision: ApprovalDecision, explanation: str | None = None
    ) -> None:
        self.decision = decision
        self.explanation = explanation
        self.asked: list[tuple[str, ToolCall, ToolCallView, list[str]]] = []
        self.shown: list[list[ChatMessage]] = []
        """The conversation the panel was given with each question."""

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def acp(**kwargs: object) -> Approval | None:
            return None

        async def panel(
            message: str,
            call: ToolCall,
            view: ToolCallView,
            history: object,
            choices: list[str],
        ) -> Approval:
            self.asked.append((message, call, view, choices))
            self.shown.append(cast("list[ChatMessage]", history))
            return Approval(decision=self.decision, explanation=self.explanation)

        monkeypatch.setattr(acp_module, "request_human_approval_via_acp", acp)
        monkeypatch.setattr(approver_module, "panel_approval", panel)


def _model(stand_in: StandInSidecar, provider: str = "anthropic") -> Model:
    name = {
        "anthropic": "anthropic/claude-haiku-4-5",
        "openai-api": "openai-api/together/meta-llama-3",
    }[provider]
    return get_model(
        name,
        base_url="http://proxy.test"
        if provider == "anthropic"
        else "http://proxy.test/v1",
        api_key="test-key",
        memoize=False,
        http_client=stand_in.http_client(),
    )


def _run(
    stand_in: StandInSidecar,
    provider: str = "anthropic",
    solver: Solver | list[Solver] | None = None,
    **kwargs: Any,
) -> EvalLog:
    _LOOKED_UP.clear()
    task = Task(
        dataset=[Sample(input="What's the weather?")],
        solver=solver or [use_tools(weather()), generate()],
    )
    kwargs.setdefault("sentinel_proxy", "auto")
    [log] = inspect_eval(
        task, model=_model(stand_in, provider), display="none", **kwargs
    )
    return log


def _sample(log: EvalLog) -> EvalSample:
    assert log.status == "success", log.error
    assert log.samples is not None
    return log.samples[0]


def _model_events(sample: EvalSample) -> list[ModelEvent]:
    return [e for e in sample.events if isinstance(e, ModelEvent)]


def _called(stand_in: StandInSidecar, method: str) -> list[dict[str, Any]]:
    return [c["params"] for c in stand_in.calls if c["method"] == method]


_OSLO = Turn(text="Checking.", calls=[("call_1", "weather", {"city": "Oslo"})])


# --- a call with no sidecar ---------------------------------------------------


def test_with_no_sidecar_no_request_id_is_reused() -> None:
    # outside any agent call through a sidecar, every request gets a new id
    assert request_id_to_reuse() is None
    hooks = HttpxHooks(httpx2.AsyncClient())
    with hooks.request() as first, hooks.request() as second:
        assert first != second


async def test_with_no_sidecar_a_requests_path_is_untouched() -> None:
    sent: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json={})

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(answer))
    hooks = HttpxHooks(client)
    with hooks.request() as request_id:
        await client.post(
            "http://provider.test/v1/messages?beta=true",
            headers={HttpxHooks.REQUEST_ID_HEADER: request_id},
            json={},
        )
        # a request that names a sample, of a call no person was asked about
        with receiving_call():
            await client.post(
                "http://provider.test/v1/messages",
                headers={
                    HttpxHooks.REQUEST_ID_HEADER: request_id,
                    "x-inspect-context": "{}",
                },
                json={},
            )

    assert [str(r.url) for r in sent] == [
        "http://provider.test/v1/messages?beta=true",
        "http://provider.test/v1/messages",
    ]


async def test_with_no_sidecar_refused_output_returns_at_once() -> None:
    asked: list[str] = []

    def retryable() -> bool:
        asked.append("retryable")
        return False

    async def send_again() -> ModelOutput:
        asked.append("send_again")
        return ModelOutput.from_content("model", "sent again")

    assert _received.get() is None
    assert await refused_output("model", retryable, lambda: False, send_again) is None
    # nothing was asked of the provider, and nothing was sent
    assert asked == []


@pytest.mark.parametrize("sentinel_proxy", [None, "off"], ids=["not set", "off"])
def test_with_no_sidecar_a_provider_error_is_handled_as_before(
    sentinel_proxy: Any,
) -> None:
    stand_in = StandInSidecar(turns=[Turn(status=400)])

    log = _run(stand_in, solver=generate(), sentinel_proxy=sentinel_proxy)

    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None and "Refused." in sample.error.message
    # one request, to the model, and none to a sidecar
    assert [r.url.path for r in stand_in.requests] == ["/v1/messages"]
    [event] = _model_events(sample)
    assert event.error is not None and event.pending is None


# --- a call paused at its reply -----------------------------------------------


def test_a_person_is_shown_the_conversation_as_inspect_holds_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person = Person("approve")
    person.install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["tool_call"], turns=[_OSLO, Turn()])

    _run(stand_in)

    # the messages the call was sent with, from the eval's own process: the
    # sidecar's question holds no conversation
    [history] = person.shown
    assert [(m.role, m.text) for m in history] == [("user", "What's the weather?")]


@pytest.mark.parametrize("provider", ["anthropic", "openai-api"])
def test_an_approved_call_gets_the_held_reply_on_the_same_model_event(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    person = Person("approve")
    person.install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["tool_call"], turns=[_OSLO, Turn()])

    sample = _sample(_run(stand_in, provider))

    # the person saw the call, with who escalated it
    [(message, call, view, choices)] = person.asked
    assert (message, call.function, call.arguments) == (
        "Checking.",
        "weather",
        {"city": "Oslo"},
    )
    assert view.call is not None and "risk_monitor: A new city." in view.call.content
    assert choices == ["approve", "reject", "terminate"]

    # the same request went twice under one id: to the model, then to the
    # sidecar's held-reply path, and the provider was called once for it
    route = "/v1/messages" if provider == "anthropic" else "/v1/chat/completions"
    first, second, third = [
        r for r in stand_in.requests if r.url.path in (route, HELD_REPLY_PATH)
    ]
    assert (first.url.path, second.url.path) == (route, HELD_REPLY_PATH)
    assert first.headers["x-irid"] == second.headers["x-irid"]
    assert first.content == second.content
    # the next call is another model call, with an id of its own
    assert third.url.path == route
    assert third.headers["x-irid"] != first.headers["x-irid"]
    assert stand_in.refused == []

    # one model event for the call, with the reply, the record of the request
    # that brought it, and the usage counted once
    turn_event, last_event = _model_events(sample)
    assert turn_event.error is None and turn_event.pending is None
    assert [c.function for c in turn_event.output.message.tool_calls or []] == [
        "weather"
    ]
    assert turn_event.call is not None
    assert turn_event.call.response is not None
    assert "error" not in turn_event.call.response
    assert turn_event.output.usage is not None
    assert sample.model_usage[str(_model(stand_in, provider))].input_tokens == (
        turn_event.output.usage.input_tokens
        + (last_event.output.usage.input_tokens if last_event.output.usage else 0)
    )
    # the call ran once it was approved
    assert _LOOKED_UP == ["Oslo"]
    assert stand_in.cancelled == []


def test_a_held_reply_keeps_its_response_ids_and_its_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)

    def with_request_id(request: httpx2.Request) -> httpx2.Response:
        response = stand_in._handle(request)
        if request.url.path == HELD_REPLY_PATH:
            response.headers["request-id"] = "req_held"
        return response

    stand_in = ReviewingSidecar(pauses=["tool_call"], turns=[_OSLO])
    streamed: list[Any] = []

    @solver
    def streams() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            async def on_stream(event: Any) -> None:
                streamed.append(event)

            state.output = await get_model().generate(
                state.messages, on_stream=on_stream
            )
            return state

        return solve

    task = Task(dataset=[Sample(input="What's the weather?")], solver=streams())
    model = get_model(
        "anthropic/claude-haiku-4-5",
        base_url="http://proxy.test",
        api_key="test-key",
        memoize=False,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(with_request_id)),
    )
    [log] = inspect_eval(task, model=model, display="none", sentinel_proxy="auto")

    sample = _sample(log)
    [event] = _model_events(sample)
    # the held reply was asked for as a stream, and read as one
    [held] = stand_in.held_reply_requests
    assert json.loads(held.content)["stream"] is True
    assert streamed, "the held reply's deltas reached the stream handler"
    assert event.output.message.text == "Checking."
    assert event.request_ids is not None
    assert "req_held" in [request.id for request in event.request_ids]


def test_a_rejected_call_goes_on_as_the_models_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("reject", "Not Oslo.").install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn(text="I can't look that up.")]
    )

    sample = _sample(_run(stand_in))

    [answer] = _called(stand_in, "answer_question")
    assert (answer["decision"], answer["reason"]) == ("reject", "Not Oslo.")
    # no held reply is asked for, and the call is answered with the rejection
    assert stand_in.held_reply_requests == []
    [tool_message] = [m for m in sample.messages if isinstance(m, ChatMessageTool)]
    assert tool_message.error is not None
    assert (tool_message.error.type, tool_message.error.message) == (
        "approval",
        "Not Oslo.",
    )
    assert _LOOKED_UP == []


def test_an_sdk_retry_of_the_held_reply_request_keeps_the_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn()], held_reply_statuses=[503]
    )

    sample = _sample(_run(stand_in))

    # the SDK sent the request again itself, to the same path, under the same id
    first, second = stand_in.held_reply_requests
    assert first.headers["x-irid"] == second.headers["x-irid"]
    assert first.content == second.content
    assert _LOOKED_UP == ["Oslo"]
    assert _model_events(sample)[0].error is None


def test_a_continuation_after_the_held_reply_goes_to_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # the held reply pauses its turn, so the provider continues it with a
    # request that has another body
    stand_in = ReviewingSidecar(
        pauses=["tool_call"],
        turns=[Turn(text="Searching.", stop_reason="pause_turn"), Turn()],
    )

    _run(stand_in, solver=generate())

    [held] = stand_in.held_reply_requests
    continuation = stand_in.requests[stand_in.requests.index(held) + 1]
    assert continuation.url.path == "/v1/messages"
    assert continuation.headers["x-irid"] == held.headers["x-irid"]
    assert continuation.content != held.content


# --- a call paused at its request ---------------------------------------------


def test_a_call_paused_at_its_request_is_sent_again_on_the_model_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["tool_result"], turns=[Turn(text="Sunny.")])

    sample = _sample(_run(stand_in, solver=generate()))

    # the request went twice to the model's path under one id, and the
    # sidecar sent the second on to the provider
    first, second = stand_in.model_calls
    assert first.headers["x-irid"] == second.headers["x-irid"]
    assert first.content == second.content
    assert stand_in.held_reply_requests == []
    [event] = _model_events(sample)
    assert event.error is None
    assert event.output.message.text == "Sunny."
    assert sample.output.completion == "Sunny."


def test_a_provider_error_after_a_review_is_inspects_to_retry_under_the_same_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # the provider fails the request the sidecar sent on, then answers
    stand_in = ReviewingSidecar(
        pauses=["tool_result"], turns=[Turn(status=529), Turn(text="Sunny.")]
    )

    sample = _sample(_run(stand_in, solver=generate()))

    assert sample.output.completion == "Sunny."
    ids = {r.headers["x-irid"] for r in stand_in.model_calls}
    assert len(ids) == 1
    # the person was asked once, whatever was sent since
    assert len(_called(stand_in, "answer_question")) == 1


def test_a_provider_error_after_a_review_is_the_error_the_model_event_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # the provider refuses the request the sidecar sent on, with an error
    # Inspect doesn't retry, and which the provider's client raises
    stand_in = ReviewingSidecar(pauses=["tool_result"], turns=[Turn(status=403)])

    log = _run(stand_in, solver=generate(), fail_on_error=False)

    sample = _sample(log)
    assert sample.error is not None
    # the call's one event holds the provider's error, which is the error the
    # sample failed with, and not the sidecar's word that the call waited
    [event] = _model_events(sample)
    assert event.pending is None
    assert event.error is not None
    assert "403" in event.error
    assert "403" in sample.error.message
    assert len(stand_in.model_calls) == 2


def test_the_providers_error_is_got_from_the_sidecar_when_inspect_holds_the_sidecars_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # The provider refuses the request the sidecar sent on, with an error
    # Inspect doesn't retry. The try Inspect holds was answered "pending
    # review", as one is that comes while another is with the provider.
    stand_in = ReviewingSidecar(
        pauses=["tool_result"], turns=[Turn(status=403)], error_lost=True
    )

    sample = _sample(_run(stand_in, solver=generate(), fail_on_error=False))

    # the call fails with the provider's error, on the sample and on the
    # call's one event, and not with the sidecar's word that the call waited
    assert sample.error is not None and "403" in sample.error.message
    [event] = _model_events(sample)
    assert event.pending is None
    assert event.error is not None and "403" in event.error
    assert "pending review" not in event.error
    # it was got once from the held-reply path, under the call's id, and the
    # provider wasn't called again for an error Inspect doesn't retry
    [got] = stand_in.held_reply_requests
    first, sent_on = stand_in.model_calls
    assert got.headers["x-irid"] == first.headers["x-irid"] == sent_on.headers["x-irid"]


def test_a_providers_error_got_from_the_sidecar_is_retried_by_inspects_own_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # the provider is overloaded, then answers; Inspect holds "pending review"
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=529), Turn(text="Sunny.")],
        error_lost=True,
    )

    sample = _sample(_run(stand_in, solver=generate()))

    # Inspect retries an overloaded provider, and the retry is sent on under
    # the call's id, with the person asked once
    assert sample.output.completion == "Sunny."
    assert len({r.headers["x-irid"] for r in stand_in.model_calls}) == 1
    assert len(stand_in.held_reply_requests) == 1
    assert len(_called(stand_in, "answer_question")) == 1


def test_inspect_asks_again_while_a_providers_error_is_still_passing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # the sidecar says the provider failed only once the error's body has all
    # passed, and is asked twice before then
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=403)],
        error_lost=True,
        error_passing_asks=2,
    )

    sample = _sample(
        _run(
            stand_in, solver=generate(), fail_on_error=False, sentinel_proxy="required"
        )
    )

    # the call fails with the provider's error, and not as a call whose
    # reply the sidecar never saw
    assert sample.error is not None and "403" in sample.error.message
    assert "never saw a reply" not in sample.error.message
    assert len(stand_in.held_reply_requests) == 1


def test_a_providers_error_that_its_own_code_reads_as_a_reply_is_the_calls_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # Anthropic's code reads a prompt that is too long as a reply that
    # stopped for the model's length, and not as an error
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=400)],
        error_lost=True,
        failure_message="prompt is too long: 250000 tokens > 200000 maximum",
    )

    log = _run(stand_in, solver=generate(), sentinel_proxy="required")

    # as with no review: the sample goes on with the provider's answer
    sample = _sample(log)
    assert sample.error is None
    assert sample.output.stop_reason == "model_length"
    # Inspect sends nothing more, so the call is closed at the sidecar, which
    # waited for its request
    first = stand_in.model_calls[0]
    assert stand_in.cancelled == [first.headers["x-irid"]]
    assert len(stand_in.model_calls) == 2
    assert len(stand_in.held_reply_requests) == 1


def test_a_refusal_of_the_sidecars_own_that_the_providers_code_reads_as_a_reply_is_not_taken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # The provider refused the request the sidecar sent on. The held-reply
    # path first answers with a 413 of its own, unmarked, which Anthropic's
    # code reads as a reply that stopped for the model's length.
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=403)],
        error_lost=True,
        held_reply_statuses=[413],
    )

    sample = _sample(
        _run(
            stand_in, solver=generate(), fail_on_error=False, sentinel_proxy="required"
        )
    )

    # nothing is taken from the sidecar's own refusal: the error is asked for
    # again, and the call fails with the provider's
    assert sample.error is not None and "403" in sample.error.message
    assert len(stand_in.held_reply_requests) == 2
    # and the refusal was never the call's result
    [event] = _model_events(sample)
    assert event.error is not None and "403" in event.error
    assert event.output.stop_reason != "model_length"


def test_a_providers_error_whose_connection_failed_part_way_is_asked_for_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # The provider refused the request the sidecar sent on. The first answer
    # with its error loses its connection after the headers, the sidecar's
    # marker among them, and before the body has all come.
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=403)],
        error_lost=True,
        error_cut_off=1,
    )

    sample = _sample(
        _run(
            stand_in, solver=generate(), fail_on_error=False, sentinel_proxy="required"
        )
    )

    # the failure isn't taken as handled until the error has come whole: it
    # is asked for again, and the call fails with the provider's error,
    # without the provider being called again
    assert sample.error is not None and "403" in sample.error.message
    assert len(stand_in.held_reply_requests) >= 2
    assert len(stand_in.model_calls) == 2


def test_a_refusal_of_the_sidecars_own_is_never_taken_for_the_providers_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # the held-reply path refuses with the status the provider's error has,
    # and without the header that marks a provider's error
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=403)],
        error_lost=True,
        held_reply_statuses=[403, 403],
    )

    sample = _sample(_run(stand_in, solver=generate(), fail_on_error=False))

    # asked for a bounded number of times, and the failed try is never taken
    # to have been acted on
    assert len(stand_in.held_reply_requests) == FAILURE_FETCHES
    assert sample.error is not None
    assert len(stand_in.model_calls) == 2


# --- what became of each question, in the log and for the person ---------------


def _reviews_logged(sample: EvalSample) -> list[dict[str, Any]]:
    return [
        event.data
        for event in sample.events
        if isinstance(event, InfoEvent)
        and event.source == "sentinel sidecar"
        and isinstance(event.data, dict)
        and "review" in event.data
    ]


def _warned(sample: EvalSample) -> list[str]:
    return [
        event.message.message
        for event in sample.events
        if isinstance(event, LoggerEvent) and event.message.level == "warning"
    ]


def test_a_persons_review_is_kept_in_the_evals_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn()], judged_step=True
    )

    sample = _sample(_run(stand_in))

    # the question's record, once, with the call's id and the try it was
    # asked at
    [logged] = _reviews_logged(sample)
    first = stand_in.model_calls[0]
    assert logged["request"] == first.headers["x-irid"]
    review = logged["review"]
    assert (review["try_number"], review["stage"], review["call"]) == (
        1,
        "tool_call",
        "call_1",
    )
    assert (review["decision"], review["resolution"]) == ("approve", "answered")
    # and the step that asked names the question, so the two are found together
    [step] = [e for e in sample.events if isinstance(e, SentinelEvent)]
    assert step.metadata is not None
    assert step.metadata["sentinel_sidecar"]["reviews"] == [review["id"]]
    # an answer that was used is nothing to tell the person of
    assert not [w for w in _warned(sample) if "wasn't used" in w]


def test_a_person_whose_answer_came_too_late_is_told_it_wasnt_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn()], expires=True
    )

    sample = _sample(_run(stand_in))

    # the person is told, plainly, with why, how long before, and what the
    # call came to
    [told] = [w for w in _warned(sample) if "wasn't used" in w]
    assert "A person's answer (approve)" in told and "the call to weather" in told
    assert "the question had timed out" in told
    assert "about 12 minutes before the answer" in told
    assert "The call was rejected." in told
    # the record of a question nobody answered in time is in the log too,
    # though no step was judged with it
    [logged] = _reviews_logged(sample)
    assert logged["review"]["resolution"] == "timed_out"
    assert "decision" not in logged["review"]
    # and the call went as the sidecar decided, not as the person chose
    assert _LOOKED_UP == []
    assert stand_in.held_reply_requests == []


def test_a_person_is_told_when_the_sidecar_cant_say_what_became_of_their_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn()], records_dropped=True
    )

    sample = _sample(_run(stand_in, fail_on_error=False))

    # neither that the answer was used nor that it wasn't
    [told] = [w for w in _warned(sample) if "couldn't learn whether" in w]
    assert "a person's answer (approve)" in told and "dropped" in told
    assert not [w for w in _warned(sample) if "wasn't used" in w]
    assert _reviews_logged(sample) == []


# --- a call Inspect gives up on -----------------------------------------------


def test_a_sample_that_times_out_while_a_person_decides_cancels_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def never(*args: object, **kwargs: object) -> Approval:
        await anyio.sleep_forever()
        raise AssertionError

    async def acp(**kwargs: object) -> Approval | None:
        return None

    monkeypatch.setattr(acp_module, "request_human_approval_via_acp", acp)
    monkeypatch.setattr(approver_module, "panel_approval", never)
    stand_in = ReviewingSidecar(pauses=["tool_call"], turns=[_OSLO])

    log = _run(stand_in, solver=generate(), time_limit=1)

    assert log.samples is not None
    [sample] = log.samples
    assert sample.limit is not None and sample.limit.type == "time"
    [first] = stand_in.model_calls
    assert stand_in.cancelled == [first.headers["x-irid"]]
    # the call's event didn't stay pending
    [event] = _model_events(sample)
    assert event.pending is None
    assert review_module._open_calls == {}
    # the record of the question the cancellation closed is in the log
    [logged] = _reviews_logged(sample)
    assert logged["request"] == first.headers["x-irid"]
    assert (logged["review"]["resolution"], logged["review"]["cause"]) == (
        "cancelled",
        "cancelled",
    )


async def test_a_call_cancelled_while_a_person_decides_is_cancelled_at_the_sidecar() -> (
    None
):
    cancelled: list[str] = []
    waiting = anyio.Event()

    class Sidecar:
        origin = "http://proxy.test"
        review = True

        async def eval_call(self, method: str, params: dict[str, Any]) -> Any:
            if method == "request_result":
                return {"id": params["id"], "records": "held", "state": "judging"}
            assert method == "cancel_request"
            cancelled.append(params["id"])
            return {"id": params["id"], "cancelled": True}

    async def send_again() -> ModelOutput:
        raise AssertionError("nothing is sent for a call still being judged")

    async def call(received: ReceivedCall) -> None:
        # a call a person was asked about, whose answer the sidecar is judging
        received.request_id = received.reviewed_id = "request_1"
        received.sent = received.open = True
        waiting.set()
        await refused_output("model", lambda: False, lambda: False, send_again)

    with receiving_call(Sidecar()) as received:
        async with anyio.create_task_group() as tg:
            tg.start_soon(call, received)
            await waiting.wait()
            await anyio.sleep(0.05)
            tg.cancel_scope.cancel()

    assert cancelled == ["request_1"]
    assert received.open is False


def test_a_request_is_sent_to_the_held_reply_path_only_for_its_own_call() -> None:
    def request(irid: str, body: bytes = b"{}") -> httpx2.Request:
        return httpx2.Request(
            "POST",
            "http://proxy.test/v1/messages?beta=true",
            headers={"x-irid": irid},
            content=body,
        )

    with receiving_call() as received:
        received.reviewed_id = "request_1"
        # not while no held reply is being got
        sent = request("request_1")
        use_held_reply_path(sent)
        assert sent.url.path == "/v1/messages"

        received.getting_held_reply = True
        other = request("request_2")
        use_held_reply_path(other)
        assert other.url.path == "/v1/messages"

        # the path is replaced, and the origin and the query are kept
        first = request("request_1")
        use_held_reply_path(first)
        assert str(first.url) == f"http://proxy.test{HELD_REPLY_PATH}?beta=true"
        # the SDK's retry has the same body; a continuation has another
        retry, continuation = request("request_1"), request("request_1", b'{"m":1}')
        use_held_reply_path(retry)
        use_held_reply_path(continuation)
        assert retry.url.path == HELD_REPLY_PATH
        assert continuation.url.path == "/v1/messages"
