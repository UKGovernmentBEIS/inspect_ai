import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest
from test_helpers.stand_in_sidecar import StandInSidecar, Turn

from inspect_ai import Task, eval
from inspect_ai._sentinel._sidecar._endpoint import (
    SentinelProxyError,
    Sidecar,
    probe,
    proxy_client,
)
from inspect_ai._sentinel._sidecar._field import receiving_field
from inspect_ai._sentinel._sidecar._task import SampleFacts, TaskFacts, TaskSidecars
from inspect_ai._util._async import tg_collect
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.agent import react
from inspect_ai.agent._bridge.util import bridge_model_generate
from inspect_ai.approval import Approval, ApprovalPolicy, Approver, approver
from inspect_ai.dataset import Sample
from inspect_ai.event import InfoEvent, SentinelEvent, ToolEvent
from inspect_ai.log import EvalSample
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.scorer import (
    Score,
    Scorer,
    Target,
    mean,
    require_monitor_state,
    score,
    scorer,
)
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver, use_tools
from inspect_ai.tool import Tool, ToolCall, tool

_MODELS = {
    "anthropic": "anthropic/claude-haiku-4-5",
    # no reasoning options, so no side request to check for reasoning summaries
    "openai": "openai/gpt-4.1-mini",
}


@pytest.fixture(autouse=True)
def _nothing_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # no base URL or credential but the test's own reaches the stand-in
    for name in [
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "OPENAI_BASE_URL",
        "INSPECT_EVAL_MODEL_BASE_URL",
    ]:
        monkeypatch.delenv(name, raising=False)


def _model(
    stand_in: StandInSidecar,
    provider: str = "anthropic",
    base_url: str | None = "http://proxy.test",
) -> Model:
    return get_model(
        _MODELS[provider],
        base_url=base_url,
        api_key="test-key",
        memoize=False,
        http_client=stand_in.http_client(),
    )


async def _probed(model: Model) -> Sidecar | str:
    client = proxy_client(model.api)
    assert client is not None
    return await probe(client)


@pytest.mark.parametrize(
    ("provider", "base_url"),
    [("anthropic", "http://proxy.test"), ("openai", "http://proxy.test/v1")],
)
async def test_a_sidecar_behind_the_models_base_url_is_found(
    provider: str, base_url: str
) -> None:
    stand_in = StandInSidecar()

    found = await _probed(_model(stand_in, provider, base_url))

    assert isinstance(found, Sidecar)
    assert (found.origin, found.release) == ("http://proxy.test", "whole")
    # at the proxy's root, not on the end of an OpenAI base URL, and with the
    # credentials the model's calls carry
    [asked] = stand_in.probes
    assert str(asked.url) == "http://proxy.test/sentinel/info"
    assert asked.headers["authorization"] == "Bearer test-key"


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_a_model_whose_base_url_was_not_set_is_not_probed(provider: str) -> None:
    stand_in = StandInSidecar()

    assert proxy_client(_model(stand_in, provider, base_url=None).api) is None


@pytest.mark.parametrize(
    ("provider", "variable"),
    [("anthropic", "ANTHROPIC_BASE_URL"), ("openai", "OPENAI_BASE_URL")],
)
async def test_a_base_url_set_in_the_environment_is_probed(
    monkeypatch: pytest.MonkeyPatch, provider: str, variable: str
) -> None:
    monkeypatch.setenv(variable, "http://proxy.test")
    stand_in = StandInSidecar()

    found = await _probed(_model(stand_in, provider, base_url=None))

    assert isinstance(found, Sidecar)


@pytest.mark.parametrize(
    ("stand_in", "says"),
    [
        (StandInSidecar(info=None), "has no sidecar"),
        (StandInSidecar(info={"models": []}), "not as a sidecar"),
        (StandInSidecar(probe_status=401), "failed"),
        (StandInSidecar(probe_status=503), "failed"),
    ],
    ids=["404", "not a sidecar", "401", "503"],
)
async def test_an_answer_that_isnt_a_sidecar_finds_none(
    stand_in: StandInSidecar, says: str
) -> None:
    found = await _probed(_model(stand_in))

    assert isinstance(found, str)
    assert says in found


@pytest.mark.parametrize(
    ("info", "says"),
    [
        ({"service": "inspect_sentinel", "versions": [2]}, r"serves versions \[2\]"),
        (
            {"service": "inspect_sentinel", "versions": [1], "release": "early"},
            "releases replies early",
        ),
    ],
    ids=["an unknown version", "early release"],
)
async def test_a_sidecar_inspect_cant_work_with_is_an_error(
    info: dict[str, Any], says: str
) -> None:
    with pytest.raises(SentinelProxyError, match=says):
        await _probed(_model(StandInSidecar(info=info)))


async def test_a_task_that_requires_a_sidecar_fails_without_one() -> None:
    sidecars = TaskSidecars("required", _FACTS)

    with pytest.raises(SentinelProxyError, match="has no sidecar"):
        await sidecars.start(_model(StandInSidecar(info=None)))


async def test_a_task_that_requires_a_sidecar_fails_for_a_model_never_probed() -> None:
    sidecars = TaskSidecars("required", _FACTS)

    with pytest.raises(SentinelProxyError, match="base URL was not set"):
        await sidecars.start(_model(StandInSidecar(), base_url=None))


async def test_an_endpoint_is_probed_once_for_samples_asking_at_once() -> None:
    stand_in = StandInSidecar()
    model = _model(stand_in)
    sidecars = TaskSidecars("auto", _FACTS)

    found = await tg_collect([lambda: sidecars.sidecar(model.api)] * 5)

    assert all(isinstance(sidecar, Sidecar) for sidecar in found)
    assert len(stand_in.probes) == 1


@solver
def _nothing() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return state

    return solve


def _task() -> Task:
    return Task(dataset=[Sample(input="Hi.")], solver=_nothing())


