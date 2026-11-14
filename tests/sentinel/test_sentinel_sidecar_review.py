"""A person's review of a call that a sentinel in a sidecar asks for, and what a call with no sidecar is spared of it.

The stand-in here keeps a call a person is asked about as one model call under its `x-irid`, as the sidecar does: it answers the call's request with an error while the question is open, and afterwards answers the same request, sent to its held-reply path, with the provider's reply it held.
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

import anyio
import httpx2
import pytest
from tenacity import wait_none
from test_helpers.stand_in_sidecar import (
    _MODEL_ROUTES,
    ENDPOINT,
    UNAUTHORIZED,
    StandInSidecar,
    Turn,
)

from inspect_ai import Task
from inspect_ai import eval as inspect_eval
from inspect_ai._control.pause import pause_process, process_paused, resume_process
from inspect_ai._sentinel._sidecar import _lookup as lookup_module
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
from inspect_ai._sentinel._sidecar._review import (
    FAILED_TRY,
    FAILURE_FETCHES,
    MODEL_SENDS,
)
from inspect_ai._util.working import sample_wait
from inspect_ai.approval import Approval
from inspect_ai.approval._approval import ApprovalDecision
from inspect_ai.approval._human import acp as acp_module
from inspect_ai.approval._human import approver as approver_module
from inspect_ai.dataset import Sample
from inspect_ai.event import InfoEvent, LoggerEvent, ModelEvent, SentinelEvent
from inspect_ai.log import EvalLog, EvalSample
from inspect_ai.log._samples import sample_active
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.model._providers.anthropic import AnthropicAPI
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
    judging_time: float = 0.0
    """How long the sentinel judged the call while the proxy held its sends, added up over them."""


@dataclass
class _HeldRequest:
    """A request the stand-in held before answering, as a proxy holds a call, with when the hold began and ended on the monotonic clock."""

    path: str
    began: float
    ended: float = 0.0
    finished: bool = False
    """Whether the hold ran its whole time. A hold whose client went away, as when the call was cancelled or timed out, ended before that."""


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
    """The message of the provider's error, in Anthropic's format, in place of the stand-in's own: as the held-reply path serves it, and as the try that is sent on is answered with it."""
    lookups_lost: int = 0
    """How many `request_result` calls about a paused call, once a person has answered, the proxy answers with a 502, so that they never reach the sidecar."""
    lookups_refused: int = 0
    """How many such calls the sidecar itself answers with an error."""
    questions_lost: int = 0
    """How many `pending_questions` calls the proxy answers with a 502, so that they never reach the sidecar."""
    answers_lost: int = 0
    """How many `answer_question` calls the proxy answers with a 502, so that they never reach the sidecar."""
    error_cut_off: int = 0
    """How many times the held-reply path's answer with the provider's error has its connection fail part way through the body, after its headers, the sidecar's marker among them, have come."""
    pending_lost: int = 0
    """How many of the paused call's requests, from the first, lose their connection before the sidecar's "pending review" comes back: every try the provider's SDK makes by itself, for a large enough number."""
    cut_off: bool = False
    """Whether every try that is sent on is cut off at the provider, with Inspect's own try answered with an error that has a status."""
    judge_usage: dict[str, Any] | None = None
    """The judge model's usage, added up over the call, that every `request_result` about a paused call gives, as the sidecar does."""
    error_lost: bool = False
    """Whether the try that is sent on is answered with the sidecar's own "pending review" when the provider fails it, and not with the provider's error: what Inspect holds when a try of its was answered while another was with the provider."""
    provider_takes_asks: int = 0
    """How many times `request_result` still says the sidecar awaits the reply of the try it sent on to the provider, before the reply has come and been judged. That try's own connection is held far longer, so Inspect's attempt at it times out first."""
    lookups_take: list[float] = field(default_factory=list)
    """How long the sidecar takes to answer each `request_result` that finds the call awaiting the provider's reply, in order, in seconds. Those past the list's end are answered at once."""
    awaited_lookups: int = 0
    """How many `request_result` calls found the call awaiting the provider's reply."""
    reply_judged_asks: int = 0
    """How many times, once the provider's reply has come, `request_result` says the sidecar is judging it, before it is decided."""
    closed_before_asked: bool = False
    """Whether the question about a call paused at its reply times out before Inspect first asks about the call, and the sentinel's cautious answer still lets the turn go on."""
    sdk_retries: bool = True
    """Whether the provider's SDK may retry a provider's error on a try that is sent on. Without, the error comes back to Inspect, as `x-should-retry: false` makes it."""
    holds: list[tuple[float, float]] = field(default_factory=list)
    held_at: list[float] = field(default_factory=list)
    """When each request given a hold came, on the monotonic clock."""
    """For each request of a paused call, in order: how long the proxy holds it before answering, and how much of that the sentinel spent judging it, in seconds."""

    when_held: Callable[[], None] | None = None
    """Called as the stand-in begins to hold a request, in the task of the call that sent it, so that a test can time something from the hold's start."""
    held_requests: list[_HeldRequest] = field(default_factory=list)
    """Each request the stand-in held, in the order they came, with how long it was really held: a busy machine holds one longer than it was told to."""

    def __post_init__(self) -> None:
        assert self.info is not None
        self.info["review"] = True
        self.methods.setdefault("pending_questions", self._pending_questions)
        self.methods.setdefault("answer_question", self._answer_question)
        self.methods.setdefault("cancel_request", self._cancel_request)

    @property
    def held_reply_requests(self) -> list[httpx2.Request]:
        return [r for r in self.requests if r.url.path == HELD_REPLY_PATH]

    async def _handle_async(self, request: httpx2.Request) -> httpx2.Response:
        response = self._handle(request)
        hold = self._holds.pop(id(request), 0.0)
        if hold:
            # timed here, where the request is held, so that a test can
            # compare what Inspect counted with what really happened
            held = _HeldRequest(request.url.path, time.monotonic())
            self.held_requests.append(held)
            if self.when_held is not None:
                self.when_held()
            try:
                await anyio.sleep(hold)
                held.finished = True
            finally:
                held.ended = time.monotonic()
        return response

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        context = request.headers.get("x-inspect-context")
        if path == HELD_REPLY_PATH:
            self.requests.append(request)
            return self._held(request, self._held_reply(request))
        if path in _MODEL_ROUTES and context is not None:
            irid = request.headers.get("x-irid")
            if irid in self.paused or self.pauses:
                self.requests.append(request)
                unread = self._unread(context, irid)
                if unread is not None:
                    self.refused.append(unread)
                    return _refusal(unread)
                assert irid is not None
                return self._held(request, self._paused_call(request, irid))
        if path == ENDPOINT:
            call = json.loads(request.content)
            if call["method"] == "pending_questions" and self.questions_lost > 0:
                self.questions_lost -= 1
                return httpx2.Response(502, text="Bad Gateway")
            if call["method"] == "answer_question" and self.answers_lost > 0:
                self.answers_lost -= 1
                return httpx2.Response(502, text="Bad Gateway")
            if (
                call["method"] == "request_result"
                and call["params"].get("id") in self.paused
            ):
                self.methods["request_result"] = self._request_result
                if self.paused[call["params"]["id"]].state != "awaiting_review":
                    if self.lookups_lost > 0:
                        self.lookups_lost -= 1
                        return httpx2.Response(502, text="Bad Gateway")
                    if self.lookups_refused > 0:
                        self.lookups_refused -= 1
                        self.methods["request_result"] = lambda params: self._refuse(
                            -32000, "The sidecar can't answer."
                        )
                if self.paused[call["params"]["id"]].state == "awaiting_reply":
                    self.awaited_lookups += 1
                    if self.lookups_take:
                        self._holds[id(request)] = self.lookups_take.pop(0)
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
                if self.closed_before_asked:
                    now = time.time()
                    paused.reviews.append(
                        {
                            "id": f"question_{irid}",
                            "try_number": 1,
                            "stage": "tool_call",
                            "call": "call_1",
                            "asked": now,
                            "resolution": "timed_out",
                            "resolved": now,
                        }
                    )
                    paused.state = "decided"
                    paused.judgment = {"outcome": "proceed", "steps": []}
            return self._pending(request)
        paused.tries += 1
        if paused.state != "awaiting_request":
            # no other try is sent on, and a call that has ended is read
            # with `request_result`
            return self._pending(request)
        if self.cut_off:
            paused.reason = "cut_off"
            paused.failure = {"try_number": paused.tries}
            return _refusal("The connection to the provider was lost.")
        turn = self.turns.pop(0) if self.turns else Turn()
        if turn.status != 200:
            paused.reason = "provider_error"
            paused.failure = {
                "try_number": paused.tries,
                "reply": {"status": turn.status, "headers": {}, "body": ""},
            }
            if self.error_lost:
                return _refusal("pending review")
        elif self.provider_takes_asks > 0:
            # with the provider, whose reply the sidecar will hold
            paused.turn = turn
            paused.state = "awaiting_reply"
            self._holds[id(request)] = 60.0
        else:
            paused.turn = turn
            paused.state = "decided"
            paused.judgment = {"outcome": "proceed", "steps": []}
        replied = _MODEL_ROUTES[paused.route](turn, bool(asked.get("stream")), asked)
        if turn.status != 200 and self.failure_message is not None:
            replied = self._failed(turn.status, self.failure_message)
        if turn.status != 200 and not self.sdk_retries:
            replied.headers["x-should-retry"] = "false"
        return replied

    def _failed(self, status: int, message: str) -> httpx2.Response:
        # a provider's error with a message of its own, in Anthropic's format
        return httpx2.Response(
            status,
            json={
                "type": "error",
                "error": {"type": "invalid_request_error", "message": message},
            },
        )

    def _held(
        self, request: httpx2.Request, response: httpx2.Response
    ) -> httpx2.Response:
        # held by the proxy, part of the time while the sentinel judged it
        if self.holds:
            hold, judging = self.holds.pop(0)
            self._holds[id(request)] = hold
            self.paused[request.headers["x-irid"]].judging_time += judging
            self.held_at.append(time.monotonic())
        return response

    def _pending(self, request: httpx2.Request) -> httpx2.Response:
        # the sidecar's "pending review", unless the connection is lost first
        if self.pending_lost > 0:
            self.pending_lost -= 1
            raise httpx2.ConnectError("The connection was lost.", request=request)
        return _refusal("pending review")

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
                failed = self._failed(
                    paused.failure["reply"]["status"], self.failure_message
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
        if paused.state == "judging" and paused.turn is not None:
            self.reply_judged_asks -= 1
            if self.reply_judged_asks <= 0:
                paused.state = "decided"
                paused.judgment = {"outcome": "proceed", "steps": []}
        if paused.state == "awaiting_reply":
            self.provider_takes_asks -= 1
            if self.provider_takes_asks <= 0 and self.reply_judged_asks > 0:
                # the provider's reply has come, and is being judged
                paused.state = "judging"
            elif self.provider_takes_asks <= 0:
                # the provider's reply has come, and was judged
                paused.state = "decided"
                paused.judgment = {"outcome": "proceed", "steps": []}
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
        if paused.judging_time:
            result["judging_time"] = paused.judging_time
        if self.judge_usage is not None:
            result["judging_usage"] = [
                {"role": "monitor", "model": "mockllm/judge", "usage": self.judge_usage}
            ]
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
        self,
        decision: ApprovalDecision,
        explanation: str | None = None,
        takes: float = 0.0,
        meanwhile: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.decision = decision
        self.explanation = explanation
        self.takes = takes
        """How long they take to answer, in seconds."""
        self.meanwhile = meanwhile
        """What happens while they decide, before their answer is given."""
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
            await anyio.sleep(self.takes)
            if self.meanwhile is not None:
                await self.meanwhile()
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


_SDK_RETRY_WAITS = 0.375 + 0.75
"""The least Anthropic's SDK waits, in seconds, before its second and third tries of a request whose connection failed: half a second and then a second, each shortened by up to a quarter."""


def _event_waiting(event: ModelEvent) -> float:
    # How much of a model event, from its start to its end, was not the
    # model's work, in seconds. A slow machine adds to the event's whole time
    # and to its working time alike, so this holds what was counted as
    # waiting however slow the machine.
    assert event.completed is not None and event.working_time is not None
    return (event.completed - event.timestamp).total_seconds() - event.working_time


def _sample_waiting(sample: EvalSample) -> float:
    # the same for a sample: its whole time less its working time
    assert sample.total_time is not None and sample.working_time is not None
    return sample.total_time - sample.working_time


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


def test_a_question_that_cant_be_shown_tells_nothing_of_what_it_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person = Person("approve")
    person.install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn(text="I can't look that up.")]
    )
    listed = stand_in._pending_questions
    secret = "sk-not-to-be-told"

    def unreadable(params: dict[str, Any]) -> dict[str, Any]:
        # a question whose call Inspect can't read: its arguments are a list,
        # and hold a secret
        questions = listed(params)
        for question in questions["questions"]:
            question["call"]["arguments"] = ["--api-key", secret]
        return questions

    stand_in.methods["pending_questions"] = unreadable

    sample = _sample(_run(stand_in))

    # the question fails closed, and no person is asked
    assert person.asked == []
    [answer] = _called(stand_in, "answer_question")
    assert answer["decision"] == "reject"
    # The reason sent with the answer is what the model is told. It names the
    # error's type, and has nothing of its text, which holds the arguments.
    assert "ValidationError" in answer["reason"]
    assert secret not in answer["reason"]
    # the warning in the eval's log likewise
    [warned] = [w for w in _warned(sample) if "couldn't be shown" in w]
    assert "ValidationError" in warned
    assert secret not in warned
    # so the secret is nowhere in the sample's log
    assert secret not in sample.model_dump_json()


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


