"""Tests of human review through a sidecar, in Inspect's sidecar client.

A sentinel in a sidecar can ask a person about a tool call. The sidecar then
pauses the model call: it answers the request with a "pending review" error
and keeps the call under its `x-irid`. Once the person has answered, Inspect
fetches the provider's reply from the sidecar's judged-reply path, or resends
the request so that the proxy passes it on to the provider.

`ReviewingSidecar` stands in for the proxy and the sidecar, and pauses calls
the same way. The first tests check that a call with no sidecar is unchanged.
"""

import asyncio
import json
import math
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

import anyio
import httpx2
import pytest
from markdown_it import MarkdownIt
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
from inspect_ai._sentinel._person import held_call_view
from inspect_ai._sentinel._sidecar import _lookup as lookup_module
from inspect_ai._sentinel._sidecar import _review as review_module
from inspect_ai._sentinel._sidecar._act import refused_output
from inspect_ai._sentinel._sidecar._endpoint import QUESTION_ANSWERED
from inspect_ai._sentinel._sidecar._received import (
    JUDGED_REPLY_PATH,
    ReceivedCall,
    _received,
    current_receiving,
    receiving_call,
    request_id_to_reuse,
    route_fetch_to_sidecar,
)
from inspect_ai._sentinel._sidecar._review import (
    FAILED_TRY_HEADER,
    MAX_ERROR_FETCHES,
    MAX_RESENDS,
)
from inspect_ai._sentinel._sidecar._task import SampleFacts, task_sidecars
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
    ChatMessageUser,
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentToolUse,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.model._providers.anthropic import AnthropicAPI
from inspect_ai.model._providers.util.hooks import HttpxHooks
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver, use_tools
from inspect_ai.tool import Tool, ToolCall, ToolCallContent, ToolCallView, tool
from inspect_ai.tool._tool_call import substitute_tool_call_content

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
    """A model call that the stand-in paused for a person, kept under its `x-irid`."""

    stage: str
    """Where the call was paused.

    `tool_call` and `model_output`: at its reply, which the stand-in holds.
    At `model_output` the question is about the whole turn. `tool_result` and
    `model_input`: at its request, before the provider was called. At
    `model_input` the question is about the request.
    """
    route: str
    state: str = "awaiting_review"
    turn: Turn | None = None
    """The provider's reply, once the provider was called."""
    judgment: dict[str, Any] | None = None
    failure: dict[str, Any] | None = None
    reason: str | None = None
    tries: int = 0
    reviews: list[dict[str, Any]] = field(default_factory=list)
    """The record of each question about the call, as `request_result` returns it."""
    judging_time: float = 0.0
    """How long the sentinel spent judging the call's requests, in seconds, in total."""


@dataclass
class _HeldRequest:
    """A request the stand-in held before answering it, as a proxy holds a call.

    `began` and `ended` are when the hold began and ended, on the monotonic
    clock.
    """

    path: str
    began: float
    ended: float = 0.0
    finished: bool = False
    """Whether the hold ran its full time.

    False if the client went away first, for example because the call was
    cancelled or timed out.
    """