def test_an_eval_that_requires_a_sidecar_fails_its_task_without_one() -> None:
    [log] = eval(
        _task(),
        model=_model(StandInSidecar(info=None)),
        sentinel_proxy="required",
        display="none",
    )

    assert log.status == "error"
    assert log.error is not None
    assert "A sentinel sidecar is required" in log.error.message
    assert log.eval.config.sentinel_proxy == "required"


@pytest.mark.parametrize("sentinel_proxy", ["auto", None])
def test_an_eval_finds_a_sidecar_unless_told_not_to(
    sentinel_proxy: Any,
) -> None:
    stand_in = StandInSidecar()

    [log] = eval(
        _task(), model=_model(stand_in), sentinel_proxy=sentinel_proxy, display="none"
    )

    assert log.status == "success"
    assert len(stand_in.probes) == 1


def test_an_eval_told_not_to_look_never_probes() -> None:
    stand_in = StandInSidecar()

    [log] = eval(_task(), model=_model(stand_in), sentinel_proxy="off", display="none")

    assert log.status == "success"
    assert stand_in.probes == []


def _registered(stand_in: StandInSidecar, method: str) -> list[dict[str, Any]]:
    return [call["params"] for call in stand_in.calls if call["method"] == method]


def test_an_eval_registers_its_task_with_the_sidecar_it_finds() -> None:
    stand_in = StandInSidecar()
    task = Task(
        dataset=[Sample(input="Hi.", id="a"), Sample(input="Bye.", id="b")],
        solver=_nothing(),
        metadata={"desk": "weather"},
        name="weather_desk",
    )

    [log] = eval(task, model=_model(stand_in), sample_id="a", epochs=2, display="none")

    assert log.status == "success"
    # the selected samples' ids and the epochs, and no sample's facts, which
    # are sent before each sample runs
    assert _registered(stand_in, "register_task") == [
        {
            "eval_id": log.eval.eval_id,
            "task": "weather_desk",
            "task_description": None,
            "metadata": {"desk": "weather"},
            "sample_ids": ["a"],
            "epochs": 2,
        }
    ]


@pytest.mark.parametrize(
    ("error", "says"),
    [
        (
            {"code": -32001, "message": "no runtime registration"},
            "runs only the tasks its admin registered",
        ),
        (
            {"code": -32008, "message": "already keeps the 1000 tasks"},
            "couldn't register the task",
        ),
    ],
    ids=["refused", "full"],
)
def test_a_task_the_sidecar_wont_register_fails(
    error: dict[str, Any], says: str
) -> None:
    stand_in = StandInSidecar(methods={"register_task": lambda _: {"error": error}})

    [log] = eval(_task(), model=_model(stand_in), display="none")

    assert log.status == "error"
    assert log.error is not None
    assert says in log.error.message
    # under `auto` too: a sidecar was found, so the task needs it
    assert log.eval.config.sentinel_proxy is None


def _sample(sample_id: str | int = 1) -> SampleFacts:
    return SampleFacts(
        sample_id=sample_id,
        sample_description="A rainy day.",
        sample_input=[ChatMessageUser(content="File the report.")],
        metadata={"city": "Philadelphia"},
    )


_FACTS = TaskFacts(
    eval_id="eval_789",
    task="weather_desk",
    task_description=None,
    metadata={},
    sample_ids=[1],
    epochs=2,
)


async def test_a_samples_registration_is_completed_once_for_all_its_epochs() -> None:
    stand_in = StandInSidecar()
    sidecars = TaskSidecars("auto", _FACTS)
    sidecar = await sidecars.sidecar(_model(stand_in).api)
    assert sidecar is not None

    # each epoch's first call, at once
    await tg_collect([lambda: sidecars.complete_registration(sidecar, _sample())] * 3)

    [completed] = _registered(stand_in, "complete_registration")
    messages = completed.pop("sample_input")
    assert completed == {
        "eval_id": "eval_789",
        "task": "weather_desk",
        "sample_id": 1,
        "sample_description": "A rainy day.",
        "metadata": {"city": "Philadelphia"},
    }
    # chat messages as inspect_ai writes them
    [message] = messages
    assert (message["role"], message["content"]) == ("user", "File the report.")


async def test_a_sample_the_sidecar_wont_take_is_an_error() -> None:
    stand_in = StandInSidecar(
        methods={
            "complete_registration": lambda _: {
                "error": {"code": -32009, "message": "no registration"}
            }
        }
    )
    sidecars = TaskSidecars("auto", _FACTS)
    sidecar = await sidecars.sidecar(_model(stand_in).api)
    assert sidecar is not None

    with pytest.raises(SentinelProxyError, match="couldn't register the sample 1"):
        await sidecars.complete_registration(sidecar, _sample())


async def test_a_sidecar_found_after_the_task_started_is_registered_once() -> None:
    stand_in = StandInSidecar()
    sidecars = TaskSidecars("auto", _FACTS)
    model = _model(stand_in)

    await tg_collect([lambda: sidecars.sidecar(model.api)] * 3)

    assert len(_registered(stand_in, "register_task")) == 1


def _context(request: httpx2.Request) -> dict[str, Any] | None:
    header = request.headers.get("x-inspect-context")
    return json.loads(header) if header is not None else None