def test_a_call_whose_question_closed_before_inspect_asked_gets_its_held_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person = Person("approve")
    person.install(monkeypatch)
    # the question timed out before Inspect first asked about the call, and
    # the sidecar decided to let the turn go on
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn()], closed_before_asked=True
    )

    sample = _sample(_run(stand_in))

    # nobody here was asked, and the turn the sidecar held is the call's
    assert person.asked == []
    [got] = stand_in.held_reply_requests
    assert got.headers["x-irid"] == stand_in.model_calls[0].headers["x-irid"]
    event = _model_events(sample)[0]
    assert event.error is None
    assert _LOOKED_UP == ["Oslo"]


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


@pytest.mark.parametrize(
    "error_lost",
    [True, False],
    ids=["got from the sidecar", "passed on to Inspect's own try"],
)
def test_a_providers_error_that_its_own_code_reads_as_a_reply_is_the_calls_result(
    error_lost: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # Anthropic's code reads a prompt that is too long as a reply that
    # stopped for the model's length, and not as an error. The proxy passes
    # the provider's error on to the try the sidecar sent on, which is
    # Inspect's own unless another try of the call was with the provider.
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=400)],
        error_lost=error_lost,
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
    assert len(stand_in.held_reply_requests) == (1 if error_lost else 0)
    assert review_module._open_calls == {}


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