@dataclass
class ReviewingSidecar(StandInSidecar):
    """A stand-in sidecar that pauses model calls and asks a person about them."""

    pauses: list[str] = field(default_factory=list)
    """Where to pause each new model call, in order: one of the four stages.

    Calls after the list runs out aren't paused.
    """
    paused: dict[str, _Paused] = field(default_factory=dict)
    cancelled: list[str] = field(default_factory=list)
    judged_reply_statuses: list[int] = field(default_factory=list)
    """Error statuses that the judged-reply path returns first, in order.

    After them it returns what it holds. They stand for the sidecar's own
    refusals, so they lack the header that marks a provider's error.
    """
    asked_turn: ChatMessageAssistant | None = None
    """The turn that a question shows, in place of the held one: the whole turn at `model_output`, and the turn that made the call, without its calls, at `tool_call`."""
    asked_request: list[ChatMessage] | None = None
    """The messages that a question about a request shows as not sent before, in place of the stand-in's own."""
    forced_tool: str | None = None
    """The one function that a question about a request says the model must call."""
    expires: bool = False
    """Whether each question times out at the sidecar before the person answers.

    The sidecar then rejects the call, and refuses the person's answer because
    the question has closed.
    """
    closes_while_shown: bool = False
    """Whether each question times out at the sidecar while the person is still shown it.

    A `request_result` that names the question finds it timed out, and its
    call rejected.
    """
    open_checks_lost: int = 0
    """How many `request_result` calls that name a question the proxy fails with a 502."""
    judged_step: bool = False
    """Whether an approved call's judgment includes the step that asked the question.

    The step names the question's id.
    """
    records_dropped: bool = False
    """Whether the sidecar drops the call's records once a person has answered."""
    error_arriving_lookups: int = 0
    """How many times `request_result` returns `awaiting_reply` after a failure.

    It stands for a sidecar that is still receiving the provider's error. The
    sidecar reports the failure only once it has the whole error.
    """
    failure_message: str | None = None
    """A message for the provider's error, in Anthropic's format.

    It replaces the stand-in's default error body, both on the try passed on
    to the provider and on the judged-reply path.
    """
    lookups_lost: int = 0
    """How many `request_result` calls the proxy fails with a 502.

    Only calls about a paused call whose question is no longer open count.
    They never reach the sidecar.
    """
    lookups_refused: int = 0
    """How many of those `request_result` calls the sidecar answers with an error."""
    questions_lost: int = 0
    """How many `list_pending_questions` calls the proxy fails with a 502.

    They never reach the sidecar.
    """
    answers_lost: int = 0
    """How many `answer_question` calls the proxy fails with a 502.

    They never reach the sidecar.
    """
    error_cut_off: int = 0
    """How many fetches of the provider's error lose their connection part way.

    The headers arrive, including the sidecar's `x-sentinel-failed-try`. The
    connection fails before the whole body does.
    """
    pending_reviews_lost: int = 0
    """How many "pending review" answers are lost with their connection, from the first.

    With a large number, every try that the provider's SDK makes on its own
    fails this way.
    """
    when_pending_review_lost: Callable[[], None] | None = None
    when_resend_lost: Callable[[], None] | None = None
    """Set to have a resend that the sidecar passed on to a busy provider lose its connection, and run as it does.

    The provider still has the request, and Inspect gets a connection error.
    """
    """Run as a "pending review" answer is lost, for what happens before the client's next try."""
    cut_off: bool = False
    """Whether the provider's reply is cut off on every try passed on to it.

    The stand-in then reports `cut_off`, and answers Inspect's try with a 400.
    """
    judge_usage: dict[str, Any] | None = None
    """The judge model's usage for the whole call.

    Every `request_result` about a paused call returns it, as the sidecar does.
    """
    error_hidden_by_pending_review: bool = False
    """Whether Inspect gets "pending review" when the provider fails a resend.

    Without it, Inspect gets the provider's error. It stands for a try the
    sidecar answered while another try of the call was with the provider.
    """
    provider_busy_lookups: int = 0
    """How many times `request_result` returns `awaiting_reply` for a resend.

    The stand-in holds the resend's own connection for 60 seconds, so Inspect's
    attempt at it times out first.
    """
    lookup_durations: list[float] = field(default_factory=list)
    """How long each `request_result` that finds `awaiting_reply` takes, in seconds.

    In order. Calls after the list runs out are answered at once.
    """
    awaited_lookups: int = 0
    """How many `request_result` calls found the call at `awaiting_reply`."""
    judging_lookups: int = 0
    """How many times `request_result` returns `judging` once the provider has replied.

    After that the call is `decided`.
    """
    closed_before_asked: bool = False
    """Whether a `tool_call` question times out before Inspect first looks the call up.

    The call is then `decided` with `proceed`, so the turn still goes ahead.
    """
    sdk_retries: bool = True
    """Whether the provider's SDK may retry a provider's error on a resend.

    If not, the stand-in adds `x-should-retry: false`, so the SDK returns the
    error to Inspect.
    """
    holds: list[tuple[float, float]] = field(default_factory=list)
    """How long the proxy holds each request of a paused call, in order, in seconds.

    Each pair is the whole hold, and how much of it the sentinel spent judging.
    """
    held_at: list[float] = field(default_factory=list)
    """When each request that was given a hold arrived, on the monotonic clock."""

    when_held: Callable[[], None] | None = None
    """Called when the stand-in begins to hold a request.

    It runs in the task of the call that sent the request, so a test can time
    something from the start of the hold.
    """
    held_requests: list[_HeldRequest] = field(default_factory=list)
    """Each request the stand-in held, in order, with when its hold began and ended.

    A busy machine can hold a request longer than `holds` asked.
    """

    def __post_init__(self) -> None:
        assert self.info is not None
        self.info["review"] = True
        self.methods.setdefault("list_pending_questions", self._list_pending_questions)
        self.methods.setdefault("answer_question", self._answer_question)
        self.methods.setdefault("cancel_paused_request", self._cancel_paused_request)

    @property
    def judged_reply_requests(self) -> list[httpx2.Request]:
        return [r for r in self.requests if r.url.path == JUDGED_REPLY_PATH]

    async def _handle_async(self, request: httpx2.Request) -> httpx2.Response:
        response = self._handle(request)
        hold = self._holds.pop(id(request), 0.0)
        if hold:
            # The stand-in times the hold itself, so a test can compare the
            # time Inspect counted with the time the request was really held.
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
        if path == JUDGED_REPLY_PATH:
            self.requests.append(request)
            return self._held(request, self._judged_reply(request))
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
            if call["method"] == "list_pending_questions" and self.questions_lost > 0:
                self.questions_lost -= 1
                return httpx2.Response(502, text="Bad Gateway")
            if call["method"] == "answer_question" and self.answers_lost > 0:
                self.answers_lost -= 1
                return httpx2.Response(502, text="Bad Gateway")
            if (
                call["method"] == "request_result"
                and call["params"].get("question") is not None
                and self.open_checks_lost > 0
            ):
                self.open_checks_lost -= 1
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
                    if self.lookup_durations:
                        self._holds[id(request)] = self.lookup_durations.pop(0)
            else:
                self.methods.pop("request_result", None)
        return super()._handle(request)

    def _paused_call(self, request: httpx2.Request, irid: str) -> httpx2.Response:
        asked = json.loads(request.content)
        paused = self.paused.get(irid)
        if paused is None:
            paused = self.paused[irid] = _Paused(self.pauses.pop(0), request.url.path)
            paused.tries = 1
            if paused.stage in _AT_THE_REPLY:
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
        if paused.state != "awaiting_resend":
            # Only a call at `awaiting_resend` is passed on to the provider.
            # Any other try gets "pending review", and Inspect reads the
            # call's state with `request_result`.
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
            if self.error_hidden_by_pending_review:
                return _refusal("pending review")
        elif self.provider_busy_lookups > 0:
            # the provider is still working, and the sidecar will hold its reply
            paused.turn = turn
            paused.state = "awaiting_reply"
            if self.when_resend_lost is not None:
                self.when_resend_lost()
                raise httpx2.ReadError("The connection was lost.", request=request)
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
        # The proxy holds the request for `hold` seconds, and the sentinel
        # spends `judging` seconds of that judging it.
        if self.holds:
            hold, judging = self.holds.pop(0)
            self._holds[id(request)] = hold
            self.paused[request.headers["x-irid"]].judging_time += judging
            self.held_at.append(time.monotonic())
        return response

    def _pending(self, request: httpx2.Request) -> httpx2.Response:
        # The sidecar's "pending review" error. While `pending_reviews_lost` lasts,
        # the connection fails before the error arrives.
        if self.pending_reviews_lost > 0:
            self.pending_reviews_lost -= 1
            if self.when_pending_review_lost is not None:
                self.when_pending_review_lost()
            raise httpx2.ConnectError("The connection was lost.", request=request)
        return _refusal("pending review")

    def _judged_reply(self, request: httpx2.Request) -> httpx2.Response:
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
        if self.judged_reply_statuses:
            return httpx2.Response(
                self.judged_reply_statuses.pop(0),
                json={"error": {"type": "error", "message": "Not now."}},
            )
        paused = self.paused.get(irid or "")
        asked = json.loads(request.content)
        if (
            paused is not None
            and paused.state == "awaiting_resend"
            and paused.reason == "provider_error"
            and paused.failure is not None
        ):
            # The provider's error. `x-sentinel-failed-try` names the failed
            # try, and `x-should-retry: false` stops the SDK retrying the fetch.
            failed = _MODEL_ROUTES[paused.route](
                Turn(status=paused.failure["reply"]["status"]),
                bool(asked.get("stream")),
                asked,
            )
            if self.failure_message is not None:
                failed = self._failed(
                    paused.failure["reply"]["status"], self.failure_message
                )
            failed.headers[FAILED_TRY_HEADER] = str(paused.failure["try_number"])
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
            return _refusal("no judged reply")
        return _MODEL_ROUTES[paused.route](
            paused.turn, bool(asked.get("stream")), asked
        )

    def _unaccepted(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if method != "answer_question":
            return super()._unaccepted(method, params)
        # the signature of `answer_question` also covers the question's id,
        # the decision and the reason
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
                # the question timed out twelve minutes before the person answered
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
        if (
            self.closes_while_shown
            and params.get("question") is not None
            and paused.state == "awaiting_review"
        ):
            ended = time.time()
            paused.reviews.append(
                {
                    "id": params["question"],
                    "try_number": 1,
                    "stage": paused.stage,
                    "call": "call_1",
                    "asked": ended - 60,
                    "resolution": "timed_out",
                    "resolved": ended,
                }
            )
            self._rejected(paused, "No person answered in time.")
        if self.records_dropped and paused.reviews:
            return {"id": params["id"], "records": "dropped"}
        if paused.failure is not None and self.error_arriving_lookups > 0:
            self.error_arriving_lookups -= 1
            return {"id": params["id"], "records": "held", "state": "awaiting_reply"}
        if paused.state == "judging" and paused.turn is not None:
            self.judging_lookups -= 1
            if self.judging_lookups <= 0:
                paused.state = "decided"
                paused.judgment = {"outcome": "proceed", "steps": []}
        if paused.state == "awaiting_reply":
            self.provider_busy_lookups -= 1
            if self.provider_busy_lookups <= 0 and self.judging_lookups > 0:
                # the provider has replied, and the sentinel is judging the reply
                paused.state = "judging"
            elif self.provider_busy_lookups <= 0:
                # the provider has replied, and the sentinel has judged the reply
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

    def _list_pending_questions(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "questions": [
                {
                    "id": f"question_{irid}",
                    "sample_uuid": params.get("sample_uuid"),
                    "request_id": irid,
                    "stage": paused.stage,
                    "escalations": [
                        {"name": "risk_monitor", "explanation": "A new city."}
                    ],
                    "asked": 0.0,
                    **self._asked_about(paused),
                }
                for irid, paused in self.paused.items()
                if paused.state == "awaiting_review"
            ]
        }

    def _asked_about(self, paused: _Paused) -> dict[str, Any]:
        # what the question shows the person, and what they may pick
        if paused.stage == "model_input":
            # the request, which can go on or end the run
            new = self.asked_request or [ChatMessageUser(content="What's the weather?")]
            # the request sends two messages the model was sent before, then
            # these
            sent = len(new) + 2
            return {
                "message": "",
                "request": {
                    "model": "claude-haiku-4-5",
                    "messages": sent,
                    "new": [
                        {
                            "position": position,
                            "message": message.model_dump(
                                mode="json", exclude_none=True
                            ),
                        }
                        for position, message in enumerate(new, 3)
                    ],
                    **(
                        {
                            "tools": [self.forced_tool],
                            "tool_choice": "function",
                            "tool_function": self.forced_tool,
                        }
                        if self.forced_tool is not None
                        else {"tools": ["weather"], "tool_choice": "auto"}
                    ),
                },
                "choices": ["approve", "terminate"],
            }
        if paused.stage == "model_output":
            # the whole turn, which can go on or end the run
            turn = self.asked_turn or _held_turn(paused.turn or Turn())
            return {
                "message": turn.text,
                "turn": turn.model_dump(mode="json", exclude_none=True),
                "choices": ["approve", "terminate"],
            }
        made_by: dict[str, Any] = {}
        said = "Checking."
        if paused.stage == "tool_call" and self.asked_turn is not None:
            # the turn that made the call, which the sidecar still holds
            turn = self.asked_turn.model_copy(update={"tool_calls": None})
            said = turn.text
            made_by = {"turn": turn.model_dump(mode="json", exclude_none=True)}
        return {
            "call": {
                "id": "call_1",
                "function": "weather",
                "arguments": {"city": "Oslo"},
                "type": "function",
            },
            "message": said,
            "view": {},
            "choices": ["approve", "reject", "terminate"],
            **made_by,
        }

    def _answer_question(self, params: dict[str, Any]) -> dict[str, Any]:
        paused = self.paused[params["id"].removeprefix("question_")]
        now = time.time()
        # a question at a generate stage names no call
        call = None if paused.stage in ("model_input", "model_output") else "call_1"
        record = {
            "id": params["id"],
            "try_number": 1,
            "stage": paused.stage,
            "call": call,
            "asked": now,
            "decision": params["decision"],
            "answered": now,
            "resolution": "answered",
            "resolved": now,
        }
        paused.reviews.append({k: v for k, v in record.items() if v is not None})
        if params["decision"] == "terminate" and paused.stage == "model_input":
            # the person ended the run at the request, which is never sent on
            paused.state = "decided"
            paused.judgment = {
                "outcome": "terminate",
                "steps": [
                    {
                        "stage": "model_input",
                        "decision": {
                            "action": "terminate",
                            "explanation": params.get("reason") or "Ended.",
                        },
                        "reviews": [params["id"]],
                    }
                ],
            }
        elif params["decision"] == "terminate" and paused.stage == "model_output":
            # the person ended the run at the turn, none of whose calls runs
            turn = paused.turn or Turn()
            paused.state = "decided"
            paused.judgment = {
                "outcome": "terminate",
                "steps": [
                    {
                        "stage": "model_output",
                        "decision": {
                            "action": "terminate",
                            "explanation": params.get("reason") or "Ended.",
                        },
                        "reviews": [params["id"]],
                    }
                ],
                "withheld": {
                    "message": _held_turn(turn).model_dump(
                        mode="json", exclude_none=True
                    ),
                    "results": {
                        id: "This call was not run." for id, _, _ in turn.calls
                    },
                },
            }
        elif params["decision"] != "approve":
            self._rejected(paused, params.get("reason") or "Rejected.")
        elif paused.stage in _AT_THE_REPLY:
            paused.state = "decided"
            step = {
                "stage": paused.stage,
                "call": call,
                "decision": {"action": "proceed"},
                "reviews": [params["id"]],
            }
            paused.judgment = {
                "outcome": "proceed",
                "steps": [step] if self.judged_step else [],
            }
        else:
            paused.state = "awaiting_resend"
        return {"id": params["id"], "decision": params["decision"]}

    def _cancel_paused_request(self, params: dict[str, Any]) -> dict[str, Any]:
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
    # a response body whose connection fails part way through
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'{"type": "err'
        raise httpx2.ReadError("The connection was lost.")


_AT_THE_REPLY = ("tool_call", "model_output")
"""The stages at which a call is paused at its reply, which the sidecar then holds."""


def _held_turn(turn: Turn) -> ChatMessageAssistant:
    # the turn the stand-in holds, as the sidecar writes it into a question
    return ChatMessageAssistant(
        content=turn.text,
        tool_calls=[
            ToolCall(id=id, function=function, arguments=arguments)
            for id, function, arguments in turn.calls
        ],
    )


def _refusal(message: str) -> httpx2.Response:
    return httpx2.Response(400, json={"error": {"type": "error", "message": message}})


class Person:
    """A person at Inspect's approval panel, who gives the same answer every time."""

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
        """Something to run once they have decided, before the panel returns."""
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
"""The least Anthropic's SDK waits before its second and third tries, in seconds.

After a failed connection it waits half a second, then a second, each
shortened by up to a quarter.
"""


def _event_waiting(event: ModelEvent) -> float:
    # The part of a model event's duration that was not working time, in
    # seconds. A slow machine adds the same amount to the duration and to the
    # working time, so the difference doesn't depend on the machine's speed.
    assert event.completed is not None and event.working_time is not None
    return (event.completed - event.timestamp).total_seconds() - event.working_time


def _sample_waiting(sample: EvalSample) -> float:
    # the same for a sample: its total time minus its working time
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
        # this request names a sample, but its call isn't paused, so the hook
        # leaves its path alone
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
    # `refused_output` called neither `retryable` nor `send_again`
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

    # The person sees the messages Inspect sent with the call. Inspect
    # supplies them itself, because the sidecar's question has none.
    [history] = person.shown
    assert [(m.role, m.text) for m in history] == [("user", "What's the weather?")]


@pytest.mark.parametrize("provider", ["anthropic", "openai-api"])
def test_the_judged_reply_of_an_approved_call_is_fetched_on_the_same_model_event(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    person = Person("approve")
    person.install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["tool_call"], turns=[_OSLO, Turn()])

    sample = _sample(_run(stand_in, provider))

    # The person saw the call, and the monitor that escalated it. The sidecar
    # holds the reply, so Inspect has shown none of the turn: its text is in the
    # view, above the call, and not in a message that an ACP client leaves out.
    [(message, call, view, choices)] = person.asked
    assert (message, call.function, call.arguments) == (
        "",
        "weather",
        {"city": "Oslo"},
    )
    assert view.call is not None
    shown = view.call.content
    assert shown.index("risk_monitor: A new city.") < shown.index("The turn says")
    assert shown.index("The turn says") < shown.index("Checking.")
    assert choices == ["approve", "reject", "terminate"]

    # Inspect sent the same request twice under one `x-irid`: first to the
    # model's path, then to the judged-reply path as a fetch. The provider was
    # called once.
    route = "/v1/messages" if provider == "anthropic" else "/v1/chat/completions"
    first, second, third = [
        r for r in stand_in.requests if r.url.path in (route, JUDGED_REPLY_PATH)
    ]
    assert (first.url.path, second.url.path) == (route, JUDGED_REPLY_PATH)
    assert first.headers["x-irid"] == second.headers["x-irid"]
    assert first.content == second.content
    # the next model call has an `x-irid` of its own
    assert third.url.path == route
    assert third.headers["x-irid"] != first.headers["x-irid"]
    assert stand_in.refused == []

    # The call has one model event. It holds the reply, the response to the
    # request that fetched it, and usage that is counted once.
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
    # the tool ran once the person approved the call
    assert _LOOKED_UP == ["Oslo"]
    assert stand_in.cancelled == []


def test_a_judged_reply_keeps_its_response_ids_and_its_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)

    def with_request_id(request: httpx2.Request) -> httpx2.Response:
        response = stand_in._handle(request)
        if request.url.path == JUDGED_REPLY_PATH:
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
    # Inspect fetched the judged reply as a stream, and read it as one
    [held] = stand_in.judged_reply_requests
    assert json.loads(held.content)["stream"] is True
    assert streamed, "the judged reply's deltas reached the stream handler"
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
    # Inspect fetches no judged reply, and answers the tool call with the
    # person's rejection
    assert stand_in.judged_reply_requests == []
    [tool_message] = [m for m in sample.messages if isinstance(m, ChatMessageTool)]
    assert tool_message.error is not None
    assert (tool_message.error.type, tool_message.error.message) == (
        "approval",
        "Not Oslo.",
    )
    assert _LOOKED_UP == []