@pytest.mark.parametrize(
    ("provider", "base_url"),
    [("anthropic", "http://proxy.test"), ("openai", "http://proxy.test/v1")],
)
def test_an_agent_call_names_its_sample(provider: str, base_url: str) -> None:
    stand_in = StandInSidecar()
    task = Task(
        dataset=[Sample(input="Hi.", id="a")], solver=generate(), name="weather_desk"
    )

    [log] = eval(task, model=_model(stand_in, provider, base_url), display="none")

    assert log.status == "success"
    assert log.samples is not None
    [sample] = log.samples
    [call] = [r for r in stand_in.model_calls if _context(r) is not None]
    context = _context(call)
    assert context is not None
    attempt = context.pop("attempt")
    assert context == {
        "version": 1,
        "eval_id": log.eval.eval_id,
        "task": "weather_desk",
        "sample_id": "a",
        "epoch": 1,
        "sample_uuid": sample.uuid,
    }
    assert attempt
    # the sample's registration was complete before the sidecar saw its call
    completed = [
        i
        for i, r in enumerate(stand_in.requests)
        if r.url.path == "/sentinel/v1"
        and json.loads(r.content)["method"] == "complete_registration"
    ]
    assert completed == [completed[0]]
    assert completed[0] < stand_in.requests.index(call)


@scorer(metrics=[mean()])
def _graded() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        await get_model().generate("Grade it.")
        return Score(value=1)

    return score


def test_only_the_agents_calls_name_their_sample() -> None:
    stand_in = StandInSidecar()
    task = Task(dataset=[Sample(input="Hi.")], solver=generate(), scorer=_graded())

    [log] = eval(task, model=_model(stand_in), display="none")

    assert log.status == "success"
    named = [_context(r) is not None for r in stand_in.model_calls]
    # the agent's turn, then the grader's, which no sidecar judges in process
    assert named == [True, False]


@solver
def _asks_twice() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()
        await model.generate(state.messages, cache=True)
        await model.generate(state.messages, cache=True)
        return state

    return solve


@pytest.mark.parametrize(
    ("sentinel_proxy", "calls"),
    [("auto", 2), ("off", 1)],
    ids=["through a sidecar", "without one"],
)
def test_an_agent_call_through_a_sidecar_is_never_answered_from_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sentinel_proxy: Any, calls: int
) -> None:
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path))
    stand_in = StandInSidecar()
    task = Task(dataset=[Sample(input="Hi.")], solver=_asks_twice())

    [log] = eval(
        task, model=_model(stand_in), sentinel_proxy=sentinel_proxy, display="none"
    )

    assert log.status == "success"
    assert len(stand_in.model_calls) == calls


def test_a_call_to_an_endpoint_with_no_sidecar_names_no_sample() -> None:
    stand_in = StandInSidecar(info=None)
    task = Task(dataset=[Sample(input="Hi.")], solver=generate())

    [log] = eval(task, model=_model(stand_in), display="none")

    assert log.status == "success"
    assert [_context(r) for r in stand_in.model_calls] == [None]
    assert _registered(stand_in, "register_task") == []


_FIELD = {
    "version": 1,
    "outcome": "proceed",
    "steps": [
        {"stage": "tool_call", "call": "call_1", "decision": {"action": "proceed"}}
    ],
}

_FORMATS: dict[str, tuple[str, str, dict[str, Any]]] = {
    "anthropic": ("anthropic", "http://proxy.test", {"streaming": False}),
    "anthropic streamed": ("anthropic", "http://proxy.test", {"streaming": True}),
    "responses": ("openai", "http://proxy.test/v1", {"streaming": False}),
    "responses streamed": ("openai", "http://proxy.test/v1", {"streaming": True}),
    "chat": (
        "openai",
        "http://proxy.test/v1",
        {"streaming": False, "responses_api": False},
    ),
    "chat streamed": (
        "openai",
        "http://proxy.test/v1",
        {"streaming": True, "responses_api": False},
    ),
}


async def _received(name: str, turn: Turn) -> dict[str, Any] | None:
    provider, base_url, model_args = _FORMATS[name]
    stand_in = StandInSidecar(turns=[turn])
    model = get_model(
        _MODELS[provider],
        base_url=base_url,
        api_key="test-key",
        memoize=False,
        http_client=stand_in.http_client(),
        **model_args,
    )
    with receiving_field() as received:
        try:
            # few tokens, as the Anthropic SDK refuses a long call it isn't streaming
            await model.generate(
                "Hi.", config=GenerateConfig(max_retries=0, max_tokens=100)
            )
        except Exception:
            pass
    assert len(stand_in.model_calls) == 1
    return received.field


@pytest.mark.parametrize("name", list(_FORMATS))
async def test_the_field_is_read_from_a_reply(name: str) -> None:
    assert await _received(name, Turn(sentinel=_FIELD)) == _FIELD


@pytest.mark.parametrize("name", list(_FORMATS))
async def test_a_reply_without_the_field_has_none(name: str) -> None:
    assert await _received(name, Turn()) is None


@pytest.mark.parametrize("name", list(_FORMATS))
@pytest.mark.parametrize("nested", [False, True], ids=["envoy", "litellm"])
async def test_the_field_is_read_from_a_refusal(name: str, nested: bool) -> None:
    refused = {**_FIELD, "outcome": "reject"}

    received = await _received(name, Turn(status=400, sentinel=refused, nested=nested))

    assert received == refused


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


def _turn_json(*calls: tuple[str, str]) -> dict[str, Any]:
    # the model's turn, as the sidecar writes it in the field
    message = ChatMessageAssistant(
        content="Checking.",
        tool_calls=[
            ToolCall(id=id, function="weather", arguments={"city": city})
            for id, city in calls
        ],
    )
    return message.model_dump(mode="json", exclude_none=True)


def _run_agent(
    stand_in: StandInSidecar,
    approval: list[ApprovalPolicy] | None = None,
    agent: str = "generate",
) -> EvalSample:
    _LOOKED_UP.clear()
    task = Task(
        dataset=[Sample(input="What's the weather?")],
        solver=(
            react(tools=[weather()])
            if agent == "react"
            else [use_tools(weather()), generate()]
        ),
        approval=approval,
    )
    [log] = eval(task, model=_model(stand_in), display="none")
    assert log.status == "success", log.error
    assert log.samples is not None
    return log.samples[0]