def test_a_lookup_lost_on_the_way_doesnt_give_up_a_call_a_person_approved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lookup_module, "LOOKUP_RETRY_PAUSE", 0.01)
    Person("approve").install(monkeypatch)
    # the proxy fails once, for the lookup that follows the person's answer
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn()], lookups_lost=1
    )

    sample = _sample(_run(stand_in))

    # the sidecar is asked again, and the approved call goes on: the person
    # isn't asked twice, the call isn't cancelled, and its held reply is got
    assert stand_in.lookups_lost == 0
    assert sample.error is None
    assert len(_called(stand_in, "answer_question")) == 1
    assert stand_in.cancelled == []
    assert len(stand_in.held_reply_requests) == 1


def test_lookups_that_keep_being_lost_are_asked_again_only_so_many_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lookup_module, "LOOKUP_RETRY_PAUSE", 0.01)
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["tool_call"], turns=[_OSLO], lookups_lost=100)

    log = _run(stand_in, solver=generate(), fail_on_error=False)

    # The lookup is lost, and so is each of the times it is asked again. The
    # call's judgment is then unavailable, and the call is given up: it is
    # cancelled at the sidecar, which is asked once more for its records.
    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None
    assert 100 - stand_in.lookups_lost == 1 + lookup_module.LOOKUP_RETRIES + 1
    [first] = stand_in.model_calls
    assert stand_in.cancelled == [first.headers["x-irid"]]
    assert stand_in.held_reply_requests == []