def test_a_question_that_cant_be_shown_leaks_none_of_its_contents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person = Person("approve")
    person.install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn(text="I can't look that up.")]
    )
    listed = stand_in._list_pending_questions
    secret = "sk-not-to-be-told"

    def unreadable(params: dict[str, Any]) -> dict[str, Any]:
        # Inspect can't read this question's call, because its arguments are
        # a list. The list holds a secret.
        questions = listed(params)
        for question in questions["questions"]:
            question["call"]["arguments"] = ["--api-key", secret]
        return questions

    stand_in.methods["list_pending_questions"] = unreadable

    sample = _sample(_run(stand_in))

    # no person is asked, and Inspect answers `reject` in their place
    assert person.asked == []
    [answer] = _called(stand_in, "answer_question")
    assert answer["decision"] == "reject"
    # The model sees the reason sent with the answer. The reason names the
    # error's type and leaves out its text, which contains the arguments.
    assert "ValidationError" in answer["reason"]
    assert secret not in answer["reason"]
    # the same goes for the warning in the eval's log
    [warned] = [w for w in _warned(sample) if "couldn't be shown" in w]
    assert "ValidationError" in warned
    assert secret not in warned
    # so the secret is nowhere in the sample's log
    assert secret not in sample.model_dump_json()


def _unreadable_message(request: dict[str, Any], secret: str) -> str:
    # a message whose role Inspect can't read, holding the secret
    request["new"][0]["message"] = {"role": "nobody", "content": secret}
    return "ValidationError"


def _no_function_named(request: dict[str, Any], secret: str) -> str:
    # a forced call that names no function, in a request holding the secret
    request["new"][0]["message"]["content"] = secret
    request["tool_choice"] = "function"
    request.pop("tool_function", None)
    return "ValueError"


@pytest.mark.parametrize(
    "spoil",
    [
        pytest.param(_unreadable_message, id="a message it can't read"),
        pytest.param(_no_function_named, id="a forced call with no function"),
    ],
)
def test_a_request_question_that_cant_be_shown_ends_the_sample_and_leaks_nothing(
    spoil: Callable[[dict[str, Any], str], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    person = Person("approve")
    person.install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["model_input"], turns=[Turn(text="Sunny.")])
    listed = stand_in._list_pending_questions
    secret = "sk-not-to-be-told"
    raised: list[str] = []

    def unreadable(params: dict[str, Any]) -> dict[str, Any]:
        questions = listed(params)
        for question in questions["questions"]:
            raised.append(spoil(question["request"], secret))
        return questions

    stand_in.methods["list_pending_questions"] = unreadable

    sample = _sample(_run(stand_in, solver=generate()))

    # No person is asked. A request can't be rejected, so Inspect answers
    # `terminate` in their place, and the sample ends.
    assert person.asked == []
    [answer] = _called(stand_in, "answer_question")
    assert answer["decision"] == "terminate"
    assert sample.limit is not None and sample.limit.type == "operator"
    # The reason and the warning name the error's type, and nothing of the
    # request: a validation error quotes the values it couldn't read.
    error = raised[0]
    [warned] = [w for w in _warned(sample) if "couldn't be shown" in w]
    assert error in answer["reason"] and error in warned
    assert secret not in answer["reason"] and secret not in warned
    assert secret not in sample.model_dump_json()


def test_an_sdk_retry_of_the_judged_reply_request_keeps_the_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn()], judged_reply_statuses=[503]
    )

    sample = _sample(_run(stand_in))

    # the SDK retried the fetch itself, to the same path, under the same id
    first, second = stand_in.judged_reply_requests
    assert first.headers["x-irid"] == second.headers["x-irid"]
    assert first.content == second.content
    assert _LOOKED_UP == ["Oslo"]
    assert _model_events(sample)[0].error is None


def test_a_continuation_after_the_judged_reply_goes_to_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # The judged reply stops with `pause_turn`, so Inspect's provider code
    # sends a continuation request, which has a different body.
    stand_in = ReviewingSidecar(
        pauses=["tool_call"],
        turns=[Turn(text="Searching.", stop_reason="pause_turn"), Turn()],
    )

    _run(stand_in, solver=generate())

    [held] = stand_in.judged_reply_requests
    continuation = stand_in.requests[stand_in.requests.index(held) + 1]
    assert continuation.url.path == "/v1/messages"
    assert continuation.headers["x-irid"] == held.headers["x-irid"]
    assert continuation.content != held.content


# --- a call paused at its reply, for a question about the whole turn ----------


_TWO_CITIES = Turn(
    text="Checking both.",
    calls=[
        ("call_1", "weather", {"city": "Oslo"}),
        ("call_2", "weather", {"city": "Bergen"}),
    ],
)


def test_a_person_is_shown_a_whole_turn_and_an_approved_turn_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person = Person("approve")
    person.install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["model_output"], turns=[_TWO_CITIES, Turn()], judged_step=True
    )

    sample = _sample(_run(stand_in))

    # The person is asked once, about the turn as a whole. The view holds the
    # turn's text, because none of the turn has reached Inspect to be shown.
    [(message, call, view, choices)] = person.asked
    assert message == ""
    assert call.function == "Assistant turn: 2 tool calls (weather ×2)"
    assert view.call is not None
    shown = view.call.content
    assert "risk_monitor: A new city." in shown and "Checking both." in shown
    assert shown.index("Call 1 of 2") < shown.index("Oslo") < shown.index("Call 2 of 2")
    assert "Bergen" in shown
    # a turn can go on or end the run: it can't be rejected
    assert choices == ["approve", "terminate"]

    # Inspect fetched the judged reply, and the turn's calls ran
    assert len(stand_in.judged_reply_requests) == 1
    assert _LOOKED_UP == ["Oslo", "Bergen"]
    # the question's record is in the log, and names no call
    [logged] = _reviews_logged(sample)
    review = logged["review"]
    assert (review["stage"], review["decision"]) == ("model_output", "approve")
    assert "call" not in review


def _turn_shown(
    monkeypatch: pytest.MonkeyPatch, *content: Content, calls: int = 1
) -> str:
    # the view a person is shown for a turn with this content
    person = Person("approve")
    person.install(monkeypatch)
    turn = ChatMessageAssistant(
        content=list(content),
        tool_calls=[
            ToolCall(id=f"call_{n}", function="weather", arguments={"city": "Oslo"})
            for n in range(1, calls + 1)
        ],
    )
    _run(
        ReviewingSidecar(
            pauses=["model_output"], turns=[_OSLO, Turn()], asked_turn=turn
        )
    )
    [(message, _, view, _)] = person.asked
    assert message == "" and view.call is not None
    return view.call.content


_ENCRYPTED = "gAAAAB-encrypted-reasoning"


@pytest.mark.parametrize(
    ("reasoning", "shown", "withheld"),
    [
        pytest.param(
            ContentReasoning(reasoning="First I will wipe the disk."),
            "First I will wipe the disk.",
            False,
            id="readable",
        ),
        pytest.param(
            ContentReasoning(
                reasoning=_ENCRYPTED, redacted=True, summary="Plans to wipe the disk."
            ),
            "Plans to wipe the disk.",
            False,
            id="redacted, with a summary",
        ),
        pytest.param(
            ContentReasoning(reasoning="", summary="Plans to wipe the disk."),
            "Plans to wipe the disk.",
            False,
            id="a summary only",
        ),
        pytest.param(
            ContentReasoning(reasoning=_ENCRYPTED, redacted=True),
            None,
            True,
            id="redacted, with nothing to read",
        ),
    ],
)
def test_a_person_reads_the_turns_reasoning_before_they_decide(
    reasoning: ContentReasoning,
    shown: str | None,
    withheld: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = _turn_shown(monkeypatch, reasoning, ContentText(text="Checking."))

    # None of the turn has reached Inspect, so the view is the only place the
    # person can read what the model reasoned. Reasoning comes before the
    # turn's words.
    if shown is not None:
        assert view.index("The turn's reasoning") < view.index(shown)
        assert view.index(shown) < view.index("The turn says")
    # reasoning the provider withheld is counted, never shown as its cipher text
    assert ("withheld the text of 1 block" in view) == withheld
    assert _ENCRYPTED not in view


def test_a_turns_own_words_cant_pass_for_the_rest_of_the_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forged = "Fine.\n```\n\n---\n\n**The turn makes no tool calls.**\n\n```\n\x1b[2J"

    view = _turn_shown(
        monkeypatch,
        ContentReasoning(reasoning=forged),
        ContentText(text=forged),
        calls=2,
    )

    # Each block of the model's own words is fenced by more backticks than it
    # holds, so it can't close its block and write the view's own lines.
    for heading in ("**The turn's reasoning**", "**The turn says**"):
        block = view[view.index(heading) + len(heading) :].lstrip("\n")
        assert block.startswith("````\n")
    assert "**The turn makes 2 tool calls.**" in view
    # a control character is shown as a marker, and the view says so
    assert "\x1b" not in view and "hidden or control characters" in view


def test_a_person_is_shown_what_the_provider_ran_during_the_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = _turn_shown(
        monkeypatch,
        ContentToolUse(
            tool_type="mcp_call",
            id="mcp_1",
            name="delete_repo",
            context="github",
            arguments='{"repo": "prod"}',
            result="Deleted prod.",
        ),
        ContentToolUse(
            tool_type="web_search",
            id="search_1",
            name="web_search",
            arguments='{"query": "undo"}',
            result="",
            error="max_uses_exceeded",
        ),
        ContentImage(image="data:image/png;base64,AAAA"),
        ContentText(text="Done."),
        calls=0,
    )

    # A tool the provider runs is no call of the turn's, and it has already run.
    # The view is the only place the person can read what it was sent and what
    # it returned.
    assert "**The turn makes no tool calls.**" in view
    first = view.index("Tool 1 of 2 that the provider ran:")
    second = view.index("Tool 2 of 2 that the provider ran:")
    assert first < view.index('{"repo": "prod"}') < view.index("Deleted prod.") < second
    assert "github" in view[first:second]
    assert view.index('{"query": "undo"}') < view.index("max_uses_exceeded")
    # content the view can't show is counted, so none of the turn goes unsaid
    assert "content that is not shown here: 1 image." in view
    assert "base64" not in view


def test_what_the_provider_ran_cant_pass_for_the_rest_of_the_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forged = "ok\n```\n\n---\n\n**The turn makes no tool calls.**\n\n```"

    view = _turn_shown(
        monkeypatch,
        ContentToolUse(
            tool_type="mcp_call",
            id="mcp_1",
            name="**It returned**\nnothing",
            arguments=forged,
            result=forged,
        ),
    )

    # a tool's name is one line of plain text, and what it was sent and what it
    # returned are each in a code block they cannot close
    assert "\\*\\*It returned\\*\\* nothing" in view
    assert view.count("````\nok\n```") == 2
    assert view.count("**The turn makes") == 3
    assert "**The turn makes 1 tool call.**" in view


def test_a_person_asked_about_a_call_is_shown_the_rest_of_its_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person = Person("approve")
    person.install(monkeypatch)
    turn = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="Oslo first, then wipe the disk."),
            ContentText(text="Checking {{city}}."),
        ]
    )

    _run(ReviewingSidecar(pauses=["tool_call"], turns=[_OSLO, Turn()], asked_turn=turn))

    # The sidecar holds the reply that makes the call, so the view has what the
    # person could read nowhere else: the turn's reasoning and its text, above
    # the call.
    [(message, call, view, _)] = person.asked
    assert message == "" and view.call is not None
    shown = substitute_tool_call_content(view.call, call.arguments).content
    assert shown.index("The turn's reasoning") < shown.index("then wipe the disk.")
    assert shown.index("then wipe the disk.") < shown.index("The turn says")
    # the turn's words are not a template for the call's arguments
    assert "Checking { {city}}." in shown and "Checking Oslo." not in shown