def _tool_messages(sample: EvalSample) -> dict[str, ChatMessageTool]:
    return {
        m.tool_call_id: m
        for m in sample.messages
        if isinstance(m, ChatMessageTool) and m.tool_call_id is not None
    }


def _turns(sample: EvalSample) -> list[ChatMessageAssistant]:
    return [m for m in sample.messages if isinstance(m, ChatMessageAssistant)]


def test_a_call_the_sidecar_took_out_is_answered_with_an_approval_error() -> None:
    proposed = {
        "message": _turn_json(("call_1", "Tokyo"), ("call_2", "Oslo")),
        "results": {"call_1": "Tokyo is not allowed."},
    }
    stand_in = StandInSidecar(
        turns=[
            # the sidecar hands over the turn without the rejected call
            Turn(
                calls=[("call_2", "weather", {"city": "Oslo"})],
                sentinel={"outcome": "proceed", "steps": [], "proposed": proposed},
            ),
            Turn(text="Sunny in Oslo."),
        ]
    )

    sample = _run_agent(stand_in)

    # the model's own turn, both calls in it, as in process
    first = _turns(sample)[0]
    assert [c.id for c in first.tool_calls or []] == ["call_1", "call_2"]
    results = _tool_messages(sample)
    assert results["call_1"].error is not None
    assert results["call_1"].error.type == "approval"
    assert results["call_1"].error.message == "Tokyo is not allowed."
    assert results["call_2"].error is None
    assert _LOOKED_UP == ["Oslo"]


def test_a_call_the_sidecar_changed_runs_with_its_new_arguments() -> None:
    original = {"id": "call_1", "function": "weather", "arguments": {"city": "Tokyo"}}
    modified = {"id": "call_1", "function": "weather", "arguments": {"city": "Oslo"}}
    stand_in = StandInSidecar(
        turns=[
            Turn(
                calls=[("call_1", "weather", {"city": "Oslo"})],
                sentinel={
                    "outcome": "proceed",
                    "steps": [
                        {
                            "stage": "tool_call",
                            "call": "call_1",
                            "original": original,
                            "decision": {"action": "modify", "modified": modified},
                        }
                    ],
                },
            ),
            Turn(text="Sunny in Oslo."),
        ]
    )

    sample = _run_agent(stand_in)

    # the model's turn keeps the call it made, and the changed one ran
    [call] = _turns(sample)[0].tool_calls or []
    assert call.arguments == {"city": "Tokyo"}
    assert _LOOKED_UP == ["Oslo"]


def test_a_turn_the_sidecar_rejected_whole_goes_on_as_the_models_turn() -> None:
    withheld = {
        "message": _turn_json(("call_1", "Tokyo")),
        "results": {"call_1": "Tokyo is not allowed."},
    }
    stand_in = StandInSidecar(
        turns=[
            Turn(status=400, sentinel={"outcome": "reject", "withheld": withheld}),
            Turn(text="I can't look that up."),
        ]
    )

    sample = _run_agent(stand_in)

    # the agent carries on, as it would in process
    assert sample.error is None
    [call] = _turns(sample)[0].tool_calls or []
    assert call.id == "call_1"
    error = _tool_messages(sample)["call_1"].error
    assert error is not None
    assert (error.type, error.message) == ("approval", "Tokyo is not allowed.")
    assert _LOOKED_UP == []
    assert _turns(sample)[-1].text == "I can't look that up."


def _ends(stage: str, call: str | None = None) -> dict[str, Any]:
    # a sentinel's terminate, as the field reports it
    return {
        "stage": stage,
        "call": call,
        "decision": {"action": "terminate", "explanation": "Too far."},
    }


def _ended_turn(*calls: tuple[str, str]) -> dict[str, Any]:
    # the turn the run ended at, none of whose calls runs
    return {
        "message": _turn_json(*calls),
        "results": {id: "This call was not run." for id, _ in calls},
    }


def _ended_as_operator(sample: EvalSample, reason: str = "Too far.") -> None:
    assert sample.error is None
    assert sample.limit is not None
    assert (sample.limit.type, sample.limit.reason) == ("operator", reason)


@pytest.mark.parametrize("agent", ["generate", "react"])
def test_a_terminate_at_a_call_ends_the_sample_with_the_turn_kept(agent: str) -> None:
    calls = (("call_1", "Tokyo"), ("call_2", "Oslo"))
    field = {
        "outcome": "terminate",
        "steps": [_ends("tool_call", "call_2")],
        "withheld": _ended_turn(*calls),
    }
    stand_in = StandInSidecar(turns=[Turn(status=400, sentinel=field)])

    sample = _run_agent(stand_in, agent=agent)

    # the turn is the agent's, as an in-process sentinel leaves it, and the
    # sample ends before any of its calls runs
    _ended_as_operator(sample)
    assert [c.id for c in _turns(sample)[-1].tool_calls or []] == ["call_1", "call_2"]
    assert _tool_messages(sample) == {}
    assert _LOOKED_UP == []
    tool_events = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert tool_events
    assert all(e.failed for e in tool_events)


@pytest.mark.parametrize(
    "step",
    [_ends("model_input"), _ends("model_output")],
    ids=["a request", "a reply"],
)
def test_a_terminate_before_the_calls_ends_the_sample_at_the_model_call(
    step: dict[str, Any],
) -> None:
    field: dict[str, Any] = {"outcome": "terminate", "steps": [step]}
    if step["stage"] == "model_output":
        field["withheld"] = _ended_turn(("call_1", "Tokyo"))
    stand_in = StandInSidecar(turns=[Turn(status=400, sentinel=field)])

    sample = _run_agent(stand_in)

    # as in process, the agent is never handed the turn
    _ended_as_operator(sample)
    assert _turns(sample) == []
    assert _LOOKED_UP == []