def test_a_lookup_the_sidecar_answers_with_an_error_isnt_asked_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lookup_module, "LOOKUP_RETRY_PAUSE", 0.01)
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO], lookups_refused=100
    )

    log = _run(stand_in, solver=generate(), fail_on_error=False)

    # an error the sidecar itself gave is its answer: one lookup after the
    # person's answer, and one after the call is cancelled
    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None
    assert 100 - stand_in.lookups_refused == 2
    [first] = stand_in.model_calls
    assert stand_in.cancelled == [first.headers["x-irid"]]


def test_questions_the_sidecar_wont_list_fail_the_review_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["tool_call"], turns=[_OSLO])
    asked: list[dict[str, Any]] = []

    def invalid(params: dict[str, Any]) -> dict[str, Any]:
        # an error of the sidecar's own, which asking again wouldn't change
        asked.append(params)
        return stand_in._refuse(-32602, "The call's parameters can't be read.")

    stand_in.methods["pending_questions"] = invalid

    # the sample's own limit is far off: it ends a review that goes on
    # asking, so that such a test fails and doesn't hang
    log = _run(stand_in, solver=generate(), fail_on_error=False, time_limit=10)

    # asked once, and the sample fails on the sidecar's error; the call is
    # closed at the sidecar, which still holds its question
    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None and sample.limit is None
    assert "won't take the eval's calls" in sample.error.message
    assert len(asked) == 1
    [first] = stand_in.model_calls
    assert stand_in.cancelled == [first.headers["x-irid"]]


def test_questions_lost_on_the_way_are_asked_for_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lookup_module, "LOOKUP_RETRY_PAUSE", 0.01)
    person = Person("approve")
    person.install(monkeypatch)
    # the proxy fails as many times as Inspect asks again, and then answers
    stand_in = ReviewingSidecar(
        pauses=["tool_call"],
        turns=[_OSLO, Turn()],
        questions_lost=lookup_module.LOOKUP_RETRIES,
    )

    sample = _sample(_run(stand_in))

    # the person is shown the question once it is got, and the call goes on
    assert stand_in.questions_lost == 0
    assert sample.error is None
    assert len(person.asked) == 1
    assert stand_in.cancelled == []
    assert len(stand_in.held_reply_requests) == 1


def test_questions_that_keep_being_lost_are_asked_for_only_so_many_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lookup_module, "LOOKUP_RETRY_PAUSE", 0.01)
    person = Person("approve")
    person.install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["tool_call"], turns=[_OSLO], questions_lost=100)

    log = _run(stand_in, solver=generate(), fail_on_error=False, time_limit=10)

    # The sidecar goes on saying a question is open, and that doesn't begin
    # the count afresh: after the first loss and each time it is asked again,
    # the review fails and the call is closed at the sidecar.
    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None and sample.limit is None
    assert "couldn't be asked for the questions" in sample.error.message
    assert 100 - stand_in.questions_lost == 1 + lookup_module.LOOKUP_RETRIES
    assert person.asked == []
    [first] = stand_in.model_calls
    assert stand_in.cancelled == [first.headers["x-irid"]]


def test_an_answer_lost_on_the_way_is_sent_again_without_asking_the_person_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lookup_module, "LOOKUP_RETRY_PAUSE", 0.01)
    person = Person("approve")
    person.install(monkeypatch)
    # the proxy fails as many times as Inspect sends again, and then answers
    stand_in = ReviewingSidecar(
        pauses=["tool_call"],
        turns=[_OSLO, Turn()],
        answers_lost=lookup_module.LOOKUP_RETRIES,
    )

    sample = _sample(_run(stand_in))

    # the answer the person gave once reaches the sidecar, and the call goes on
    assert stand_in.answers_lost == 0
    assert sample.error is None
    assert len(person.asked) == 1
    [answer] = _called(stand_in, "answer_question")
    assert answer["decision"] == "approve"


def test_an_answer_that_keeps_being_lost_is_sent_only_so_many_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lookup_module, "LOOKUP_RETRY_PAUSE", 0.01)
    person = Person("approve")
    person.install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["tool_call"], turns=[_OSLO], answers_lost=100)

    # the sample's own limit is far off: it ends a review that goes on
    # sending, so that such a test fails and doesn't hang
    log = _run(stand_in, solver=generate(), fail_on_error=False, time_limit=10)

    # The sidecar goes on listing the question and saying it is open, and
    # neither begins the count afresh: after the first loss and each time the
    # answer is sent again, the review fails. The person was asked once.
    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None and sample.limit is None
    assert "answer couldn't be sent" in sample.error.message
    assert 100 - stand_in.answers_lost == 1 + lookup_module.LOOKUP_RETRIES
    assert len(person.asked) == 1
    # The call is closed at the sidecar when the review fails, not when the
    # sample ends, so the record of its question is in the sample's log.
    [first] = stand_in.model_calls
    assert stand_in.cancelled == [first.headers["x-irid"]]
    [logged] = _reviews_logged(sample)
    assert logged["review"]["resolution"] == "cancelled"
    assert review_module._open_calls == {}


def _without(question: dict[str, Any], member: str) -> dict[str, Any]:
    return {name: value for name, value in question.items() if name != member}