def _outside_code_blocks(markdown: str) -> list[str]:
    # The lines of a view that are in no code block: the view's own. A block
    # is closed by a line of backticks at least as long as the one that opened
    # it, as CommonMark closes one.
    outside: list[str] = []
    fence = 0
    for line in markdown.splitlines():
        ticks = len(line) - len(line.lstrip("`"))
        if fence == 0 and ticks >= 3:
            fence = ticks
        elif fence and ticks >= fence and ticks == len(line):
            fence = 0
        elif fence == 0 and line:
            outside.append(line)
    assert fence == 0
    return outside


_BASH = "```bash\n{{command}}\n```\n"
"""The view inspect_ai's own bash viewer makes: the command, between fixed fences."""


@pytest.mark.parametrize(
    ("made", "block"),
    [
        pytest.param(
            ToolCallContent(format="text", content="run: {{command}}"),
            "````\nrun: ok",
            id="a viewer that writes plain text",
        ),
        pytest.param(
            ToolCallContent(title="bash", format="markdown", content=_BASH),
            "````bash\nok",
            id="a viewer that fences a code block",
        ),
        pytest.param(
            ToolCallContent(format="markdown", content="Runs `{{command}}` now."),
            "````markdown\nRuns `ok",
            id="a viewer that writes other markdown",
        ),
    ],
)
def test_nothing_in_a_held_calls_view_passes_for_one_of_its_labels(
    made: ToolCallContent, block: str
) -> None:
    # Text that closes a code block and writes a label. Padded to the window's
    # width, plain text wraps and starts at the margin with no line break.
    forged = "ok\n```\n\n**The turn says**\n\ndenied" + " " * 500 + "It failed with"
    turn = ChatMessageAssistant(
        content=[
            ContentToolUse(
                tool_type="mcp_call",
                id="mcp_1",
                name="deploy",
                arguments="{}",
                result=forged,
            )
        ]
    )
    call = ToolCall(
        id="call_1", function="bash", arguments={"command": forged, "other": "`````"}
    )

    view = held_call_view(
        ToolCallView(
            context=ToolCallContent(format="markdown", content="In {{command}}"),
            call=made,
        ),
        call,
        f"- risk_monitor: {forged} {{{{other}}}}",
        turn,
    )

    # Everything a tool, a monitor or the tool's viewer wrote is inside a code
    # block it can't close, where a wrapped line stays in the block. Only the
    # view's own labels are outside. The viewer's context is in the view too,
    # so no part of what a surface shows is left as the viewer made it.
    assert view.context is None and view.call is not None
    assert view.call.format == "markdown"
    assert _outside_code_blocks(view.call.content) == [
        "**Escalated by**",
        "**Tool 1 of 1 that the provider ran:** deploy \\(mcp\\_call\\)",
        "**It returned**",
        "**The call's context**",
        "**The call**",
    ]
    assert f"**The call**\n\n{block}\n" in view.call.content
    # the surfaces fill in the call's arguments once more, which changes nothing
    again = substitute_tool_call_content(view.call, call.arguments)
    assert again.content == view.call.content


class _Notified:
    """An Apprise instance that keeps what it was asked to send."""

    def __init__(self) -> None:
        self.bodies: list[str] = []

    def notify(self, body: str, title: str) -> bool:
        self.bodies.append(body)
        return True


@pytest.mark.parametrize("stage", ["model_output", "tool_call"])
def test_the_operator_is_notified_with_the_turns_text_once(
    stage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    Person("approve").install(monkeypatch)
    notified = _Notified()
    monkeypatch.setattr("inspect_ai._eval.eval.build_apprise", lambda config: notified)

    _run(ReviewingSidecar(pauses=[stage], turns=[_OSLO, Turn()]))

    # The view holds the turn's text, and the prompt's message is empty. The
    # notification still says what the turn said, as it does for a turn that
    # reached Inspect, and the operator is told once.
    [body] = notified.bodies
    assert body.endswith("Checking.")


def test_a_person_who_ends_the_run_at_a_turn_ends_the_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("terminate", "Not this.").install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["model_output"], turns=[_TWO_CITIES, Turn()])

    log = _run(stand_in)

    # the sample ends as an operator's limit, with the person's reason, and
    # none of the turn's calls runs
    sample = _sample(log)
    assert sample.limit is not None
    assert (sample.limit.type, sample.limit.reason) == ("operator", "Not this.")
    assert _LOOKED_UP == []
    assert stand_in.judged_reply_requests == []


@pytest.mark.parametrize(
    ("stage", "about"),
    [("model_output", "the model's turn"), ("model_input", "the model's request")],
)
def test_an_answer_at_a_generate_stage_that_came_too_late_says_what_it_was_about(
    stage: str, about: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=[stage], turns=[_TWO_CITIES, Turn()], expires=True
    )

    sample = _sample(_run(stand_in))

    [told] = [w for w in _warned(sample) if "wasn't used" in w]
    assert f"question about {about}" in told


# --- a call paused at its request ---------------------------------------------


def test_a_call_paused_at_its_request_is_resent_for_the_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["tool_result"], turns=[Turn(text="Sunny.")])

    sample = _sample(_run(stand_in, solver=generate()))

    # Inspect sent the request twice to the model's path under one `x-irid`.
    # The second is the resend, which the sidecar passed on to the provider.
    first, second = stand_in.model_calls
    assert first.headers["x-irid"] == second.headers["x-irid"]
    assert first.content == second.content
    assert stand_in.judged_reply_requests == []
    [event] = _model_events(sample)
    assert event.error is None
    assert event.output.message.text == "Sunny."
    assert sample.output.completion == "Sunny."


def test_a_person_is_shown_a_request_and_an_approved_request_is_sent_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person = Person("approve")
    person.install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["model_input"], turns=[Turn(text="Sunny.")])

    sample = _sample(_run(stand_in, solver=generate()))

    # the person is asked once, about the request and what it adds
    [(message, call, view, choices)] = person.asked
    assert message == ""
    assert call.function == "Model request: 3 messages (1 not sent before)"
    assert view.call is not None
    shown = view.call.content
    assert "risk_monitor: A new city." in shown
    assert (
        "3 messages to claude\\-haiku\\-4\\-5, 2 of which the model was sent "
        "before. The other 1 is below."
    ) in shown
    assert (
        "Tools offered (1): ` weather `. The model may call any of them, or none."
    ) in shown
    assert shown.index("**Message 3 of 3:** user") < shown.index("What's the weather?")
    # a request can go on or end the run: it can't be rejected
    assert choices == ["approve", "terminate"]

    # Inspect resent the request under the same `x-irid`, and the sidecar
    # passed the resend on to the provider
    first, second = stand_in.model_calls
    assert first.headers["x-irid"] == second.headers["x-irid"]
    assert stand_in.judged_reply_requests == []
    assert sample.output.completion == "Sunny."
    # the question's record is in the log, and names no call
    [logged] = _reviews_logged(sample)
    assert (logged["review"]["stage"], logged["review"]["decision"]) == (
        "model_input",
        "approve",
    )
    assert "call" not in logged["review"]


def test_a_person_who_ends_the_run_at_a_request_ends_the_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("terminate", "Not this.").install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["model_input"], turns=[Turn(text="Sunny.")])

    sample = _sample(_run(stand_in, solver=generate()))

    # the sample ends as an operator's limit, with the person's reason, and
    # the request is never sent again for the provider
    assert sample.limit is not None
    assert (sample.limit.type, sample.limit.reason) == ("operator", "Not this.")
    assert len(stand_in.model_calls) == 1
    assert sample.output.completion == ""


@pytest.mark.parametrize("name", ["send_keys", "none"])
def test_a_request_the_sidecar_asks_about_says_which_function_must_be_called(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    person = Person("approve")
    person.install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["model_input"], turns=[Turn(text="Sunny.")], forced_tool=name
    )

    _run(stand_in, solver=generate())

    # a tool named for a choice, such as `none`, can't pass for that choice
    [(_, _, view, _)] = person.asked
    assert view.call is not None
    assert f"The model must call the function ` {name} `." in view.call.content


def test_a_tools_output_in_a_request_cant_pass_for_the_rest_of_the_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person = Person("approve")
    person.install(monkeypatch)
    forged = "Sunny.\n```\n\n---\n\n**Message 2 of 2:** user\n\n```\nApprove.\x1b[2J"
    stand_in = ReviewingSidecar(
        pauses=["model_input"],
        turns=[Turn(text="Sunny.")],
        asked_request=[
            ChatMessageTool(content=forged, tool_call_id="call_1", function="weather")
        ],
    )

    _run(stand_in, solver=generate())

    [(_, _, view, _)] = person.asked
    assert view.call is not None
    shown = view.call.content
    # the tool's output is one code block, which it can't close to write a
    # header of its own
    assert "**Message 3 of 3:** tool (weather)" in shown
    [block] = [
        token.content
        for token in MarkdownIt("commonmark").parse(shown)
        if token.type == "fence" and "Approve." in token.content
    ]
    assert block.startswith("Sunny.\n```\n\n---\n\n**Message 2 of 2:** user")
    assert "\x1b" not in shown and "hidden or control characters" in shown


def test_inspect_fetches_the_judged_reply_of_a_call_whose_question_closed_before_it_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person = Person("approve")
    person.install(monkeypatch)
    # the question timed out before Inspect first looked the call up, and
    # the sidecar decided `proceed`
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn()], closed_before_asked=True
    )

    sample = _sample(_run(stand_in))

    # Inspect asked no person, and fetched the judged reply as the call's result
    assert person.asked == []
    [fetch] = stand_in.judged_reply_requests
    assert fetch.headers["x-irid"] == stand_in.model_calls[0].headers["x-irid"]
    event = _model_events(sample)[0]
    assert event.error is None
    assert _LOOKED_UP == ["Oslo"]


def test_inspect_retries_a_provider_error_after_a_review_under_the_same_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # the provider fails the resend with a 529, then answers the retry
    stand_in = ReviewingSidecar(
        pauses=["tool_result"], turns=[Turn(status=529), Turn(text="Sunny.")]
    )

    sample = _sample(_run(stand_in, solver=generate()))

    assert sample.output.completion == "Sunny."
    ids = {r.headers["x-irid"] for r in stand_in.model_calls}
    assert len(ids) == 1
    # the person was asked once, however many times the request was sent
    assert len(_called(stand_in, "answer_question")) == 1