def test_an_agent_that_doesnt_run_the_turns_calls_ends_at_its_next_call() -> None:
    field = {
        "outcome": "terminate",
        "steps": [_ends("tool_call", "call_1")],
        "withheld": _ended_turn(("call_1", "Tokyo")),
    }
    stand_in = StandInSidecar(
        turns=[
            Turn(status=400, sentinel=field),
            # the sidecar refuses every later call of a run it ended
            Turn(status=400, sentinel={"outcome": "terminate", "steps": []}),
        ]
    )
    task = Task(dataset=[Sample(input="Hi.")], solver=_asks_twice())

    [log] = eval(task, model=_model(stand_in), display="none")

    assert log.samples is not None
    _ended_as_operator(log.samples[0], "A sentinel in the sidecar ended the sample.")


def test_an_approver_never_sees_a_call_the_sidecar_took_out() -> None:
    seen: list[str] = []

    @approver
    def recording() -> Approver:
        async def approve(
            message: str, call: ToolCall, view: Any, history: list[Any]
        ) -> Approval:
            seen.append(call.id)
            return Approval(decision="approve")

        return approve

    proposed = {
        "message": _turn_json(("call_1", "Tokyo"), ("call_2", "Oslo")),
        "results": {"call_1": "Tokyo is not allowed."},
    }
    stand_in = StandInSidecar(
        turns=[
            Turn(
                calls=[("call_2", "weather", {"city": "Oslo"})],
                sentinel={"outcome": "proceed", "steps": [], "proposed": proposed},
            ),
            Turn(text="Done."),
        ]
    )

    _run_agent(stand_in, approval=[ApprovalPolicy(approver=recording(), tools="*")])

    assert seen == ["call_2"]