@pytest.mark.parametrize(
    "unreadable",
    [
        pytest.param(lambda listed: {}, id="no list"),
        pytest.param(lambda listed: {"questions": None}, id="null"),
        pytest.param(lambda listed: {"questions": "none"}, id="a string"),
        pytest.param(
            lambda listed: {"questions": ["a question"]}, id="an entry that is text"
        ),
        pytest.param(
            lambda listed: {"questions": [{**q, "id": 7} for q in listed]},
            id="an id that is a number",
        ),
        pytest.param(
            lambda listed: {"questions": [_without(q, "id") for q in listed]},
            id="no id",
        ),
        pytest.param(
            lambda listed: {"questions": [_without(q, "request_id") for q in listed]},
            id="no request id",
        ),
    ],
)
def test_questions_listed_in_a_form_inspect_cant_read_fail_the_review_at_once(
    monkeypatch: pytest.MonkeyPatch,
    unreadable: Callable[[list[dict[str, Any]]], dict[str, Any]],
) -> None:
    person = Person("approve")
    person.install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["tool_call"], turns=[_OSLO])
    listed = stand_in._pending_questions
    asked: list[dict[str, Any]] = []

    def listing(params: dict[str, Any]) -> dict[str, Any]:
        asked.append(params)
        return unreadable(listed(params)["questions"])

    stand_in.methods["pending_questions"] = listing

    # the sample's own limit is far off: it ends a review that goes on
    # asking, so that such a test fails and doesn't hang
    log = _run(stand_in, solver=generate(), fail_on_error=False, time_limit=10)

    # A list that can't be read isn't taken for one with no questions, which
    # Inspect would go on asking for. The review fails on the first, nobody
    # is asked, and the error tells nothing of what a question held.
    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None and sample.limit is None
    assert "in a form Inspect can't read" in sample.error.message
    assert "Oslo" not in sample.error.message
    assert len(asked) == 1
    assert person.asked == []
    # closed at the sidecar at once, so the question's record is in the log
    [first] = stand_in.model_calls
    assert stand_in.cancelled == [first.headers["x-irid"]]
    [logged] = _reviews_logged(sample)
    assert logged["review"]["resolution"] == "cancelled"


@solver
def _generates_beside_a_waiting_task() -> Solver:
    # one model call, while another task of the sample waits on something
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        waiting = anyio.Event()
        done = anyio.Event()

        async def waits() -> None:
            with sample_wait():
                waiting.set()
                await done.wait()

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(waits)
            # the other task's wait is open before the call begins
            await waiting.wait()
            state.output = await get_model().generate(state.messages)
            done.set()
        return state

    return solve


@pytest.mark.parametrize(
    "pending_lost,holds",
    [
        # the provider's client hands the sidecar's "pending review" back, so
        # the held reply is got after the attempt's own block has ended
        (0, [(0.0, 0.0), (1.0, 0.0)]),
        # every try of the first send loses its connection, so the client
        # raises, and the held reply is got inside the attempt's block
        (10, [(1.0, 0.0)]),
    ],
    ids=["its error handed back", "its error raised"],
)
def test_a_send_after_a_review_is_the_models_time_while_another_task_waits(
    pending_lost: int,
    holds: list[tuple[float, float]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # the send that gets the held reply takes a second
    stand_in = ReviewingSidecar(
        pauses=["tool_call"],
        turns=[Turn(text="Sunny.")],
        pending_lost=pending_lost,
        holds=list(holds),
    )

    sample = _sample(_run(stand_in, solver=_generates_beside_a_waiting_task()))

    # that second is the model's, for the sample as for the model event,
    # though another task of the sample was waiting all the while
    assert stand_in.holds == []
    [event] = _model_events(sample)
    assert event.working_time is not None and sample.working_time is not None
    assert event.working_time >= 0.8
    assert sample.working_time >= 0.8


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


def test_a_pending_review_lost_on_the_way_is_found_and_not_asked_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person = Person("approve")
    person.install(monkeypatch)
    # Every try the provider's SDK makes of the paused call loses its
    # connection before the sidecar's "pending review" comes back, so Inspect
    # holds an error it retries.
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn()], pending_lost=10
    )

    sample = _sample(_run(stand_in))

    # The sidecar is asked about the call first, so the person is asked once,
    # the held reply is got under the call's own id, and Inspect's retry is
    # never another model call at the sidecar.
    assert sample.error is None
    assert len(person.asked) == 1
    [got] = stand_in.held_reply_requests
    first = stand_in.model_calls[0]
    assert got.headers["x-irid"] == first.headers["x-irid"]
    assert _LOOKED_UP == ["Oslo"]


def test_a_call_given_up_on_after_a_lost_pending_review_is_cancelled_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def never(*args: object, **kwargs: object) -> Approval:
        await anyio.sleep_forever()
        raise AssertionError

    async def acp(**kwargs: object) -> Approval | None:
        return None

    monkeypatch.setattr(acp_module, "request_human_approval_via_acp", acp)
    monkeypatch.setattr(approver_module, "panel_approval", never)
    # the sidecar's "pending review" is lost on every try
    stand_in = ReviewingSidecar(pauses=["tool_call"], turns=[_OSLO], pending_lost=10)
    cancelled_before_the_sample_ended: list[list[str]] = []

    @solver
    def gives_up_on_one_call() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            # the solver stops waiting for the call while the person decides,
            # and the sample goes on
            with anyio.move_on_after(5):
                await generate(state)
            cancelled_before_the_sample_ended.append(list(stand_in.cancelled))
            return state

        return solve

    _run(stand_in, solver=gives_up_on_one_call())

    # the call is cancelled at the sidecar when it is given up on, not only
    # when the sample ends
    first = stand_in.model_calls[0]
    assert cancelled_before_the_sample_ended == [[first.headers["x-irid"]]]