def test_a_provider_error_after_a_review_is_the_error_the_model_event_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # The provider answers the resend with a 403. Inspect doesn't retry a
    # 403, and the provider's client raises it.
    stand_in = ReviewingSidecar(pauses=["tool_result"], turns=[Turn(status=403)])

    log = _run(stand_in, solver=generate(), fail_on_error=False)

    sample = _sample(log)
    assert sample.error is not None
    # The call's one model event holds the provider's error, and the sample
    # fails with the same error, not with the sidecar's "pending review".
    [event] = _model_events(sample)
    assert event.pending is None
    assert event.error is not None
    assert "403" in event.error
    assert "403" in sample.error.message
    assert len(stand_in.model_calls) == 2


def test_inspect_fetches_the_providers_error_when_it_holds_the_sidecars_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # The provider answers the resend with a 403, which Inspect doesn't
    # retry. Inspect's own try gets "pending review" instead, as it does when
    # another try of the call is with the provider.
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=403)],
        error_hidden_by_pending_review=True,
    )

    sample = _sample(_run(stand_in, solver=generate(), fail_on_error=False))

    # The sample and the call's one model event both fail with the
    # provider's error, not with the sidecar's "pending review".
    assert sample.error is not None and "403" in sample.error.message
    [event] = _model_events(sample)
    assert event.pending is None
    assert event.error is not None and "403" in event.error
    assert "pending review" not in event.error
    # Inspect fetched the error once from the judged-reply path, under the
    # call's id. It didn't resend, because it doesn't retry a 403.
    [fetch] = stand_in.judged_reply_requests
    first, resend = stand_in.model_calls
    assert (
        fetch.headers["x-irid"] == first.headers["x-irid"] == resend.headers["x-irid"]
    )


def test_a_fetched_provider_error_is_retried_by_inspects_own_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # the provider returns a 529, then answers the retry; Inspect's own try
    # gets "pending review"
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=529), Turn(text="Sunny.")],
        error_hidden_by_pending_review=True,
    )

    sample = _sample(_run(stand_in, solver=generate()))

    # Inspect fetches the 529 and retries it. The sidecar passes the retry
    # on to the provider under the call's id, and the person is asked once.
    assert sample.output.completion == "Sunny."
    assert len({r.headers["x-irid"] for r in stand_in.model_calls}) == 1
    assert len(stand_in.judged_reply_requests) == 1
    assert len(_called(stand_in, "answer_question")) == 1


def test_inspect_asks_again_while_a_providers_error_is_still_arriving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # The sidecar reports the provider's failure only once it has the whole
    # error. Until then `request_result` returns `awaiting_reply`, twice here.
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=403)],
        error_hidden_by_pending_review=True,
        error_arriving_lookups=2,
    )

    sample = _sample(
        _run(
            stand_in, solver=generate(), fail_on_error=False, sentinel_proxy="required"
        )
    )

    # the call fails with the provider's error, not as a call whose reply
    # the sidecar never saw
    assert sample.error is not None and "403" in sample.error.message
    assert "never saw a reply" not in sample.error.message
    assert len(stand_in.judged_reply_requests) == 1


@pytest.mark.parametrize(
    "error_hidden_by_pending_review",
    [True, False],
    ids=["fetched from the sidecar", "passed on to Inspect's own try"],
)
def test_a_providers_error_that_its_own_code_reads_as_a_reply_is_the_calls_result(
    error_hidden_by_pending_review: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # Inspect's Anthropic code reads a "prompt is too long" error as a reply
    # with the stop reason `model_length`, not as an error. With
    # `error_hidden_by_pending_review`, Inspect fetches that error from the
    # sidecar. Without it, Inspect's own resend receives the error from the
    # proxy.
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=400)],
        error_hidden_by_pending_review=error_hidden_by_pending_review,
        failure_message="prompt is too long: 250000 tokens > 200000 maximum",
    )

    log = _run(stand_in, solver=generate(), sentinel_proxy="required")

    # as without a review, the sample continues with the provider's answer
    sample = _sample(log)
    assert sample.error is None
    assert sample.output.stop_reason == "model_length"
    # Inspect sends nothing more, so it cancels the call at the sidecar,
    # which was still at `awaiting_resend`
    first = stand_in.model_calls[0]
    assert stand_in.cancelled == [first.headers["x-irid"]]
    assert len(stand_in.model_calls) == 2
    assert len(stand_in.judged_reply_requests) == (
        1 if error_hidden_by_pending_review else 0
    )
    assert review_module._paused_calls == {}


def test_the_sidecars_own_refusal_read_as_a_reply_is_not_used_as_the_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # The provider answers the resend with a 403. The judged-reply path first
    # returns a 413 of the sidecar's own, without the header that marks a
    # provider's error. Inspect's Anthropic code reads a 413 as a reply with
    # the stop reason `model_length`.
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=403)],
        error_hidden_by_pending_review=True,
        judged_reply_statuses=[413],
    )

    sample = _sample(
        _run(
            stand_in, solver=generate(), fail_on_error=False, sentinel_proxy="required"
        )
    )

    # Inspect ignores the sidecar's own refusal. It fetches the error again,
    # and the call fails with the provider's error.
    assert sample.error is not None and "403" in sample.error.message
    assert len(stand_in.judged_reply_requests) == 2
    # and the refusal was never the call's result
    [event] = _model_events(sample)
    assert event.error is not None and "403" in event.error
    assert event.output.stop_reason != "model_length"


def test_a_fetch_of_the_providers_error_that_fails_part_way_is_tried_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # The provider answers the resend with a 403. Inspect's first fetch of
    # that error loses its connection after the headers, which include the
    # sidecar's marker, and before the whole body arrives.
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=403)],
        error_hidden_by_pending_review=True,
        error_cut_off=1,
    )

    sample = _sample(
        _run(
            stand_in, solver=generate(), fail_on_error=False, sentinel_proxy="required"
        )
    )

    # Inspect counts the failure as handled only once it has the whole
    # error. So it fetches the error again, and the call fails with the
    # provider's error. The provider is not called again.
    assert sample.error is not None and "403" in sample.error.message
    assert len(stand_in.judged_reply_requests) >= 2
    assert len(stand_in.model_calls) == 2


def test_the_sidecars_own_refusal_is_never_used_as_the_providers_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # The judged-reply path returns refusals of the sidecar's own. They have
    # the same status as the provider's error, but not the header that marks
    # a provider's error.
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=403)],
        error_hidden_by_pending_review=True,
        judged_reply_statuses=[403, 403],
    )

    sample = _sample(_run(stand_in, solver=generate(), fail_on_error=False))

    # Inspect fetches the error `MAX_ERROR_FETCHES` times, then gives up, and
    # the sample fails. The provider is not called again.
    assert len(stand_in.judged_reply_requests) == MAX_ERROR_FETCHES
    assert sample.error is not None
    assert len(stand_in.model_calls) == 2


# --- lost calls to the sidecar, and each question's record in the log ---------


def test_a_lookup_lost_on_the_way_doesnt_give_up_a_call_a_person_approved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lookup_module, "LOOKUP_RETRY_PAUSE", 0.01)
    Person("approve").install(monkeypatch)
    # the proxy fails the first `request_result` after the person's answer
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn()], lookups_lost=1
    )

    sample = _sample(_run(stand_in))

    # Inspect calls `request_result` again, and the approved call continues.
    # The person isn't asked twice, the call isn't cancelled, and Inspect
    # fetches the judged reply.
    assert stand_in.lookups_lost == 0
    assert sample.error is None
    assert len(_called(stand_in, "answer_question")) == 1
    assert stand_in.cancelled == []
    assert len(stand_in.judged_reply_requests) == 1


def test_lookups_that_keep_being_lost_are_asked_again_only_so_many_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lookup_module, "LOOKUP_RETRY_PAUSE", 0.01)
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["tool_call"], turns=[_OSLO], lookups_lost=100)

    log = _run(stand_in, solver=generate(), fail_on_error=False)

    # The proxy fails the lookup and every retry of it. Inspect then treats
    # the call's judgment as unavailable and gives up on the call. It cancels
    # the call at the sidecar, and looks it up once more for its records.
    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None
    assert 100 - stand_in.lookups_lost == 1 + lookup_module.LOOKUP_RETRIES + 1
    [first] = stand_in.model_calls
    assert stand_in.cancelled == [first.headers["x-irid"]]
    assert stand_in.judged_reply_requests == []


def test_a_lookup_the_sidecar_answers_with_an_error_isnt_asked_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lookup_module, "LOOKUP_RETRY_PAUSE", 0.01)
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO], lookups_refused=100
    )

    log = _run(stand_in, solver=generate(), fail_on_error=False)

    # Inspect doesn't retry an error that the sidecar itself returned. It
    # makes one lookup after the person's answer, and one after it cancels
    # the call.
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
        # the sidecar's own error, which a retry would not change
        asked.append(params)
        return stand_in._refuse(-32602, "The call's parameters can't be read.")

    stand_in.methods["list_pending_questions"] = invalid

    # The sample's time limit is a safety net. If the review kept asking,
    # the limit would end it, so the test would fail and not hang.
    log = _run(stand_in, solver=generate(), fail_on_error=False, time_limit=10)

    # Inspect asks once, and the sample fails with the sidecar's error.
    # Inspect cancels the call at the sidecar, which still holds the question.
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
    # the proxy fails `list_pending_questions` `LOOKUP_RETRIES` times, the
    # most Inspect retries, and then answers
    stand_in = ReviewingSidecar(
        pauses=["tool_call"],
        turns=[_OSLO, Turn()],
        questions_lost=lookup_module.LOOKUP_RETRIES,
    )

    sample = _sample(_run(stand_in))

    # once Inspect has the question it shows the person, and the call continues
    assert stand_in.questions_lost == 0
    assert sample.error is None
    assert len(person.asked) == 1
    assert stand_in.cancelled == []
    assert len(stand_in.judged_reply_requests) == 1