def _answers(*results: dict[str, Any]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    # `request_result`'s answers in turn, then that the call was never seen
    answers = list(results)

    def answer(params: dict[str, Any]) -> dict[str, Any]:
        found = answers.pop(0) if answers else {"records": "unknown"}
        return {"id": params["id"], **found}

    return answer


def _decided(field: dict[str, Any]) -> dict[str, Any]:
    return {"records": "held", "state": "decided", "sentinel": field}


def _taken_out() -> dict[str, Any]:
    return {
        "outcome": "proceed",
        "steps": [],
        "proposed": {
            "message": _turn_json(("call_1", "Tokyo"), ("call_2", "Oslo")),
            "results": {"call_1": "Tokyo is not allowed."},
        },
    }


def _looked_up(stand_in: StandInSidecar) -> list[str]:
    return [params["id"] for params in _registered(stand_in, "request_result")]


def test_a_reply_without_the_field_is_acted_on_as_request_result_says() -> None:
    stand_in = StandInSidecar(
        turns=[Turn(calls=[("call_2", "weather", {"city": "Oslo"})]), Turn()],
        methods={
            "request_result": _answers(
                {"records": "held", "state": "judging"}, _decided(_taken_out())
            )
        },
    )

    sample = _run_agent(stand_in)

    # asked again while the sidecar was still judging, under the call's id
    first_call = stand_in.model_calls[0]
    assert _looked_up(stand_in)[:2] == [first_call.headers["x-irid"]] * 2
    assert _tool_messages(sample)["call_1"].error is not None
    assert _LOOKED_UP == ["Oslo"]


@pytest.mark.parametrize(
    ("result", "judgment"),
    [
        ({"records": "held", "state": "not_judged", "reason": "error"}, "not judged"),
        ({"records": "unknown"}, "unavailable"),
    ],
    ids=["not judged", "unknown"],
)
def test_a_reply_the_sidecar_didnt_judge_is_used_and_says_so(
    result: dict[str, Any], judgment: str
) -> None:
    stand_in = StandInSidecar(
        turns=[Turn(text="Sunny.")], methods={"request_result": _answers(result)}
    )

    sample = _run_agent(stand_in)

    [info] = [
        e
        for e in sample.events
        if isinstance(e, InfoEvent) and e.source == "sentinel sidecar"
    ]
    assert isinstance(info.data, dict)
    assert info.data["judgment"] == judgment


def test_a_reply_whose_judgment_is_unavailable_fails_a_sample_that_requires_one() -> (
    None
):
    stand_in = StandInSidecar(
        turns=[Turn(text="Sunny.")],
        methods={"request_result": _answers({"records": "dropped"})},
    )
    task = Task(dataset=[Sample(input="Hi.")], solver=generate())

    [log] = eval(
        task, model=_model(stand_in), sentinel_proxy="required", display="none"
    )

    assert log.samples is not None
    error = log.samples[0].error
    assert error is not None
    assert "judgment of the call" in error.message


def test_a_refusal_without_the_field_is_acted_on_as_request_result_says() -> None:
    rejected = {
        "outcome": "reject",
        "withheld": {
            "message": _turn_json(("call_1", "Tokyo")),
            "results": {"call_1": "Tokyo is not allowed."},
        },
    }
    stand_in = StandInSidecar(
        turns=[Turn(status=400), Turn(text="I can't.")],
        methods={"request_result": _answers(_decided(rejected))},
    )

    sample = _run_agent(stand_in)

    assert sample.error is None
    assert _tool_messages(sample)["call_1"].error is not None


def test_a_sample_the_sidecar_cant_place_is_never_retried_or_scored() -> None:
    stand_in = StandInSidecar(
        turns=[Turn(status=400)] * 3,
        methods={
            "request_result": _answers(
                {"records": "held", "state": "not_judged", "reason": "unregistered"}
            )
        },
    )
    task = Task(dataset=[Sample(input="Hi.")], solver=generate(), scorer=_graded())

    [log] = eval(
        task,
        model=_model(stand_in),
        retry_on_error=2,
        score_on_error=True,
        display="none",
    )

    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None
    assert "SampleRefusedError" in sample.error.message
    assert sample.scores is None or sample.scores == {}
    assert len(stand_in.model_calls) == 1


def test_a_refusal_the_sidecar_couldnt_judge_fails_the_sample_with_why() -> None:
    stand_in = StandInSidecar(
        turns=[Turn(status=400)],
        methods={
            "request_result": _answers(
                {"records": "held", "state": "not_judged", "reason": "time_limit"}
            )
        },
    )

    [log] = eval(
        Task(dataset=[Sample(input="Hi.")], solver=generate()),
        model=_model(stand_in),
        display="none",
    )

    assert log.samples is not None
    error = log.samples[0].error
    assert error is not None
    assert "SidecarNotJudgedError" in error.message
    assert "(time_limit)" in error.message


def test_an_error_inspect_retries_is_not_looked_up() -> None:
    stand_in = StandInSidecar(turns=[Turn(status=529)])

    [log] = eval(
        Task(dataset=[Sample(input="Hi.")], solver=generate()),
        model=_model(stand_in),
        display="none",
    )

    # retried, as today, under the same id; only the reply that came back is
    # looked up, once, as it came without the field
    failed, replied = stand_in.model_calls
    assert failed.headers["x-irid"] == replied.headers["x-irid"]
    assert _looked_up(stand_in) == [replied.headers["x-irid"]]


def _ended(stand_in: StandInSidecar) -> list[str]:
    return [params["sample_uuid"] for params in _registered(stand_in, "end_sample")]


def test_a_sidecar_is_told_when_a_sample_ends_after_its_scoring() -> None:
    stand_in = StandInSidecar()
    task = Task(dataset=[Sample(input="Hi.")], solver=generate(), scorer=_graded())

    [log] = eval(task, model=_model(stand_in), display="none")

    assert log.samples is not None
    assert _ended(stand_in) == [log.samples[0].uuid]
    # after the grader's call, which is the scoring's
    methods = [
        json.loads(r.content).get("method") if r.url.path == "/sentinel/v1" else None
        for r in stand_in.requests
    ]
    last_model_call = max(
        i for i, r in enumerate(stand_in.requests) if r in stand_in.model_calls
    )
    assert methods.index("end_sample") > last_model_call


@solver
def _fails_once() -> Solver:
    attempts = 0

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        nonlocal attempts
        attempts += 1
        state = await generate(state)
        if attempts == 1:
            raise RuntimeError("The first attempt fails.")
        return state

    return solve


def test_a_sample_that_will_be_retried_keeps_its_state_in_the_sidecar() -> None:
    stand_in = StandInSidecar()
    task = Task(dataset=[Sample(input="Hi.")], solver=_fails_once())

    [log] = eval(task, model=_model(stand_in), retry_on_error=1, display="none")

    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is None
    # told once, after the attempt that wasn't retried
    assert _ended(stand_in) == [sample.uuid]
    assert len(stand_in.model_calls) == 2


def _sentinel_events(sample: EvalSample) -> list[SentinelEvent]:
    return [e for e in sample.events if isinstance(e, SentinelEvent)]


_RECORDED = [
    {
        "kind": "record",
        "path": "weather_watch",
        "factory": "weather_watch",
        "name": "weather_watch",
        "function": "watch",
        "call": "call_1",
        "report": {"suspicion": 0.9, "explanation": "Tokyo is far."},
    },
    {
        "kind": "record",
        "path": "no_tokyo",
        "factory": "no_tokyo",
        "name": "no_tokyo",
        "function": "decide",
        "call": "call_1",
        "report": {
            "action": "reject",
            "message": "Tokyo is not allowed.",
            "explanation": "A lookup of Tokyo.",
        },
    },
]


@pytest.mark.parametrize("trimmed", [False, True], ids=["full", "trimmed"])
def test_the_sidecars_reports_are_written_as_sentinel_events(trimmed: bool) -> None:
    step: dict[str, Any] = {
        "stage": "tool_call",
        "call": "call_1",
        "decision": {"action": "reject", "message": "Tokyo is not allowed."},
    }
    if not trimmed:
        step["recorded"] = _RECORDED
    field: dict[str, Any] = {
        "outcome": "proceed",
        "steps": [step],
        "proposed": {
            "message": _turn_json(("call_1", "Tokyo"), ("call_2", "Oslo")),
            "results": {"call_1": "Tokyo is not allowed."},
        },
    }
    if trimmed:
        field["trimmed"] = True
    stand_in = StandInSidecar(
        turns=[
            Turn(calls=[("call_2", "weather", {"city": "Oslo"})], sentinel=field),
            Turn(),
        ]
    )

    sample = _run_agent(stand_in)

    events = _sentinel_events(sample)
    irid = stand_in.model_calls[0].headers["x-irid"]
    assert all(e.step_id == "call_1" and e.stage == "tool_call" for e in events)
    assert all(e.sidecar is not None for e in events)
    where = events[0].sidecar
    assert where is not None
    assert (where.proxy, where.version, where.release, where.request) == (
        "http://proxy.test",
        1,
        "whole",
        irid,
    )
    if trimmed:
        # the step's decision, without the protocol that made it
        [event] = events
        assert (event.kind, event.action, event.function) == (
            "decision",
            "reject",
            None,
        )
        assert where.trimmed
    else:
        # one per report, as in process
        observed, decided = events
        assert (observed.path, observed.kind, observed.suspicion) == (
            "weather_watch",
            "observation",
            0.9,
        )
        assert (decided.path, decided.action, decided.message) == (
            "no_tokyo",
            "reject",
            "Tokyo is not allowed.",
        )
        assert decided.function == "decide"
        assert not where.trimmed


@scorer(metrics=[mean()])
def _reads_monitor_state() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        try:
            require_monitor_state()
        except RuntimeError as ex:
            return Score(value=0, explanation=str(ex))
        return Score(value=state.store.get("Tally:lookups", -1))

    return score


def _kept(store: dict[str, Any]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def answer(params: dict[str, Any]) -> dict[str, Any]:
        return {
            "sample_uuid": params["sample_uuid"],
            "outcome": "proceed",
            "store": store,
        }

    return answer


def test_a_scorer_reads_the_monitor_state_the_sidecar_keeps() -> None:
    stand_in = StandInSidecar(methods={"sample_result": _kept({"Tally:lookups": 3})})
    task = Task(
        dataset=[Sample(input="Hi.")], solver=generate(), scorer=_reads_monitor_state()
    )

    [log] = eval(task, model=_model(stand_in), display="none")

    assert log.samples is not None
    [sample] = log.samples
    assert sample.scores is not None
    assert sample.scores["_reads_monitor_state"].value == 3
    assert _registered(stand_in, "sample_result") == [{"sample_uuid": sample.uuid}]


@pytest.mark.parametrize(
    ("error", "says"),
    [
        ({"code": -32002, "message": "nothing for the sample"}, "holds nothing"),
        ({"code": -32601, "message": "no method"}, "doesn't send results"),
    ],
    ids=["unknown sample", "no results"],
)
def test_a_scorer_can_tell_the_copy_failed(error: dict[str, Any], says: str) -> None:
    stand_in = StandInSidecar(methods={"sample_result": lambda _: {"error": error}})
    task = Task(
        dataset=[Sample(input="Hi.")], solver=generate(), scorer=_reads_monitor_state()
    )

    [log] = eval(task, model=_model(stand_in), display="none")

    assert log.samples is not None
    score = (log.samples[0].scores or {})["_reads_monitor_state"]
    assert score.value == 0
    assert score.explanation is not None and says in score.explanation


@solver
def _scores_as_it_goes() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await generate(state)
        await score(state)
        return state

    return solve


def test_monitor_state_is_copied_before_each_scoring() -> None:
    stand_in = StandInSidecar(methods={"sample_result": _kept({"Tally:lookups": 1})})
    task = Task(
        dataset=[Sample(input="Hi.")],
        solver=_scores_as_it_goes(),
        scorer=_reads_monitor_state(),
    )

    [log] = eval(task, model=_model(stand_in), display="none")

    assert log.status == "success"
    # during the sample, as react scores each answer, and before the final scoring
    assert len(_registered(stand_in, "sample_result")) == 2


def test_a_sample_with_no_call_through_a_sidecar_copies_nothing() -> None:
    stand_in = StandInSidecar()
    task = Task(
        dataset=[Sample(input="Hi.")], solver=_nothing(), scorer=_reads_monitor_state()
    )

    [log] = eval(task, model=_model(stand_in), display="none")

    assert log.samples is not None
    assert (log.samples[0].scores or {})["_reads_monitor_state"].value == -1
    assert _registered(stand_in, "sample_result") == []


def _two_models(first: StandInSidecar, second: StandInSidecar) -> tuple[Model, Model]:
    return (
        _model(first, base_url="http://proxy-a.test"),
        _model(second, base_url="http://proxy-b.test"),
    )


@solver
def _asks_both(other: Model) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await generate(state)
        # an agent that hands work to a model behind another proxy
        await other.generate(state.messages)
        return state

    return solve


def _two_proxy_task(other: Model) -> Task:
    return Task(
        dataset=[Sample(input="Hi.")],
        solver=_asks_both(other),
        scorer=_reads_monitor_state(),
    )


def test_each_sidecar_an_agent_reaches_is_registered_told_and_ended() -> None:
    first = StandInSidecar(methods={"sample_result": _kept({"Tally:lookups": 2})})
    second = StandInSidecar(methods={"sample_result": _kept({"Other:seen": 1})})
    assigned, other = _two_models(first, second)

    [log] = eval(_two_proxy_task(other), model=assigned, display="none")

    assert log.samples is not None
    [sample] = log.samples
    for stand_in in (first, second):
        assert len(_registered(stand_in, "register_task")) == 1
        assert len(_registered(stand_in, "complete_registration")) == 1
        assert _ended(stand_in) == [sample.uuid]
        # each call names its sample to the sidecar it went through
        [call] = stand_in.model_calls
        assert _context(call) is not None
    # the second sidecar was found at the agent's first call to it
    assert len(second.probes) == 1
    assert (sample.scores or {})["_reads_monitor_state"].value == 2


def test_two_sidecars_that_keep_the_same_key_fail_the_sample() -> None:
    first = StandInSidecar(methods={"sample_result": _kept({"Tally:lookups": 2})})
    second = StandInSidecar(methods={"sample_result": _kept({"Tally:lookups": 5})})
    assigned, other = _two_models(first, second)

    [log] = eval(_two_proxy_task(other), model=assigned, display="none")

    assert log.samples is not None
    error = log.samples[0].error
    assert error is not None
    assert "both keep 'Tally:lookups'" in error.message


@solver
def _bridged_turn(seen: list[ModelOutput | Exception]) -> Solver:
    # a bridged agent's call: it runs whatever calls it is handed itself
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        with bridge_model_generate():
            try:
                seen.append(await get_model().generate(state.messages))
            except Exception as ex:
                seen.append(ex)
        return state

    return solve


def test_a_bridged_agent_is_never_handed_a_rejected_call() -> None:
    withheld = {
        "message": _turn_json(("call_1", "Tokyo")),
        "results": {"call_1": "Tokyo is not allowed."},
    }
    step = {
        "stage": "tool_call",
        "call": "call_1",
        "decision": {"action": "reject", "message": "Tokyo is not allowed."},
    }
    stand_in = StandInSidecar(
        turns=[
            Turn(
                status=400,
                sentinel={"outcome": "reject", "steps": [step], "withheld": withheld},
            )
        ]
    )
    seen: list[ModelOutput | Exception] = []
    task = Task(dataset=[Sample(input="Hi.")], solver=_bridged_turn(seen))

    [log] = eval(task, model=_model(stand_in), display="none")

    # the refusal stands, as the provider's error the bridge forwards
    [handed] = seen
    assert isinstance(handed, Exception)
    # and the rejection is in the transcript, as for an agent Inspect runs
    assert log.samples is not None
    [event] = _sentinel_events(log.samples[0])
    assert (event.step_id, event.action) == ("call_1", "reject")


def test_a_bridged_agent_ends_at_the_model_call_for_a_terminate_at_a_call() -> None:
    field = {
        "outcome": "terminate",
        "steps": [_ends("tool_call", "call_1")],
        "withheld": _ended_turn(("call_1", "Tokyo")),
    }
    stand_in = StandInSidecar(turns=[Turn(status=400, sentinel=field)])
    seen: list[ModelOutput | Exception] = []
    task = Task(dataset=[Sample(input="Hi.")], solver=_bridged_turn(seen))

    eval(task, model=_model(stand_in), display="none")

    # it runs its own tools, so it is never handed the turn
    [handed] = seen
    assert isinstance(handed, TerminateSampleError)
    assert handed.reason == "Too far."


def test_a_bridged_agent_ends_at_the_model_call_for_a_terminate_looked_up() -> None:
    field = {
        "outcome": "terminate",
        "steps": [_ends("tool_call", "call_1")],
        "withheld": _ended_turn(("call_1", "Tokyo")),
    }
    stand_in = StandInSidecar(
        # the reply came back with its call, and without the field
        turns=[Turn(calls=[("call_1", "weather", {"city": "Tokyo"})])],
        methods={"request_result": _answers(_decided(field))},
    )
    seen: list[ModelOutput | Exception] = []
    task = Task(dataset=[Sample(input="Hi.")], solver=_bridged_turn(seen))

    eval(task, model=_model(stand_in), display="none")

    # never handed the call, which it would run itself
    [handed] = seen
    assert isinstance(handed, TerminateSampleError)
    assert handed.reason == "Too far."


def test_a_bridged_agent_is_handed_the_turn_as_the_sidecar_left_it() -> None:
    proposed = {
        "message": _turn_json(("call_1", "Tokyo"), ("call_2", "Oslo")),
        "results": {"call_1": "Tokyo is not allowed."},
    }
    stand_in = StandInSidecar(
        turns=[
            Turn(
                calls=[("call_2", "weather", {"city": "Oslo"})],
                sentinel={"outcome": "proceed", "steps": [], "proposed": proposed},
            )
        ]
    )
    seen: list[ModelOutput | Exception] = []
    task = Task(dataset=[Sample(input="Hi.")], solver=_bridged_turn(seen))

    eval(task, model=_model(stand_in), display="none")

    [handed] = seen
    assert isinstance(handed, ModelOutput)
    assert [c.id for c in handed.message.tool_calls or []] == ["call_2"]


def test_an_approver_sees_the_sidecars_change_and_its_own_change_runs() -> None:
    seen: list[dict[str, Any]] = []

    @approver
    def to_lima() -> Approver:
        async def approve(
            message: str, call: ToolCall, view: Any, history: list[Any]
        ) -> Approval:
            seen.append(dict(call.arguments))
            changed = ToolCall(
                id=call.id, function=call.function, arguments={"city": "Lima"}
            )
            return Approval(decision="modify", modified=changed)

        return approve

    original = {"id": "call_1", "function": "weather", "arguments": {"city": "Tokyo"}}
    modified = {"id": "call_1", "function": "weather", "arguments": {"city": "Oslo"}}
    stand_in = StandInSidecar(
        turns=[
            Turn(
                calls=[("call_1", "weather", {"city": "Oslo"})],
                sentinel={
                    "outcome": "proceed",
                    "steps": [
                        {
                            "stage": "tool_call",
                            "call": "call_1",
                            "original": original,
                            "decision": {"action": "modify", "modified": modified},
                        }
                    ],
                },
            ),
            Turn(),
        ]
    )

    _run_agent(stand_in, approval=[ApprovalPolicy(approver=to_lima(), tools="*")])

    # the sidecar judged the turn before Inspect was handed it
    assert seen == [{"city": "Oslo"}]
    assert _LOOKED_UP == ["Lima"]


def test_a_decision_is_recovered_once_inspect_stops_retrying() -> None:
    ended = {
        "outcome": "terminate",
        "steps": [
            {
                "stage": "model_input",
                "decision": {"action": "terminate", "explanation": "Too far."},
            }
        ],
    }
    stand_in = StandInSidecar(
        # a refusal Inspect retries, with the field lost every time
        turns=[Turn(status=503)] * 10,
        methods={"request_result": _answers(_decided(ended))},
    )

    [log] = eval(
        Task(dataset=[Sample(input="Hi.")], solver=generate()),
        model=_model(stand_in),
        max_retries=0,
        display="none",
    )

    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is None
    assert sample.limit is not None
    assert (sample.limit.type, sample.limit.reason) == ("operator", "Too far.")


def test_a_failed_copy_of_monitor_state_still_cleans_up() -> None:
    cleaned: list[str] = []

    async def cleanup(state: TaskState) -> None:
        cleaned.append(state.uuid)

    first = StandInSidecar(methods={"sample_result": _kept({"Tally:lookups": 2})})
    second = StandInSidecar(methods={"sample_result": _kept({"Tally:lookups": 5})})
    assigned, other = _two_models(first, second)
    task = Task(
        dataset=[Sample(input="Hi.")],
        solver=_asks_both(other),
        scorer=_reads_monitor_state(),
        cleanup=cleanup,
    )

    [log] = eval(task, model=assigned, display="none")

    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None
    assert cleaned == [sample.uuid]