def test_a_call_whose_exchanges_keep_being_cut_off_isnt_sent_again_without_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["tool_result"], cut_off=True)

    sample = _sample(
        _run(stand_in, solver=generate(), fail_on_error=False, time_limit=30)
    )

    # sent on a bounded number of times, after which the error stands and the
    # call fails by Inspect's own rules
    assert sample.error is not None
    assert len(stand_in.model_calls) == 1 + MODEL_SENDS


def test_a_reviewed_calls_judge_usage_is_counted_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # every lookup of the paused call gives the same usage, added up over it
    stand_in = ReviewingSidecar(
        pauses=["tool_call"],
        turns=[_OSLO, Turn()],
        judge_usage={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
    )

    sample = _sample(_run(stand_in))

    # it was looked up more than once, and its usage is counted once
    paused_id = stand_in.model_calls[0].headers["x-irid"]
    looked_up = [
        call
        for call in _called(stand_in, "request_result")
        if call.get("id") == paused_id
    ]
    assert len(looked_up) > 1
    judge = sample.model_usage["mockllm/judge"]
    assert (judge.input_tokens, judge.output_tokens) == (100, 10)
    assert sample.role_usage["monitor"].input_tokens == 100


@pytest.mark.parametrize(
    "stage,holds,model_time",
    [
        # the provider replied before the sentinel asked, and the held reply
        # is got at once
        ("tool_call", [(1.0, 0.4), (0.0, 0.0)], 0.6),
        # the sentinel asked before the provider was called, and judged the
        # reply of the send it sent on
        ("tool_result", [(0.5, 0.5), (1.0, 0.3)], 0.7),
    ],
)
def test_a_reviewed_call_counts_only_the_models_time_in_its_sends(
    stage: str,
    holds: list[tuple[float, float]],
    model_time: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the person takes a second, which is theirs, not the model's
    Person("approve", takes=1.0).install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=[stage], turns=[_OSLO, Turn()], holds=list(holds)
    )

    sample = _sample(_run(stand_in))

    # each send's time counts, less the sentinel's judging in it
    assert stand_in.holds == []
    event = _model_events(sample)[0]
    assert event.working_time is not None and event.output.time is not None
    assert event.working_time >= model_time - 0.1
    assert event.output.time == event.working_time
    assert sample.working_time is not None
    assert sample.working_time >= model_time - 0.1
    # the person's second between the sends, and the sentinel's judging in
    # them, are waiting, for the event and for the sample
    judging = sum(judged for _, judged in holds)
    assert _event_waiting(event) >= 1.0 + judging - 0.1
    assert _sample_waiting(sample) >= 1.0 + judging - 0.1


def test_a_reviewed_call_inspect_retries_counts_only_its_own_judging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # Inspect retries at once, so the test needn't wait
    monkeypatch.setattr(AnthropicAPI, "retry_wait", lambda self: wait_none())
    # The sentinel judges the request 0.3 seconds before it asks. The
    # provider fails the request the sidecar sends on, and its error is got
    # from the sidecar. Inspect retries the call under its id, and that try
    # is sent on and held 0.8 seconds, 0.2 of them judging its reply.
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=529), Turn(text="Sunny.")],
        sdk_retries=False,
        holds=[(0.3, 0.3), (0.0, 0.0), (0.0, 0.0), (0.8, 0.2)],
    )

    sample = _sample(_run(stand_in, solver=generate()))

    # the retry is charged its own model time; the earlier judging was
    # waiting already, with the attempt it was in
    assert stand_in.holds == []
    assert sample.output.completion == "Sunny."
    event = _model_events(sample)[-1]
    assert event.working_time is not None
    # 0.6 seconds of the retry were the model's: the 0.3 seconds judged in
    # the earlier attempt are not taken from it again
    assert event.working_time >= 0.5
    # and its own 0.2 seconds of judging are waiting
    assert _event_waiting(event) >= 0.2 - 0.05


def test_a_reviewed_call_that_fails_counts_only_the_models_time_in_its_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # The request sent on after the person approved is retried by the
    # provider's SDK after a 529, with the SDK's own wait, and that try is
    # held 0.3 seconds and refused by the provider. Its error is got from
    # the sidecar, and the sample fails on it.
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=529), Turn(status=403)],
        holds=[(0.3, 0.3), (0.0, 0.0), (0.3, 0.0), (0.0, 0.0)],
    )

    log = _run(stand_in, solver=generate(), fail_on_error=False)

    sample = _sample(log)
    assert sample.error is not None and "403" in sample.error.message
    assert stand_in.holds == []
    # The try the provider refused was held 0.3 seconds, which is the model's
    # time. The sentinel's judging of the first send, 0.3 seconds, and the
    # SDK's wait before its last try, 0.375 seconds at least, are waiting,
    # whatever the call came to. They are measured against the sample's whole
    # time: a slow machine adds to the working time and to the whole alike.
    assert sample.working_time is not None
    assert sample.working_time >= 0.2
    assert _sample_waiting(sample) >= 0.6