def test_questions_that_keep_being_lost_are_asked_for_only_so_many_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lookup_module, "LOOKUP_RETRY_PAUSE", 0.01)
    person = Person("approve")
    person.install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["tool_call"], turns=[_OSLO], questions_lost=100)

    log = _run(stand_in, solver=generate(), fail_on_error=False, time_limit=10)

    # Between failures, `request_result` keeps returning `awaiting_review`,
    # and that doesn't reset the count. After the first failure and
    # `LOOKUP_RETRIES` retries, the review fails, and Inspect cancels the
    # call at the sidecar.
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
    # the proxy fails `answer_question` `LOOKUP_RETRIES` times, the most
    # Inspect retries, and then answers
    stand_in = ReviewingSidecar(
        pauses=["tool_call"],
        turns=[_OSLO, Turn()],
        answers_lost=lookup_module.LOOKUP_RETRIES,
    )

    sample = _sample(_run(stand_in))

    # the person is asked once, their answer reaches the sidecar, and the
    # call continues
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

    # The sample's time limit is a safety net. If the review kept sending
    # the answer, the limit would end it, so the test would fail and not hang.
    log = _run(stand_in, solver=generate(), fail_on_error=False, time_limit=10)

    # Between failures, the sidecar keeps listing the question and returning
    # `awaiting_review`, and neither resets the count. After the first
    # failure and `LOOKUP_RETRIES` retries, the review fails. The person was
    # asked once.
    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None and sample.limit is None
    assert "answer couldn't be sent" in sample.error.message
    assert 100 - stand_in.answers_lost == 1 + lookup_module.LOOKUP_RETRIES
    assert len(person.asked) == 1
    # Inspect cancels the call at the sidecar when the review fails, not
    # when the sample ends. So the question's record is in the sample's log.
    [first] = stand_in.model_calls
    assert stand_in.cancelled == [first.headers["x-irid"]]
    [logged] = _reviews_logged(sample)
    assert logged["review"]["resolution"] == "cancelled"
    assert review_module._paused_calls == {}


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
    listed = stand_in._list_pending_questions
    asked: list[dict[str, Any]] = []

    def listing(params: dict[str, Any]) -> dict[str, Any]:
        asked.append(params)
        return unreadable(listed(params)["questions"])

    stand_in.methods["list_pending_questions"] = listing

    # The sample's time limit is a safety net. If the review kept asking,
    # the limit would end it, so the test would fail and not hang.
    log = _run(stand_in, solver=generate(), fail_on_error=False, time_limit=10)

    # Inspect doesn't treat an unreadable list as an empty one, because it
    # would then keep asking. The review fails on the first list, no person
    # is asked, and the error shows nothing from the questions.
    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None and sample.limit is None
    assert "in a form Inspect can't read" in sample.error.message
    assert "Oslo" not in sample.error.message
    assert len(asked) == 1
    assert person.asked == []
    # Inspect cancels the call at the sidecar at once, so the question's
    # record is in the log
    [first] = stand_in.model_calls
    assert stand_in.cancelled == [first.headers["x-irid"]]
    [logged] = _reviews_logged(sample)
    assert logged["review"]["resolution"] == "cancelled"


@solver
def _generates_beside_a_waiting_task() -> Solver:
    # makes one model call while another task of the sample is in `sample_wait`
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        waiting = anyio.Event()
        done = anyio.Event()

        async def waits() -> None:
            with sample_wait():
                waiting.set()
                await done.wait()

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(waits)
            # the other task is waiting before the model call begins
            await waiting.wait()
            state.output = await get_model().generate(state.messages)
            done.set()
        return state

    return solve


@pytest.mark.parametrize(
    "pending_reviews_lost,holds",
    [
        # The provider's client returns the sidecar's "pending review" error
        # without raising it, so Inspect fetches the judged reply after the
        # attempt's own block has ended.
        (0, [(0.0, 0.0), (1.0, 0.0)]),
        # Every try of the first send loses its connection, so the client
        # raises, and Inspect fetches the judged reply inside the attempt's block.
        (10, [(1.0, 0.0)]),
    ],
    ids=["its error returned", "its error raised"],
)
def test_a_send_after_a_review_is_the_models_time_while_another_task_waits(
    pending_reviews_lost: int,
    holds: list[tuple[float, float]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # the fetch of the judged reply takes a second
    stand_in = ReviewingSidecar(
        pauses=["tool_call"],
        turns=[Turn(text="Sunny.")],
        pending_reviews_lost=pending_reviews_lost,
        holds=list(holds),
    )

    sample = _sample(_run(stand_in, solver=_generates_beside_a_waiting_task()))

    # That second counts as working time, for the sample and for the model
    # event, even though another task of the sample was waiting throughout.
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

    # the log has the question's record once, with the call's id and the
    # number of the try that asked
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
    # the step that asked names the question's id, which links the two
    [step] = [e for e in sample.events if isinstance(e, SentinelEvent)]
    assert step.metadata is not None
    assert step.metadata["sentinel_sidecar"]["reviews"] == [review["id"]]
    # the person's answer was used, so no warning says otherwise
    assert not [w for w in _warned(sample) if "wasn't used" in w]


def test_a_person_whose_answer_came_too_late_is_warned_it_wasnt_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn()], expires=True
    )

    sample = _sample(_run(stand_in))

    # The warning tells the person that their answer wasn't used, why, how
    # long before their answer the question closed, and how the call ended.
    [told] = [w for w in _warned(sample) if "wasn't used" in w]
    assert "A person's answer (approve)" in told and "the call to weather" in told
    assert "the question had timed out" in told
    assert "about 12 minutes before the answer" in told
    assert "The call was rejected." in told
    # The log also has the record of the question that timed out, though
    # the judgment has no step for it.
    [logged] = _reviews_logged(sample)
    assert logged["review"]["resolution"] == "timed_out"
    assert "decision" not in logged["review"]
    # the call ended as the sidecar decided, not as the person chose
    assert _LOOKED_UP == []
    assert stand_in.judged_reply_requests == []


def test_a_prompt_nobody_answers_is_withdrawn_once_the_sidecar_closes_its_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the person never answers, so only the sidecar closing the question can
    # end the wait
    person = Person("approve", takes=math.inf)
    person.install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn()], closes_while_shown=True
    )

    log = _run(stand_in)

    # The sample went on with what the sidecar decided. The person was shown
    # the question once, and no answer was sent for them.
    assert log.status == "success"
    assert len(person.asked) == 1
    assert _called(stand_in, "answer_question") == []
    sample = _sample(log)
    assert [w for w in _warned(sample) if "wasn't used" in w] == []
    [logged] = _reviews_logged(sample)
    assert logged["review"]["resolution"] == "timed_out"


def test_a_check_that_fails_leaves_the_prompt_open_and_the_persons_answer_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(review_module, "OPEN_CHECK_RETRY_PAUSE", 0.01)
    lost = 3
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn()], open_checks_lost=lost
    )

    async def every_check_has_failed() -> None:
        while stand_in.open_checks_lost > 0:
            await anyio.sleep(0.01)

    # the person answers only once every failing check has failed
    Person("approve", meanwhile=every_check_has_failed).install(monkeypatch)

    log = _run(stand_in)

    assert log.status == "success"
    [answer] = _called(stand_in, "answer_question")
    assert answer["decision"] == "approve"


def test_a_person_is_warned_when_the_sidecar_cant_say_whether_their_answer_was_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn()], records_dropped=True
    )

    sample = _sample(_run(stand_in, fail_on_error=False))

    # the warning says Inspect couldn't learn whether the answer was used,
    # and doesn't claim that it wasn't
    [told] = [w for w in _warned(sample) if "couldn't learn whether" in w]
    assert "a person's answer (approve)" in told and "dropped" in told
    assert not [w for w in _warned(sample) if "wasn't used" in w]
    assert _reviews_logged(sample) == []


def test_a_pending_review_lost_on_the_way_is_found_and_not_asked_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person = Person("approve")
    person.install(monkeypatch)
    # Every try of the paused call loses its connection before the sidecar's
    # "pending review" arrives. So Inspect is left with a connection error,
    # which it would retry.
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn()], pending_reviews_lost=10
    )

    sample = _sample(_run(stand_in))

    # Inspect looks the call up before it retries. So the person is asked
    # once, Inspect fetches the judged reply under the call's own id, and no
    # retry reaches the sidecar as a new model call.
    assert sample.error is None
    assert len(person.asked) == 1
    [fetch] = stand_in.judged_reply_requests
    first = stand_in.model_calls[0]
    assert fetch.headers["x-irid"] == first.headers["x-irid"]
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
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO], pending_reviews_lost=10
    )
    cancelled_before_the_sample_ended: list[list[str]] = []

    @solver
    def gives_up_on_one_call() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            # the solver gives up on the call while the person is still
            # deciding, and the sample continues
            with anyio.move_on_after(5):
                await generate(state)
            cancelled_before_the_sample_ended.append(list(stand_in.cancelled))
            return state

        return solve

    _run(stand_in, solver=gives_up_on_one_call())

    # Inspect cancels the call at the sidecar as soon as the solver gives up
    # on it, without waiting for the sample to end
    first = stand_in.model_calls[0]
    assert cancelled_before_the_sample_ended == [[first.headers["x-irid"]]]


def _registration_fills(stand_in: ReviewingSidecar) -> Callable[[], None]:
    # The task is registered with the sidecar again, as when another of the
    # task's models is found there, and other samples fill the registration.
    # So the sidecar won't take the sample's registration again, which the
    # next try of a request finds as it is sent.
    full = [False]

    def complete(_: dict[str, Any]) -> dict[str, Any]:
        if full[0]:
            return {"error": {"code": -32008, "message": "the registrations are full"}}
        return {}

    def fill() -> None:
        sidecars = task_sidecars(stand_in.calls[0]["params"]["eval_id"])
        assert sidecars is not None
        access = sidecars.access("http://proxy.test")
        assert access is not None
        access.registrations_begun += 1
        full[0] = True

    stand_in.methods["complete_registration"] = complete
    return fill


def test_nobody_is_asked_about_a_call_whose_samples_registration_stopped_its_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person = Person("terminate")
    person.install(monkeypatch)
    # The first try's "pending review" is lost with its connection, and the
    # registration fills before the provider's SDK tries again.
    stand_in = ReviewingSidecar(
        pauses=["model_input"],
        turns=[Turn()],
        pending_reviews_lost=1,
        judge_usage={"input_tokens": 1000, "output_tokens": 0, "total_tokens": 1000},
    )
    stand_in.when_pending_review_lost = _registration_fills(stand_in)

    log = _run(stand_in, solver=generate(), sentinel_proxy="required")

    # The call fails on the registration's error whatever a person answers,
    # so nobody is asked: an answer of "terminate" would have ended the
    # sample with no error. The paused call is cancelled at the sidecar, and
    # what judging its first try cost is still counted.
    assert log.samples is not None
    sample = log.samples[0]
    assert person.asked == []
    assert sample.error is not None
    assert "the registrations are full" in sample.error.message
    [sent] = stand_in.model_calls
    assert stand_in.cancelled == [sent.headers["x-irid"]]
    assert sample.model_usage["mockllm/judge"].total_tokens == 1000