def test_a_rejected_call_counts_only_the_models_time_before_the_person(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Every try of the paused call loses its connection before the sidecar's
    # "pending review" comes back, so it is never sent again. The person
    # takes a second to reject it.
    Person("reject", takes=1.0).install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn()], pending_lost=10
    )

    sample = _sample(_run(stand_in))

    # The call's own time is its lost tries', and the person's second isn't
    # in it, for the event or for the sample. The SDK's waits between those
    # tries are waiting as well, so the person's second is looked for on top
    # of them: the waits alone come to less.
    assert stand_in.held_reply_requests == []
    # three tries of the call, so the SDK waited twice
    first = stand_in.model_calls[0].headers["x-irid"]
    assert sum(r.headers["x-irid"] == first for r in stand_in.model_calls) == 3
    event = _model_events(sample)[0]
    assert event.working_time is not None and event.output.time is not None
    assert event.output.time == event.working_time
    assert _event_waiting(event) >= 1.0 + _SDK_RETRY_WAITS - 0.1
    assert _sample_waiting(sample) >= 1.0 + _SDK_RETRY_WAITS - 0.1


def test_a_send_cut_short_by_the_sample_ending_counts_as_the_models_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)

    def end_the_sample_in_a_second() -> None:
        # timed from when the request is held, so that however long the
        # sample took to get there, the send is cut short a second into it
        active = sample_active()
        assert active is not None
        asyncio.get_running_loop().call_later(1.0, active.interrupt, "score")

    # Every try of the paused call loses its connection before the sidecar's
    # "pending review" comes back. Once the person approves, the request
    # that gets the held reply is held until the sample is ended.
    stand_in = ReviewingSidecar(
        pauses=["tool_call"],
        turns=[_OSLO, Turn()],
        pending_lost=10,
        holds=[(30.0, 0.0)],
        when_held=end_the_sample_in_a_second,
    )

    log = _run(stand_in)

    assert log.samples is not None
    [sample] = log.samples
    [got] = stand_in.held_reply_requests
    # The request was held from when it came until the sample's end cut it
    # short, as the stand-in timed it: that time was with the model, inside
    # the send, and counts as work.
    [held] = stand_in.held_requests
    assert not held.finished
    assert held.ended - held.began >= 0.9
    assert sample.working_time is not None
    assert sample.working_time >= (held.ended - held.began) - 0.1


def test_a_request_sent_again_waits_for_an_operators_hard_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paused_at: list[float] = []

    async def operator_pauses() -> None:
        # an operator pauses the process hard while the person decides, and
        # resumes it half a second later
        await pause_process(now=True)
        paused_at.append(time.monotonic())
        asyncio.get_running_loop().call_later(
            0.5, lambda: asyncio.ensure_future(resume_process())
        )

    Person("approve", meanwhile=operator_pauses).install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(text="Sunny.")],
        holds=[(0.0, 0.0), (0.0, 0.0)],
    )

    sample = _sample(_run(stand_in, solver=generate()))

    # the request the sidecar sends on to the provider went out only once
    # the process was resumed
    assert sample.output.completion == "Sunny."
    assert not process_paused()
    [_, sent_on_at] = stand_in.held_at
    assert sent_on_at - paused_at[0] >= 0.4


# --- a call's timeout ---------------------------------------------------------


def test_the_time_a_person_takes_isnt_counted_toward_the_calls_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the person takes longer than the call's whole timeout
    Person("approve", takes=1.5).install(monkeypatch)
    # Inspect retries at once, so the test needn't wait
    monkeypatch.setattr(AnthropicAPI, "retry_wait", lambda self: wait_none())
    # the provider fails the request the sidecar sends on, then answers
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=529), Turn(text="Sunny.")],
        sdk_retries=False,
    )

    sample = _sample(_run(stand_in, solver=generate(), timeout=1))

    # the provider's failure is retried, as it would be had nobody been asked
    assert sample.output.completion == "Sunny."


def test_a_try_that_times_out_while_the_provider_works_is_followed_to_its_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The person takes 2.5 seconds, and Inspect's attempt at the request the
    # sidecar sends on times out after another second: more than the call's
    # timeout of 3 with the person's time, and well within it without.
    Person("approve", takes=2.5).install(monkeypatch)
    monkeypatch.setattr(lookup_module, "AWAITED_REPLY_PAUSE", 0.01)
    monkeypatch.setattr(lookup_module, "AWAITED_REPLY_PAUSE_MAX", 0.01)
    # the provider is still working for 25 asks of the sidecar
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(text="Sunny.")],
        provider_takes_asks=25,
    )

    sample = _sample(_run(stand_in, solver=generate(), timeout=3, attempt_timeout=1))

    # Inspect went on asking until the reply had come, got it from the
    # sidecar, and sent nothing more to the provider meanwhile
    assert sample.output.completion == "Sunny."
    assert len(stand_in.model_calls) == 2
    assert len(stand_in.held_reply_requests) == 1
    assert stand_in.cancelled == []


def test_a_call_whose_timeout_passes_while_the_provider_works_is_closed_at_the_sidecar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # the provider never answers the request the sidecar sent on
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(text="Sunny.")],
        provider_takes_asks=1_000_000,
    )

    # the sample's own limit is far off: it ends a call that outlives its
    # timeout, so that such a test fails and doesn't hang
    log = _run(
        stand_in,
        solver=generate(),
        fail_on_error=False,
        timeout=2,
        attempt_timeout=1,
        time_limit=30,
    )

    # the call fails once its timeout has passed, and not before; its own
    # timeout ends it, and not the sample's limit; and the sidecar is told
    # it is given up
    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None and sample.limit is None
    assert sample.total_time is not None and sample.total_time >= 1.9
    [first, _] = stand_in.model_calls
    assert stand_in.cancelled == [first.headers["x-irid"]]