@pytest.mark.parametrize("lookups_refused", [1, 10], ids=["once", "every time"])
def test_a_cancelled_calls_judging_usage_is_asked_for_once_more_or_noted_as_unknown(
    lookups_refused: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    person = Person("terminate")
    person.install(monkeypatch)
    # As above, and the sidecar then answers with an error when asked what
    # judging the call billed.
    stand_in = ReviewingSidecar(
        pauses=["model_input"],
        turns=[Turn()],
        pending_reviews_lost=1,
        lookups_refused=lookups_refused,
        judge_usage={"input_tokens": 1000, "output_tokens": 0, "total_tokens": 1000},
    )
    stand_in.when_pending_review_lost = _registration_fills(stand_in)

    log = _run(stand_in, solver=generate(), sentinel_proxy="required")

    # The call is cancelled all the same, and fails on the registration's
    # error. Its usage is asked for once more: it is counted if the sidecar
    # then says, and noted as unknown if not.
    assert log.samples is not None
    sample = log.samples[0]
    assert person.asked == []
    assert sample.error is not None
    assert "the registrations are full" in sample.error.message
    [sent] = stand_in.model_calls
    assert stand_in.cancelled == [sent.headers["x-irid"]]
    assert len(_called(stand_in, "request_result")) == 2
    unknown = [
        e
        for e in sample.events
        if isinstance(e, InfoEvent)
        and isinstance(e.data, dict)
        and e.data.get("judging_usage") == "unavailable"
    ]
    if lookups_refused == 1:
        assert sample.model_usage["mockllm/judge"].total_tokens == 1000
        assert unknown == []
    else:
        assert "mockllm/judge" not in sample.model_usage
        assert len(unknown) == 1


@pytest.mark.parametrize(
    ("busy_lookups", "judging_lookups"),
    [(1_000_000, 0), (1, 1_000_000)],
    ids=["the provider is slow to reply", "the sidecar is slow to judge the reply"],
)
def test_a_resent_call_isnt_waited_on_once_its_samples_registration_stops_a_retry(
    busy_lookups: int, judging_lookups: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    Person("approve").install(monkeypatch)
    # The approved request is resent and reaches the provider, and the
    # resend's connection is lost. The registration fills before the
    # provider's SDK tries again.
    stand_in = ReviewingSidecar(
        pauses=["model_input"],
        turns=[Turn()],
        provider_busy_lookups=busy_lookups,
        judging_lookups=judging_lookups,
    )
    stand_in.when_resend_lost = _registration_fills(stand_in)

    log = _run(stand_in, solver=generate(), sentinel_proxy="required", time_limit=20)

    # Asked, the sidecar would go on saying it awaits the reply, or is
    # judging it. The call fails on the registration's error all the same,
    # and is cancelled, and the sample doesn't run out its time waiting.
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.limit is None
    assert sample.error is not None
    assert "the registrations are full" in sample.error.message
    assert stand_in.cancelled == [stand_in.model_calls[0].headers["x-irid"]]


def test_a_resent_calls_usage_that_cant_be_read_once_its_retry_is_stopped_is_noted_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["model_input"],
        turns=[Turn()],
        provider_busy_lookups=1,
        judge_usage={"input_tokens": 1000, "output_tokens": 0, "total_tokens": 1000},
    )
    fill = _registration_fills(stand_in)

    def fills_and_stops_answering() -> None:
        # The approved request is resent, and may be judged again. Its
        # connection is lost, the registration fills before the provider's
        # SDK tries again, and the sidecar can't then say what the call billed.
        fill()
        stand_in.lookups_refused = 10

    stand_in.when_resend_lost = fills_and_stops_answering

    log = _run(stand_in, solver=generate(), sentinel_proxy="required")

    # What was read while the person was asked is kept, and the rest is
    # noted as missing rather than read as none.
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.error is not None
    assert "the registrations are full" in sample.error.message
    assert sample.model_usage["mockllm/judge"].total_tokens == 1000
    paused_id = stand_in.model_calls[0].headers["x-irid"]
    assert [
        e.data
        for e in sample.events
        if isinstance(e, InfoEvent)
        and isinstance(e.data, dict)
        and "judging_usage" in e.data
    ] == [
        {
            "request": paused_id,
            "judging_usage": "incomplete",
            "reason": "the sidecar didn't answer",
        }
    ]


@pytest.mark.parametrize("stopped", ["the resend", "Inspect's retry"])
def test_a_paused_call_whose_samples_registration_stops_it_is_cancelled_at_once(
    stopped: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stand_in = ReviewingSidecar(
        pauses=["model_input"],
        turns=[Turn()],
        # Inspect retries a "pending review" it lost, having asked the person
        pending_reviews_lost=1 if stopped == "Inspect's retry" else 0,
    )
    fill = _registration_fills(stand_in)

    async def fills_meanwhile() -> None:
        fill()

    # the registration fills while the person decides, and they approve
    Person("approve", meanwhile=fills_meanwhile).install(monkeypatch)
    monkeypatch.setattr(AnthropicAPI, "retry_wait", lambda self: wait_none())
    cancelled_as_the_call_ended: list[list[str]] = []

    @solver
    def calls_once() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            try:
                return await generate(state)
            finally:
                cancelled_as_the_call_ended.append(list(stand_in.cancelled))

        return solve

    task = Task(dataset=[Sample(input="Hi.")], solver=calls_once())
    # with no retries in the provider's SDK, Inspect retries the call itself
    retries: dict[str, Any] = {"max_retries": 0} if stopped == "Inspect's retry" else {}
    model = get_model(
        "anthropic/claude-haiku-4-5",
        base_url="http://proxy.test",
        api_key="test-key",
        memoize=False,
        http_client=stand_in.http_client(),
        **retries,
    )

    [log] = inspect_eval(task, model=model, sentinel_proxy="required", display="none")

    # The approved request is never sent on. The sidecar is told at once,
    # as the call fails, and not only when the sample ends.
    assert log.samples is not None
    error = log.samples[0].error
    assert error is not None and "the registrations are full" in error.message
    [sent] = stand_in.model_calls
    assert cancelled_as_the_call_ended == [[sent.headers["x-irid"]]]


def _restarts_and_another_sample_registers(
    stand_in: ReviewingSidecar,
) -> Callable[[], Awaitable[None]]:
    # The sidecar restarts while the person decides, and another sample
    # finds it lost and registers the task again. The approved call carries
    # on under its id, and the restarted sidecar's running totals for it
    # start again.
    async def restart() -> None:
        stand_in.tokens.clear()
        for paused in stand_in.paused.values():
            paused.judging_time = 0.0
        received = current_receiving()
        sidecars = task_sidecars()
        assert received is not None and sidecars is not None
        another = sidecars.attempt_registration(
            received.sidecar,
            SampleFacts(
                sample_id=2, sample_description=None, sample_input="Hi.", metadata={}
            ),
            "another_sample",
            1,
        )
        await another.ensure_registered(received.sidecar)

    return restart


@pytest.mark.parametrize("backend", ["asyncio", "trio"], ids=["on asyncio", "on trio"])
def test_a_paused_calls_judging_usage_after_a_sidecar_restart_is_counted_in_full(
    backend: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    # every `request_result` about the call returns the same usage: before
    # the restart, the total of the call's first judging, and after it, the
    # total of its judging since
    stand_in = ReviewingSidecar(
        pauses=["model_input"],
        turns=[Turn()],
        judge_usage={"input_tokens": 1000, "output_tokens": 0, "total_tokens": 1000},
    )
    Person(
        "approve", meanwhile=_restarts_and_another_sample_registers(stand_in)
    ).install(monkeypatch)

    log = _run(stand_in, solver=generate(), sentinel_proxy="required")

    assert log.samples is not None
    judge = log.samples[0].model_usage["mockllm/judge"]
    assert judge.total_tokens == 2000


@pytest.mark.parametrize("backend", ["asyncio", "trio"], ids=["on asyncio", "on trio"])
def test_a_paused_calls_judging_time_after_a_sidecar_restart_counts_as_waiting(
    backend: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    # The sentinel judges the first request for 0.3 seconds before it asks.
    # The restarted sidecar holds the resend 0.5 seconds, 0.4 of them judging.
    stand_in = ReviewingSidecar(
        pauses=["model_input"],
        turns=[Turn(text="Sunny.")],
        holds=[(0.3, 0.3), (0.5, 0.4)],
    )
    Person(
        "approve", meanwhile=_restarts_and_another_sample_registers(stand_in)
    ).install(monkeypatch)

    log = _run(stand_in, solver=generate(), sentinel_proxy="required")

    assert stand_in.holds == []
    assert log.samples is not None
    event = _model_events(log.samples[0])[-1]
    # both sends' judging count as waiting, the resend's from the restarted
    # sidecar's own total
    assert _event_waiting(event) >= 0.3 + 0.4 - 0.05


def test_a_call_whose_replies_keep_being_cut_off_isnt_resent_without_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["tool_result"], cut_off=True)

    sample = _sample(
        _run(stand_in, solver=generate(), fail_on_error=False, time_limit=30)
    )

    # Inspect resends `MAX_RESENDS` times. Then it stops, and the call fails
    # with the last error.
    assert sample.error is not None
    assert len(stand_in.model_calls) == 1 + MAX_RESENDS


def test_a_reviewed_calls_judge_usage_is_counted_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # every `request_result` about the paused call returns the same usage,
    # which is the total for the whole call
    stand_in = ReviewingSidecar(
        pauses=["tool_call"],
        turns=[_OSLO, Turn()],
        judge_usage={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
    )

    sample = _sample(_run(stand_in))

    # Inspect looked the call up more than once, and counted the usage once
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
        # The provider replied before the sentinel asked. The first request
        # is held 1 second, 0.4 of it judging, and the fetch returns at once.
        ("tool_call", [(1.0, 0.4), (0.0, 0.0)], 0.6),
        # The sentinel asked before the provider was called. The first
        # request is held 0.5 seconds, all of it judging. The resend is held
        # 1 second, 0.3 of it judging the reply.
        ("tool_result", [(0.5, 0.5), (1.0, 0.3)], 0.7),
    ],
)
def test_a_reviewed_call_counts_only_the_models_time_in_its_sends(
    stage: str,
    holds: list[tuple[float, float]],
    model_time: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the person takes a second, which is not working time
    Person("approve", takes=1.0).install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=[stage], turns=[_OSLO, Turn()], holds=list(holds)
    )

    sample = _sample(_run(stand_in))

    # each request's time counts as working time, minus the sentinel's
    # judging during it
    assert stand_in.holds == []
    event = _model_events(sample)[0]
    assert event.working_time is not None and event.output.time is not None
    assert event.working_time >= model_time - 0.1
    assert event.output.time == event.working_time
    assert sample.working_time is not None
    assert sample.working_time >= model_time - 0.1
    # The person's second and the sentinel's judging count as waiting, for
    # the event and for the sample.
    judging = sum(judged for _, judged in holds)
    assert _event_waiting(event) >= 1.0 + judging - 0.1
    assert _sample_waiting(sample) >= 1.0 + judging - 0.1


def test_a_reviewed_call_inspect_retries_counts_only_its_own_judging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # Inspect retries at once, so the test needn't wait
    monkeypatch.setattr(AnthropicAPI, "retry_wait", lambda self: wait_none())
    # The sentinel judges the first request for 0.3 seconds before it asks.
    # The provider fails the resend with a 529, and Inspect fetches that
    # error from the sidecar. Inspect then retries the call under the same
    # id. The sidecar passes the retry on, and it is held 0.8 seconds, 0.2 of
    # them judging the reply.
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=529), Turn(text="Sunny.")],
        sdk_retries=False,
        holds=[(0.3, 0.3), (0.0, 0.0), (0.0, 0.0), (0.8, 0.2)],
    )

    sample = _sample(_run(stand_in, solver=generate()))

    # The retry's working time is its own. The earlier 0.3 seconds of
    # judging already counted as waiting in the attempt they belong to.
    assert stand_in.holds == []
    assert sample.output.completion == "Sunny."
    event = _model_events(sample)[-1]
    assert event.working_time is not None
    # 0.6 seconds of the retry are working time. The 0.3 seconds of judging
    # from the earlier attempt are not subtracted a second time.
    assert event.working_time >= 0.5
    # the retry's own 0.2 seconds of judging count as waiting
    assert _event_waiting(event) >= 0.2 - 0.05


def test_a_reviewed_call_that_fails_counts_only_the_models_time_in_its_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # After the person approves, Inspect resends. The provider answers 529,
    # and the provider's SDK retries after its own wait. That retry is held
    # 0.3 seconds, and the provider answers 403. Inspect fetches the 403 from
    # the sidecar, and the sample fails with it.
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=529), Turn(status=403)],
        holds=[(0.3, 0.3), (0.0, 0.0), (0.3, 0.0), (0.0, 0.0)],
    )

    log = _run(stand_in, solver=generate(), fail_on_error=False)

    sample = _sample(log)
    assert sample.error is not None and "403" in sample.error.message
    assert stand_in.holds == []
    # The try that got the 403 was held 0.3 seconds, which is working time.
    # The sentinel's 0.3 seconds of judging on the first request, and the
    # SDK's wait of at least 0.375 seconds before its retry, count as waiting
    # even though the call failed. Waiting is the sample's total time minus
    # its working time, because a slow machine adds the same amount to both.
    assert sample.working_time is not None
    assert sample.working_time >= 0.2
    assert _sample_waiting(sample) >= 0.6