def test_a_lookup_under_way_when_the_calls_timeout_passes_is_given_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    monkeypatch.setattr(lookup_module, "AWAITED_REPLY_PAUSE", 0.01)
    # The provider never answers. The sidecar says so at once the first time
    # it is asked, and takes ten seconds to say it again.
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(text="Sunny.")],
        provider_takes_asks=1_000_000,
        lookups_take=[0.0, 10.0],
    )

    log = _run(
        stand_in,
        solver=generate(),
        fail_on_error=False,
        timeout=2,
        attempt_timeout=1,
        time_limit=30,
    )

    # the call fails when its timeout passes, and not before; the lookup the
    # sidecar took ten seconds over was given up, and not waited out; and the
    # sidecar is told the call is given up
    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None and sample.limit is None
    assert sample.total_time is not None and sample.total_time >= 1.9
    assert stand_in.awaited_lookups == 2
    [slow] = [held for held in stand_in.held_requests if held.path == ENDPOINT]
    assert not slow.finished
    [first, _] = stand_in.model_calls
    assert stand_in.cancelled == [first.headers["x-irid"]]


def test_the_sidecar_isnt_asked_again_once_the_calls_timeout_has_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # Inspect next asks five seconds after the first time, or when the
    # call's timeout passes if that is sooner. The provider's reply comes
    # meanwhile, which only asking again would tell.
    monkeypatch.setattr(lookup_module, "AWAITED_REPLY_PAUSE", 5.0)
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(text="Sunny.")],
        provider_takes_asks=2,
    )

    log = _run(
        stand_in,
        solver=generate(),
        fail_on_error=False,
        timeout=2,
        attempt_timeout=1,
    )

    # the call's time is up, so it fails without asking, and is closed
    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None
    assert stand_in.awaited_lookups == 1
    [first, _] = stand_in.model_calls
    assert stand_in.cancelled == [first.headers["x-irid"]]


def test_a_reply_that_came_within_the_calls_timeout_is_judged_past_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    monkeypatch.setattr(lookup_module, "AWAITED_REPLY_PAUSE", 0.01)
    # The provider's reply comes within the call's timeout of 2 seconds.
    # The sidecar then judges it for six asks, half a second apart, which
    # ends after the timeout has passed.
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(text="Sunny.")],
        provider_takes_asks=2,
        reply_judged_asks=6,
    )

    began = time.monotonic()
    sample = _sample(_run(stand_in, solver=generate(), timeout=2, attempt_timeout=1))

    # judging a reply has no deadline, as for any call: the call is decided
    assert time.monotonic() - began > 2
    assert sample.output.completion == "Sunny."
    assert stand_in.cancelled == []


async def test_a_followed_call_asked_about_again_isnt_bound_by_its_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lookup_module, "AWAITED_REPLY_PAUSE", 0.01)
    monkeypatch.setattr(review_module, "NO_QUESTION_PAUSE", 0.01)
    # What the sidecar says of the call each time it is asked. The provider
    # still has the request, then a second question is open, with the judging
    # of the provider's reply between them never seen, then the call is
    # decided.
    states = ["awaiting_reply", "awaiting_review", "decided"]
    cancelled: list[str] = []

    class Sidecar:
        origin = "http://proxy.test"
        review = True

        async def eval_call(self, method: str, params: dict[str, Any]) -> Any:
            if method == "pending_questions":
                # the call's timeout passes while the question is dealt with
                await anyio.sleep(0.6)
                return {"questions": []}
            if method == "cancel_request":
                cancelled.append(params["id"])
                return {"id": params["id"], "cancelled": True}
            assert method == "request_result"
            state = states.pop(0) if len(states) > 1 else states[0]
            result: dict[str, Any] = {
                "id": params["id"],
                "records": "held",
                "state": state,
            }
            if state == "decided":
                result["judgment"] = {"outcome": "proceed", "steps": []}
            return result

    with receiving_call(Sidecar(), timeout=1) as received:
        # a call a person was asked about, with half of its timeout left
        received.request_id = received.reviewed_id = "request_1"
        received.sent = received.open = True
        received.began = time.monotonic() - 0.5
        looked = await lookup_module.request_result(received, replied=False)

    # the provider had replied, so the call is decided, and isn't given up
    assert looked.state == "decided"
    assert cancelled == []


# --- a call Inspect gives up on -----------------------------------------------


def test_a_call_whose_review_fails_is_closed_at_once_with_its_question_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["tool_call"], turns=[_OSLO])
    listed = stand_in._pending_questions

    def only_modify(params: dict[str, Any]) -> dict[str, Any]:
        # a question with no choice Inspect can offer a person
        questions = listed(params)
        for question in questions["questions"]:
            question["choices"] = ["modify"]
        return questions

    stand_in.methods["pending_questions"] = only_modify

    log = _run(stand_in, solver=generate(), fail_on_error=False)

    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None
    # The call is closed at the sidecar when its review fails, not when the
    # sample ends, so the record of its question is in the sample's log.
    [first] = stand_in.model_calls
    assert stand_in.cancelled == [first.headers["x-irid"]]
    [logged] = _reviews_logged(sample)
    assert logged["review"]["resolution"] == "cancelled"
    assert review_module._open_calls == {}


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