def test_a_rejected_call_counts_only_the_models_time_before_the_person(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Every try of the paused call loses its connection before the sidecar's
    # "pending review" arrives. The person takes a second to reject the call,
    # so Inspect neither fetches nor resends.
    Person("reject", takes=1.0).install(monkeypatch)
    stand_in = ReviewingSidecar(
        pauses=["tool_call"], turns=[_OSLO, Turn()], pending_reviews_lost=10
    )

    sample = _sample(_run(stand_in))

    # The call's working time is the time of its lost tries. The person's
    # second is not in it, for the event or for the sample. The SDK's waits
    # between tries also count as waiting, so the assertions below look for
    # the person's second on top of those waits.
    assert stand_in.judged_reply_requests == []
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
        # The timer starts when the stand-in begins to hold the request. So
        # the sample ends one second into the hold, however long the sample
        # took to get there.
        active = sample_active()
        assert active is not None
        asyncio.get_running_loop().call_later(1.0, active.interrupt, "score")

    # Every try of the paused call loses its connection before the sidecar's
    # "pending review" arrives. Once the person approves, the stand-in holds
    # the fetch of the judged reply until the sample ends.
    stand_in = ReviewingSidecar(
        pauses=["tool_call"],
        turns=[_OSLO, Turn()],
        pending_reviews_lost=10,
        holds=[(30.0, 0.0)],
        when_held=end_the_sample_in_a_second,
    )

    log = _run(stand_in)

    assert log.samples is not None
    [sample] = log.samples
    [fetch] = stand_in.judged_reply_requests
    # The stand-in held the fetch from its arrival until the sample's end cut
    # it short. Inspect was inside a send for all of that time, so it counts
    # as working time.
    [held] = stand_in.held_requests
    assert not held.finished
    assert held.ended - held.began >= 0.9
    assert sample.working_time is not None
    assert sample.working_time >= (held.ended - held.began) - 0.1


def test_a_resend_waits_for_an_operators_hard_pause(
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

    # Inspect sent the resend only after the process was resumed
    assert sample.output.completion == "Sunny."
    assert not process_paused()
    [_, resend_at] = stand_in.held_at
    assert resend_at - paused_at[0] >= 0.4


# --- a call's timeout ---------------------------------------------------------


def test_the_time_a_person_takes_isnt_counted_toward_the_calls_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the person takes longer than the call's whole timeout
    Person("approve", takes=1.5).install(monkeypatch)
    # Inspect retries at once, so the test needn't wait
    monkeypatch.setattr(AnthropicAPI, "retry_wait", lambda self: wait_none())
    # the provider fails the resend with a 529, then answers the retry
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(status=529), Turn(text="Sunny.")],
        sdk_retries=False,
    )

    sample = _sample(_run(stand_in, solver=generate(), timeout=1))

    # Inspect retries the provider's failure, as it would if no person had
    # been asked
    assert sample.output.completion == "Sunny."


def test_inspect_waits_for_the_reply_to_a_try_that_timed_out_while_the_provider_worked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The person takes 2.5 seconds, and Inspect's attempt at the resend times
    # out a second later. That is more than the call's timeout of 3 seconds
    # if the person's time counts, and well within it if not.
    Person("approve", takes=2.5).install(monkeypatch)
    monkeypatch.setattr(lookup_module, "AWAITED_REPLY_PAUSE", 0.01)
    monkeypatch.setattr(lookup_module, "AWAITED_REPLY_PAUSE_MAX", 0.01)
    # `request_result` returns `awaiting_reply` 25 times while the provider works
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(text="Sunny.")],
        provider_busy_lookups=25,
    )

    sample = _sample(_run(stand_in, solver=generate(), timeout=3, attempt_timeout=1))

    # Inspect kept calling `request_result` until the provider had replied,
    # then fetched the reply from the sidecar. It did not resend meanwhile.
    assert sample.output.completion == "Sunny."
    assert len(stand_in.model_calls) == 2
    assert len(stand_in.judged_reply_requests) == 1
    assert stand_in.cancelled == []


def test_a_call_that_times_out_while_the_provider_works_is_cancelled_at_the_sidecar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    # the provider never answers the resend
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(text="Sunny.")],
        provider_busy_lookups=1_000_000,
    )

    # The sample's time limit is a safety net. If the call outlived its
    # timeout, the limit would end it, so the test would fail and not hang.
    log = _run(
        stand_in,
        solver=generate(),
        fail_on_error=False,
        timeout=2,
        attempt_timeout=1,
        time_limit=30,
    )

    # The call fails when its timeout passes, and not before. Its own
    # timeout ends it, not the sample's limit. Inspect then cancels the call
    # at the sidecar.
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
    # The provider never answers. The sidecar answers the first
    # `request_result` at once, and takes ten seconds over the second.
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(text="Sunny.")],
        provider_busy_lookups=1_000_000,
        lookup_durations=[0.0, 10.0],
    )

    log = _run(
        stand_in,
        solver=generate(),
        fail_on_error=False,
        timeout=2,
        attempt_timeout=1,
        time_limit=30,
    )

    # The call fails when its timeout passes, and not before. Inspect
    # abandons the ten-second lookup without waiting for it, and cancels the
    # call at the sidecar.
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
    # Inspect waits five seconds between lookups, or until the call's
    # timeout passes if that is sooner. The provider replies during the wait,
    # which only another lookup would show.
    monkeypatch.setattr(lookup_module, "AWAITED_REPLY_PAUSE", 5.0)
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(text="Sunny.")],
        provider_busy_lookups=2,
    )

    log = _run(
        stand_in,
        solver=generate(),
        fail_on_error=False,
        timeout=2,
        attempt_timeout=1,
    )

    # the call's timeout has passed, so it fails without another lookup,
    # and Inspect cancels it at the sidecar
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
    # The provider replies within the call's timeout of 2 seconds. The
    # sidecar then returns `judging` for six lookups, half a second apart,
    # so the judging ends after the timeout has passed.
    stand_in = ReviewingSidecar(
        pauses=["tool_result"],
        turns=[Turn(text="Sunny.")],
        provider_busy_lookups=2,
        judging_lookups=6,
    )

    began = time.monotonic()
    sample = _sample(_run(stand_in, solver=generate(), timeout=2, attempt_timeout=1))

    # judging a reply has no deadline, for this call as for any other, so
    # the call is decided and not cancelled
    assert time.monotonic() - began > 2
    assert sample.output.completion == "Sunny."
    assert stand_in.cancelled == []


async def test_a_second_question_after_the_providers_reply_isnt_bound_by_the_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lookup_module, "AWAITED_REPLY_PAUSE", 0.01)
    monkeypatch.setattr(review_module, "NO_QUESTION_PAUSE", 0.01)
    # The state each `request_result` returns, in order. First the provider
    # still has the request. Then a second question is open; Inspect never
    # saw the `judging` state between the two. Then the call is decided.
    states = ["awaiting_reply", "awaiting_review", "decided"]
    cancelled: list[str] = []

    class Sidecar:
        origin = "http://proxy.test"
        review = True

        async def eval_call(self, method: str, params: dict[str, Any]) -> Any:
            if method == "list_pending_questions":
                # the call's timeout passes while Inspect handles the question
                await anyio.sleep(0.6)
                return {"questions": []}
            if method == "cancel_paused_request":
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
        # a paused call with half of its timeout left
        received.request_id = received.reviewed_request_id = "request_1"
        received.sent = received.paused = True
        received.began = time.monotonic() - 0.5
        looked = await lookup_module.request_result(received, replied=False)

    # The provider had replied, so the timeout no longer applies. Inspect
    # reads the call as decided and doesn't cancel it.
    assert looked.state == "decided"
    assert cancelled == []


# --- a call Inspect gives up on -----------------------------------------------


def test_a_call_whose_review_fails_is_cancelled_at_once_with_its_question_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Person("approve").install(monkeypatch)
    stand_in = ReviewingSidecar(pauses=["tool_call"], turns=[_OSLO])
    listed = stand_in._list_pending_questions

    def only_modify(params: dict[str, Any]) -> dict[str, Any]:
        # a question whose only choice is one Inspect can't offer a person
        questions = listed(params)
        for question in questions["questions"]:
            question["choices"] = ["modify"]
        return questions

    stand_in.methods["list_pending_questions"] = only_modify

    log = _run(stand_in, solver=generate(), fail_on_error=False)

    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None
    # Inspect cancels the call at the sidecar when the review fails, not
    # when the sample ends. So the question's record is in the sample's log.
    [first] = stand_in.model_calls
    assert stand_in.cancelled == [first.headers["x-irid"]]
    [logged] = _reviews_logged(sample)
    assert logged["review"]["resolution"] == "cancelled"
    assert review_module._paused_calls == {}


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
    # the call's model event is no longer pending
    [event] = _model_events(sample)
    assert event.pending is None
    assert review_module._paused_calls == {}
    # the log has the record of the question that the cancellation closed
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
            assert method == "cancel_paused_request"
            cancelled.append(params["id"])
            return {"id": params["id"], "cancelled": True}

    async def send_again() -> ModelOutput:
        raise AssertionError("nothing is sent for a call still being judged")

    async def call(received: ReceivedCall) -> None:
        # a paused call that the sentinel is still judging
        received.request_id = received.reviewed_request_id = "request_1"
        received.sent = received.paused = True
        waiting.set()
        await refused_output("model", lambda: False, lambda: False, send_again)

    with receiving_call(Sidecar()) as received:
        async with anyio.create_task_group() as tg:
            tg.start_soon(call, received)
            await waiting.wait()
            await anyio.sleep(0.05)
            tg.cancel_scope.cancel()

    assert cancelled == ["request_1"]
    assert received.paused is False


def test_a_request_is_sent_to_the_judged_reply_path_only_for_its_own_call() -> None:
    def request(irid: str, body: bytes = b"{}") -> httpx2.Request:
        return httpx2.Request(
            "POST",
            "http://proxy.test/v1/messages?beta=true",
            headers={"x-irid": irid},
            content=body,
        )

    with receiving_call() as received:
        received.reviewed_request_id = "request_1"
        # the hook leaves the path alone while no fetch is under way
        sent = request("request_1")
        route_fetch_to_sidecar(sent)
        assert sent.url.path == "/v1/messages"

        received.fetching = True
        other = request("request_2")
        route_fetch_to_sidecar(other)
        assert other.url.path == "/v1/messages"

        # the hook replaces the path, and keeps the origin and the query
        first = request("request_1")
        route_fetch_to_sidecar(first)
        assert str(first.url) == f"http://proxy.test{JUDGED_REPLY_PATH}?beta=true"
        # The SDK's retry has the same body, so it goes to the judged-reply
        # path too. A continuation has a different body, so it goes to the
        # model.
        retry, continuation = request("request_1"), request("request_1", b'{"m":1}')
        route_fetch_to_sidecar(retry)
        route_fetch_to_sidecar(continuation)
        assert retry.url.path == JUDGED_REPLY_PATH
        assert continuation.url.path == "/v1/messages"
