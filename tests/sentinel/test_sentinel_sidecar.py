import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import anyio
import httpx2
import pytest
from test_helpers import fake_sentinel as fake
from test_helpers.service_dispatch import (
    dispatching_service,
    serve_beside_failure_monitor,
)
from test_helpers.stand_in_sidecar import StandInSidecar, Turn

from inspect_ai import Task, eval_async
from inspect_ai import eval as inspect_eval
from inspect_ai import score as score_log
from inspect_ai._sentinel._sidecar._endpoint import (
    SentinelProxyError,
    Sidecar,
    SidecarCallError,
    _origin,
    probe,
    proxy_client,
)
from inspect_ai._sentinel._sidecar._events import SIDECAR_METADATA
from inspect_ai._sentinel._sidecar._lookup import RESULT_WAIT
from inspect_ai._sentinel._sidecar._received import receiving_call
from inspect_ai._sentinel._sidecar._task import (
    MONITOR_STATE_COPY,
    SampleFacts,
    TaskFacts,
    TaskSidecars,
)
from inspect_ai._util._async import tg_collect
from inspect_ai._util.exception import SampleRefusedError, TerminateSampleError
from inspect_ai.agent import AgentState, react
from inspect_ai.agent._bridge.sandbox.service import (
    _forward_provider_errors,
    generate_anthropic,
)
from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
from inspect_ai.agent._bridge.util import bridge_model_generate
from inspect_ai.approval import Approval, ApprovalPolicy, Approver, approver
from inspect_ai.dataset import Sample
from inspect_ai.event import InfoEvent, ModelEvent, SentinelEvent, ToolEvent
from inspect_ai.log import EvalLog, EvalSample
from inspect_ai.log._samples import sample_active
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
from inspect_ai.util import LimitExceededError, Store, StoreModel

_MODELS = {
    "anthropic": "anthropic/claude-haiku-4-5",
    # no reasoning options, so no side request to check for reasoning summaries
    "openai": "openai/gpt-4.1-mini",
    # the generic OpenAI-compatible provider, which has no address of its own
    "openai-api": "openai-api/together/meta-llama-3",
}


def eval(tasks: Any, **kwargs: Any) -> list[EvalLog]:
    # each test opts in, as an eval that uses a sidecar must; one of the
    # default passes None
    kwargs.setdefault("sentinel_proxy", "auto")
    return inspect_eval(tasks, **kwargs)


@pytest.fixture(autouse=True)
def _nothing_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # no base URL or credential but the test's own reaches the stand-in
    for name in [
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "OPENAI_BASE_URL",
        "TOGETHER_BASE_URL",
        "HF_INFERENCE_PROVIDERS_BASE_URL",
        "VLLM_BASE_URL",
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
    client = await proxy_client(model.api)
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


async def test_a_sidecar_behind_an_openai_compatible_models_base_url_is_found() -> None:
    stand_in = StandInSidecar()

    found = await _probed(_model(stand_in, "openai-api", "http://proxy.test/v1"))

    assert isinstance(found, Sidecar)
    [asked] = stand_in.probes
    assert str(asked.url) == "http://proxy.test/sentinel/info"


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
async def test_a_model_whose_base_url_was_not_set_is_not_probed(
    provider: str,
) -> None:
    stand_in = StandInSidecar()

    assert await proxy_client(_model(stand_in, provider, base_url=None).api) is None


async def test_a_named_provider_at_its_own_address_is_not_probed() -> None:
    # a service's own default address is no proxy, only a URL someone set is
    model = get_model("together/meta-llama-3", api_key="test-key", memoize=False)

    assert await proxy_client(model.api) is None


async def test_a_provider_that_passes_its_own_address_as_the_base_url_is_not_probed() -> (
    None
):
    # this provider hands its own default to the base class as the base_url
    # argument, which must not count as a URL someone set
    model = get_model(
        "hf-inference-providers/meta-llama/Llama-3.1-8B-Instruct",
        api_key="test-key",
        memoize=False,
    )

    assert await proxy_client(model.api) is None


async def test_a_vllm_server_someone_named_is_probed_without_starting_one() -> None:
    # the client is built lazily, on the first generate; naming a server
    # resolves it with no server started, so the probe has a client to use
    model = get_model(
        "vllm/meta-llama/Llama-3.1-8B-Instruct",
        base_url="http://proxy.test/v1",
        api_key="test-key",
        memoize=False,
    )

    client = await proxy_client(model.api)

    assert client is not None
    assert str(client.base_url).rstrip("/") == "http://proxy.test/v1"
    assert _origin(client.sdk.base_url) == "http://proxy.test"


async def test_a_named_vllm_server_with_an_adapter_is_resolved_off_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # loading the adapter makes blocking requests, so the probe resolves the
    # server as a generate does: in a worker thread, under the server's lock
    import threading

    from inspect_ai.model._providers import vllm

    loaded: list[tuple[bool, bool]] = []

    def stand_in_loading(server: Any, adapter: Any) -> None:
        on_loop = threading.current_thread() is threading.main_thread()
        loaded.append((on_loop, server._init_lock.locked()))

    monkeypatch.setattr(vllm, "get_adapter_rank", lambda adapter: None)
    monkeypatch.setattr(vllm, "ensure_adapter_loaded", stand_in_loading)
    model = get_model(
        "vllm/meta-llama/Llama-3.1-8B-Instruct:an-org/an-adapter",
        base_url="http://proxy.test/v1",
        api_key="test-key",
        memoize=False,
    )

    client = await proxy_client(model.api)

    assert client is not None
    assert loaded == [(False, True)]


async def test_a_second_probe_of_a_model_waits_for_its_adapter_to_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # tasks sharing a model probe it at once; the server counts as resolved
    # only once its adapter is loaded, so the second waits on the lock
    import threading
    from functools import partial

    from inspect_ai.model._providers import vllm

    loading = threading.Event()
    release = threading.Event()

    def stand_in_loading(server: Any, adapter: Any) -> None:
        loading.set()
        release.wait()

    monkeypatch.setattr(vllm, "get_adapter_rank", lambda adapter: None)
    monkeypatch.setattr(vllm, "ensure_adapter_loaded", stand_in_loading)
    model = get_model(
        "vllm/meta-llama/Llama-3.1-8B-Instruct:an-org/another-adapter",
        base_url="http://proxy.test/v1",
        api_key="test-key",
        memoize=False,
    )
    assert isinstance(model.api, vllm.VLLMAPI)
    lock = model.api._server._init_lock
    second_returned: bool | None = None

    async def second_probe() -> None:
        nonlocal second_returned
        await proxy_client(model.api)
        second_returned = not release.is_set()

    # the loader is released however the probes end, inside the group: it
    # waits for the first probe's thread, which waits for the release
    async with anyio.create_task_group() as tg:
        try:
            tg.start_soon(proxy_client, model.api)
            assert await anyio.to_thread.run_sync(partial(loading.wait, 5))
            tg.start_soon(second_probe)
            # the second probe either returns at once, or waits on the lock
            while second_returned is None and not lock.statistics().tasks_waiting:
                await anyio.sleep(0)
        finally:
            release.set()

    assert second_returned is False


@pytest.mark.parametrize("how", ["argument", "environment"])
async def test_an_sglang_server_someone_named_is_probed(
    monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    # SGLang passes the named URL as the service's own too, so the provider
    # says itself where a sidecar may be
    if how == "environment":
        monkeypatch.setenv("SGLANG_BASE_URL", "http://proxy.test/v1")
    model = get_model(
        "sglang/meta-llama/Llama-3.1-8B-Instruct",
        base_url="http://proxy.test/v1" if how == "argument" else None,
        api_key="test-key",
        memoize=False,
    )

    client = await proxy_client(model.api)

    assert client is not None
    assert str(client.base_url).rstrip("/") == "http://proxy.test/v1"
    assert _origin(client.sdk.base_url) == "http://proxy.test"


async def test_an_sglang_server_this_process_started_is_not_probed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # no server was named, so the provider starts one, which can't be behind
    # a proxy; starting it is stood in for
    from inspect_ai.model._providers.sglang import SGLangAPI

    monkeypatch.setattr(
        SGLangAPI,
        "_start_server",
        lambda self, model_path, api_key=None: ("http://localhost:30000/v1", "key"),
    )
    model = get_model(
        "sglang/meta-llama/Llama-3.1-8B-Instruct", api_key="test-key", memoize=False
    )

    assert await proxy_client(model.api) is None


async def test_a_vllm_server_this_process_would_start_is_not_probed() -> None:
    # its own base model: vLLM models sharing one are one server entry, and
    # the named-server test above resolves that entry
    model = get_model(
        "vllm/meta-llama/Llama-3.1-70B-Instruct", api_key="test-key", memoize=False
    )

    assert await proxy_client(model.api) is None
    # nothing was resolved, so no server was started
    assert not hasattr(model.api, "client")


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
    # the setting isn't part of the log format
    assert "sentinel_proxy" not in log.eval.config.model_dump()


def test_an_eval_told_to_look_finds_a_sidecar() -> None:
    stand_in = StandInSidecar()

    [log] = eval(_task(), model=_model(stand_in), sentinel_proxy="auto", display="none")

    assert log.status == "success"
    assert len(stand_in.probes) == 1


@pytest.mark.parametrize("sentinel_proxy", [None, "off"], ids=["not set", "off"])
def test_an_eval_not_told_to_look_sends_nothing_new(sentinel_proxy: Any) -> None:
    stand_in = StandInSidecar()
    task = Task(dataset=[Sample(input="Hi.")], solver=generate())

    [log] = eval(
        task, model=_model(stand_in), sentinel_proxy=sentinel_proxy, display="none"
    )

    # a base URL is set, and still no probe, no registration and no header
    assert log.status == "success"
    assert stand_in.probes == []
    assert stand_in.calls == []
    assert [_context(r) for r in stand_in.model_calls] == [None]


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


async def test_a_samples_registration_is_completed_once_for_each_attempt() -> None:
    stand_in = StandInSidecar()
    sidecars = TaskSidecars("auto", _FACTS)
    sidecar = await sidecars.sidecar(_model(stand_in).api)
    assert sidecar is not None

    # an attempt's calls, at once
    await tg_collect(
        [lambda: sidecars.complete_registration(sidecar, _sample(), "sample_123", 1)]
        * 3
    )

    [completed] = _registered(stand_in, "complete_registration")
    messages = completed.pop("sample_input")
    assert completed == {
        "eval_id": "eval_789",
        # the token the task's registration gave
        "token": "token-1",
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
                "error": {"code": -32001, "message": "not a registered sample"}
            }
        }
    )
    sidecars = TaskSidecars("auto", _FACTS)
    sidecar = await sidecars.sidecar(_model(stand_in).api)
    assert sidecar is not None

    # refused, as a sample that would be refused again, not failed
    with pytest.raises(SampleRefusedError, match="the sample 1 of the task"):
        await sidecars.complete_registration(sidecar, _sample(), "sample_123", 1)
    # a refusal isn't a forgotten task: nothing is registered again
    assert len(_registered(stand_in, "register_task")) == 1


async def test_a_sample_the_sidecar_cant_register_is_an_error() -> None:
    # any other failure to register the sample is an error, which a retry
    # may get past
    stand_in = StandInSidecar(
        methods={
            "complete_registration": lambda _: {
                "error": {"code": -32008, "message": "the registration is full"}
            }
        }
    )
    sidecars = TaskSidecars("auto", _FACTS)
    sidecar = await sidecars.sidecar(_model(stand_in).api)
    assert sidecar is not None

    with pytest.raises(SentinelProxyError, match="couldn't register the sample 1"):
        await sidecars.complete_registration(sidecar, _sample(), "sample_123", 1)


def _forgets_the_task(times: int) -> Callable[[dict[str, Any]], dict[str, Any]]:
    # a sidecar that no longer keeps the task's registration, as after a
    # restart, for its first `times` completions
    forgotten = [times]

    def complete(_: dict[str, Any]) -> dict[str, Any]:
        if forgotten[0] > 0:
            forgotten[0] -= 1
            return {"error": {"code": -32009, "message": "no registration"}}
        return {}

    return complete


async def test_a_task_the_sidecar_forgot_is_registered_again() -> None:
    stand_in = StandInSidecar(methods={"complete_registration": _forgets_the_task(1)})
    sidecars = TaskSidecars("auto", _FACTS)
    sidecar = await sidecars.sidecar(_model(stand_in).api)
    assert sidecar is not None

    await sidecars.complete_registration(sidecar, _sample(), "sample_123", 1)

    # the task's registration again, as first sent with the token the eval
    # holds, then the sample's again
    [first, again] = _registered(stand_in, "register_task")
    assert again == {**first, "token": "token-1"}
    assert [call["method"] for call in stand_in.calls] == [
        "register_task",
        "complete_registration",
        "register_task",
        "complete_registration",
    ]


async def test_every_call_for_the_eval_presents_its_latest_token() -> None:
    # a sidecar that lost the eval, as after a restart, gives a new token
    tokens = iter(["token-1", "token-2"])
    stand_in = StandInSidecar(
        methods={
            "register_task": lambda _: {"token": next(tokens), "fixed": False},
            "complete_registration": _forgets_the_task(1),
        }
    )
    sidecars = TaskSidecars("auto", _FACTS)
    sidecar = await sidecars.sidecar(_model(stand_in).api)
    assert sidecar is not None

    await sidecars.complete_registration(sidecar, _sample(), "sample_123", 1)
    sidecars.called_through("sample_123", 1, sidecar)
    await sidecars.end_sample("sample_123")

    assert [
        (call["method"], call["params"]["eval_id"], call["params"].get("token"))
        for call in stand_in.calls
    ] == [
        ("register_task", "eval_789", None),
        ("complete_registration", "eval_789", "token-1"),
        ("register_task", "eval_789", "token-1"),
        ("complete_registration", "eval_789", "token-2"),
        ("end_sample", "eval_789", "token-2"),
    ]


async def test_samples_that_find_the_task_lost_at_once_register_it_again_once() -> None:
    # every sample's first completion finds the sidecar lost the task and the
    # eval's token, so each registration gets a new token
    issued = iter(f"token-{n}" for n in range(1, 10))
    stand_in = StandInSidecar(
        methods={
            "register_task": lambda _: {"token": next(issued), "fixed": False},
            "complete_registration": _forgets_the_task(3),
        }
    )
    sidecars = TaskSidecars("auto", _FACTS)
    sidecar = await sidecars.sidecar(_model(stand_in).api)
    assert sidecar is not None

    def complete(uuid: str) -> Callable[[], Awaitable[bool]]:
        return lambda: sidecars.complete_registration(sidecar, _sample(), uuid, 1)

    await tg_collect([complete(uuid) for uuid in ["sample_1", "sample_2", "sample_3"]])

    # registered again by one, which the others wait for, rather than by
    # each with a token another's registration has replaced
    assert len(_registered(stand_in, "register_task")) == 2
    completed = _registered(stand_in, "complete_registration")
    assert [params["token"] for params in completed[3:]] == ["token-2"] * 3


_UNAUTHORIZED = {"error": {"code": -32010, "message": "another token"}}


def test_a_task_a_sidecar_keeps_another_token_for_fails() -> None:
    stand_in = StandInSidecar(methods={"register_task": lambda _: _UNAUTHORIZED})

    [log] = eval(_task(), model=_model(stand_in), display="none")

    assert log.status == "error"
    assert log.error is not None
    assert "keeps another token for this eval" in log.error.message


def test_a_sample_whose_results_a_sidecar_wont_give_fails() -> None:
    stand_in = StandInSidecar(
        turns=[Turn(text="Sunny.")],
        methods={"request_result": lambda _: _UNAUTHORIZED},
    )

    [log] = eval(
        Task(dataset=[Sample(input="Hi.")], solver=generate()),
        model=_model(stand_in),
        display="none",
    )

    assert log.samples is not None
    error = log.samples[0].error
    assert error is not None
    assert "won't say what it decided" in error.message


def test_every_reply_through_a_sidecar_is_looked_up() -> None:
    stand_in = StandInSidecar(
        turns=[Turn(text="Sunny.", judgment={"outcome": "proceed", "steps": []})]
    )

    [log] = eval(
        Task(dataset=[Sample(input="Hi.")], solver=generate()),
        model=_model(stand_in),
        display="none",
    )

    assert log.status == "success"
    # a reply never carries what was decided, so it is always asked for
    [call] = stand_in.model_calls
    assert _looked_up(stand_in) == [call.headers["x-irid"]]


async def test_a_call_sent_with_a_token_since_replaced_goes_again() -> None:
    # Another sample registers the eval again while this call is on its way,
    # as after a restart, so the sidecar keeps the new token by the time the
    # call reaches it.
    sidecars = TaskSidecars("auto", _FACTS)

    def ends(params: dict[str, Any]) -> dict[str, Any]:
        if params["token"] != "token-2":
            assert sidecar is not None and sidecar.access is not None
            sidecar.access.token = "token-2"
            return _UNAUTHORIZED
        return {"sample_uuid": params["sample_uuid"], "state": "ended"}

    stand_in = StandInSidecar(methods={"end_sample": ends})
    sidecar = await sidecars.sidecar(_model(stand_in).api)
    assert sidecar is not None

    ended = await sidecar.eval_call("end_sample", {"sample_uuid": "sample_123"})

    assert ended["state"] == "ended"
    assert [params["token"] for params in _registered(stand_in, "end_sample")] == [
        "token-1",
        "token-2",
    ]


async def test_a_call_refused_while_the_eval_registers_again_waits_for_it() -> None:
    # Another sample is registering the eval again, as after a restart: the
    # sidecar already keeps the new token, but its reply hasn't arrived when
    # this call is refused.
    def ends(params: dict[str, Any]) -> dict[str, Any]:
        if params["token"] != "token-2":
            return _UNAUTHORIZED
        return {"sample_uuid": params["sample_uuid"], "state": "ended"}

    stand_in = StandInSidecar(methods={"end_sample": ends})
    sidecars = TaskSidecars("auto", _FACTS)
    sidecar = await sidecars.sidecar(_model(stand_in).api)
    assert sidecar is not None and sidecar.access is not None
    access = sidecar.access
    ended: dict[str, Any] = {}

    async def end() -> None:
        ended.update(
            await sidecar.eval_call("end_sample", {"sample_uuid": "sample_123"})
        )

    async with anyio.create_task_group() as tg:
        # the registration holds the lock until its reply arrives
        await access.lock.acquire()
        tg.start_soon(end)

        # the refused call waits for it
        with anyio.fail_after(5):
            while access.lock.statistics().tasks_waiting == 0:
                await anyio.sleep(0.01)

        access.token = "token-2"
        access.lock.release()

    assert ended["state"] == "ended"
    assert [params["token"] for params in _registered(stand_in, "end_sample")] == [
        "token-1",
        "token-2",
    ]


async def test_a_call_refused_with_the_token_it_still_holds_is_not_sent_again() -> None:
    stand_in = StandInSidecar(methods={"end_sample": lambda _: _UNAUTHORIZED})
    sidecars = TaskSidecars("auto", _FACTS)
    sidecar = await sidecars.sidecar(_model(stand_in).api)
    assert sidecar is not None

    with pytest.raises(SidecarCallError):
        await sidecar.eval_call("end_sample", {"sample_uuid": "sample_123"})

    assert len(_registered(stand_in, "end_sample")) == 1


def test_a_refusal_the_sample_fails_on_is_looked_up_first() -> None:
    # the judgment is recorded before the sample fails on the refusal
    stand_in = StandInSidecar(
        turns=[
            Turn(
                text="I can't help.",
                stop_reason="refusal",
                judgment={"outcome": "proceed", "steps": []},
            )
        ]
    )

    [log] = eval(
        Task(dataset=[Sample(input="Hi.")], solver=generate()),
        model=_model(stand_in),
        display="none",
        fail_on_refusal=True,
    )

    [call] = stand_in.model_calls
    assert _looked_up(stand_in) == [call.headers["x-irid"]]
    assert log.samples is not None
    error = log.samples[0].error
    assert error is not None
    assert "refus" in error.message.lower()


async def test_a_task_the_sidecar_forgets_again_is_an_error() -> None:
    stand_in = StandInSidecar(methods={"complete_registration": _forgets_the_task(2)})
    sidecars = TaskSidecars("auto", _FACTS)
    sidecar = await sidecars.sidecar(_model(stand_in).api)
    assert sidecar is not None

    with pytest.raises(SentinelProxyError, match="couldn't register the sample 1"):
        await sidecars.complete_registration(sidecar, _sample(), "sample_123", 1)
    # registered again once, not on and on
    assert len(_registered(stand_in, "register_task")) == 2


async def test_each_epoch_and_retry_completes_the_samples_registration_again() -> None:
    stand_in = StandInSidecar()
    sidecars = TaskSidecars("auto", _FACTS)
    sidecar = await sidecars.sidecar(_model(stand_in).api)
    assert sidecar is not None

    # the first epoch, its retry, and the second epoch
    for sample_uuid, attempt in [("epoch_1", 1), ("epoch_1", 2), ("epoch_2", 1)]:
        await sidecars.complete_registration(sidecar, _sample(), sample_uuid, attempt)

    assert len(_registered(stand_in, "complete_registration")) == 3


async def test_a_later_epoch_registers_a_task_the_sidecar_lost_again() -> None:
    # the sidecar loses the task, as on a restart, after the sample's first
    # epoch completed its registration
    lost = [False]

    def complete(_: dict[str, Any]) -> dict[str, Any]:
        if lost[0]:
            lost[0] = False
            return {"error": {"code": -32009, "message": "no registration"}}
        return {}

    stand_in = StandInSidecar(methods={"complete_registration": complete})
    sidecars = TaskSidecars("auto", _FACTS)
    sidecar = await sidecars.sidecar(_model(stand_in).api)
    assert sidecar is not None
    await sidecars.complete_registration(sidecar, _sample(), "epoch_1", 1)

    lost[0] = True
    await sidecars.complete_registration(sidecar, _sample(), "epoch_2", 1)

    assert len(_registered(stand_in, "register_task")) == 2
    assert len(_registered(stand_in, "complete_registration")) == 3


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
        "attempt_number": 1,
        "model": _MODELS[provider],
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


async def _kept_id(name: str, turn: Turn) -> tuple[str | None, str | None]:
    # the id the call is kept under, and the `x-irid` it was sent with
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
    with receiving_call() as received:
        try:
            # few tokens, as the Anthropic SDK refuses a long call it isn't streaming
            await model.generate(
                "Hi.", config=GenerateConfig(max_retries=0, max_tokens=100)
            )
        except Exception:
            pass
    [call] = stand_in.model_calls
    return received.request_id, call.headers.get("x-irid")


@pytest.mark.parametrize("name", list(_FORMATS))
async def test_a_reply_is_kept_under_the_id_it_was_sent_with(name: str) -> None:
    kept, sent = await _kept_id(name, Turn())

    # the only way `request_result` finds what was decided of it
    assert kept is not None and kept == sent


@pytest.mark.parametrize("name", list(_FORMATS))
async def test_a_refusal_is_kept_under_the_id_it_was_sent_with(name: str) -> None:
    kept, sent = await _kept_id(name, Turn(status=400))

    assert kept is not None and kept == sent


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


def _turn_json(*calls: tuple[str, str | None]) -> dict[str, Any]:
    # the model's turn, as the sidecar writes it in a judgment: a call with no
    # city is one a decision acted on, redacted to its id and function
    message = ChatMessageAssistant(
        content="Checking.",
        tool_calls=[
            ToolCall(
                id=id,
                function="weather",
                arguments={"city": city} if city is not None else {},
            )
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
    assert log.status == "success"
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


def _recorded_calls(sample: EvalSample) -> list[tuple[str, dict[str, Any]]]:
    # the first turn's calls, as its model event recorded them
    event = next(e for e in sample.events if isinstance(e, ModelEvent))
    return [(c.id, c.arguments) for c in event.output.message.tool_calls or []]


def test_a_call_the_sidecar_took_out_is_answered_with_an_approval_error() -> None:
    proposed = {
        "message": _turn_json(("call_1", None), ("call_2", "Oslo")),
        "results": {"call_1": "Tokyo is not allowed."},
        "redacted": ["call_1"],
    }
    stand_in = StandInSidecar(
        turns=[
            # the sidecar hands over the turn without the rejected call
            Turn(
                calls=[("call_2", "weather", {"city": "Oslo"})],
                judgment={"outcome": "proceed", "steps": [], "proposed": proposed},
            ),
            Turn(text="Sunny in Oslo."),
        ]
    )

    sample = _run_agent(stand_in)

    # the model's turn, both calls in it, as in process, and the rejected
    # call held as given: its id and function, never its arguments
    first = _turns(sample)[0]
    assert [c.id for c in first.tool_calls or []] == ["call_1", "call_2"]
    assert _recorded_calls(sample) == [("call_1", {}), ("call_2", {"city": "Oslo"})]
    results = _tool_messages(sample)
    assert results["call_1"].error is not None
    assert results["call_1"].error.type == "approval"
    assert results["call_1"].error.message == "Tokyo is not allowed."
    assert results["call_2"].error is None
    assert _LOOKED_UP == ["Oslo"]


def test_a_call_the_sidecar_changed_runs_with_its_new_arguments() -> None:
    modified = {"id": "call_1", "function": "weather", "arguments": {"city": "Oslo"}}
    # a changed call is in the turn as it ran; the model's arguments are never
    # handed to the eval
    proposed = {"message": _turn_json(("call_1", "Oslo")), "results": {}}
    stand_in = StandInSidecar(
        turns=[
            Turn(
                calls=[("call_1", "weather", {"city": "Oslo"})],
                judgment={
                    "outcome": "proceed",
                    "steps": [
                        {
                            "stage": "tool_call",
                            "call": "call_1",
                            "decision": {"action": "modify", "modified": modified},
                        }
                    ],
                    "proposed": proposed,
                },
            ),
            Turn(text="Sunny in Oslo."),
        ]
    )

    sample = _run_agent(stand_in)

    # the turn holds the changed call, which ran
    [call] = _turns(sample)[0].tool_calls or []
    assert call.arguments == {"city": "Oslo"}
    assert _recorded_calls(sample) == [("call_1", {"city": "Oslo"})]
    assert _LOOKED_UP == ["Oslo"]


def test_a_turn_the_sidecar_rejected_whole_goes_on_as_the_models_turn() -> None:
    withheld = {
        "message": _turn_json(("call_1", None)),
        "results": {"call_1": "Tokyo is not allowed."},
        "redacted": ["call_1"],
    }
    stand_in = StandInSidecar(
        turns=[
            Turn(status=400, judgment={"outcome": "reject", "withheld": withheld}),
            Turn(text="I can't look that up."),
        ]
    )

    sample = _run_agent(stand_in)

    # the agent carries on, as it would in process
    assert sample.error is None
    [call] = _turns(sample)[0].tool_calls or []
    # held as given: its id and function, never its arguments
    assert (call.id, call.function, call.arguments) == ("call_1", "weather", {})
    error = _tool_messages(sample)["call_1"].error
    assert error is not None
    assert (error.type, error.message) == ("approval", "Tokyo is not allowed.")
    assert _LOOKED_UP == []
    assert _turns(sample)[-1].text == "I can't look that up."


def test_a_turn_rejected_whole_runs_none_of_its_calls_even_one_a_step_changed() -> None:
    # The sidecar changed call_2 and rejected call_1, couldn't write the
    # change, and refused the turn whole: nothing ran, and the judgment's
    # steps still carry the change.
    withheld = {
        "message": _turn_json(("call_1", None), ("call_2", "Oslo")),
        "results": {
            "call_1": "Tokyo is not allowed.",
            "call_2": "This call was not run.",
        },
        "redacted": ["call_1"],
    }
    changed = {"id": "call_2", "function": "weather", "arguments": {"city": "Lima"}}
    steps = [
        {
            "stage": "tool_call",
            "call": "call_1",
            "decision": {"action": "reject", "message": "Tokyo is not allowed."},
        },
        {
            "stage": "tool_call",
            "call": "call_2",
            "decision": {"action": "modify", "modified": changed},
        },
    ]
    stand_in = StandInSidecar(
        turns=[
            Turn(
                status=400,
                judgment={"outcome": "reject", "steps": steps, "withheld": withheld},
            ),
            Turn(text="Neither ran."),
        ]
    )

    sample = _run_agent(stand_in)

    # the refusal stands for every call: the changed one never runs either
    assert sample.error is None
    assert _LOOKED_UP == []
    results = _tool_messages(sample)
    assert {id: m.error.type if m.error else None for id, m in results.items()} == {
        "call_1": "approval",
        "call_2": "approval",
    }
    assert results["call_2"].error is not None
    assert results["call_2"].error.message == "This call was not run."


def _ends(stage: str, call: str | None = None) -> dict[str, Any]:
    # a sentinel's terminate, as the judgment reports it
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
    judgment = {
        "outcome": "terminate",
        "steps": [_ends("tool_call", "call_2")],
        "withheld": _ended_turn(*calls),
    }
    stand_in = StandInSidecar(turns=[Turn(status=400, judgment=judgment)])

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
    judgment: dict[str, Any] = {"outcome": "terminate", "steps": [step]}
    if step["stage"] == "model_output":
        judgment["withheld"] = _ended_turn(("call_1", "Tokyo"))
    stand_in = StandInSidecar(turns=[Turn(status=400, judgment=judgment)])

    sample = _run_agent(stand_in)

    # as in process, the agent is never handed the turn
    _ended_as_operator(sample)
    assert _turns(sample) == []
    assert _LOOKED_UP == []


def test_an_agent_that_doesnt_run_the_turns_calls_ends_at_its_next_call() -> None:
    judgment = {
        "outcome": "terminate",
        "steps": [_ends("tool_call", "call_1")],
        "withheld": _ended_turn(("call_1", "Tokyo")),
    }
    stand_in = StandInSidecar(
        turns=[
            Turn(status=400, judgment=judgment),
            # the sidecar refuses every later call of a run it ended
            Turn(status=400, judgment={"outcome": "terminate", "steps": []}),
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
                judgment={"outcome": "proceed", "steps": [], "proposed": proposed},
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


@pytest.mark.parametrize("sentinel_proxy", [None, "off"], ids=["not set", "off"])
def test_a_failed_call_with_no_sidecar_asks_the_provider_nothing_more(
    sentinel_proxy: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # whether Inspect retries the error is the provider's `should_retry`, which
    # can log or raise, so it is asked only of a call through a sidecar
    from inspect_ai.model import _model as model_module

    asked: list[BaseException] = []

    def would_retry(api: Any, ex: BaseException) -> bool:
        asked.append(ex)
        return False

    monkeypatch.setattr(model_module, "_would_retry", would_retry)
    stand_in = StandInSidecar(turns=[Turn(status=400)])
    task = Task(dataset=[Sample(input="Hi.")], solver=generate())

    [log] = eval(
        task, model=_model(stand_in), sentinel_proxy=sentinel_proxy, display="none"
    )

    assert log.samples is not None and log.samples[0].error is not None
    assert asked == []


def _decided(judgment: dict[str, Any]) -> dict[str, Any]:
    return {"records": "held", "state": "decided", "judgment": judgment}


def _taken_out() -> dict[str, Any]:
    return {
        "outcome": "proceed",
        "steps": [],
        "proposed": {
            "message": _turn_json(("call_1", None), ("call_2", "Oslo")),
            "results": {"call_1": "Tokyo is not allowed."},
            "redacted": ["call_1"],
        },
    }


def _looked_up(stand_in: StandInSidecar) -> list[str]:
    return [params["id"] for params in _registered(stand_in, "request_result")]


def test_a_reply_is_acted_on_as_request_result_says() -> None:
    stand_in = StandInSidecar(
        turns=[Turn(calls=[("call_2", "weather", {"city": "Oslo"})]), Turn()],
        methods={
            "request_result": _answers(
                {"records": "held", "state": "judging"}, _decided(_taken_out())
            )
        },
    )

    sample = _run_agent(stand_in)

    # asked again while the sidecar was still judging, under the call's id,
    # each time holding the answer while it judges, with the eval's token
    first_call = stand_in.model_calls[0]
    assert _looked_up(stand_in)[:2] == [first_call.headers["x-irid"]] * 2
    asked = _registered(stand_in, "request_result")[0]
    assert (asked["wait"], asked["token"]) == (RESULT_WAIT, "token-1")
    assert _tool_messages(sample)["call_1"].error is not None
    assert _LOOKED_UP == ["Oslo"]


def test_a_continued_reply_is_looked_up_after_its_continuation() -> None:
    # Anthropic pauses a long turn, and Inspect continues it under the same
    # request: the sidecar is asked once the continuation's reply is in
    paused = Turn(text="Searching.", stop_reason="pause_turn")
    stand_in = StandInSidecar(
        turns=[paused, Turn(calls=[("call_2", "weather", {"city": "Oslo"})]), Turn()],
        methods={"request_result": _answers(_decided(_taken_out()))},
    )

    sample = _run_agent(stand_in)

    # the continuation goes under the paused reply's request id, which the
    # sidecar is asked about, as the agent's next turn is too
    paused_call, continued = stand_in.model_calls[:2]
    assert continued.headers["x-irid"] == paused_call.headers["x-irid"]
    assert _looked_up(stand_in)[0] == paused_call.headers["x-irid"]
    assert _tool_messages(sample)["call_1"].error is not None
    assert _LOOKED_UP == ["Oslo"]


@pytest.mark.parametrize(
    ("result", "judgment"),
    [
        ({"records": "held", "state": "not_judged", "reason": "error"}, "not judged"),
        ({"records": "unknown"}, "unavailable"),
        # the proxy passed the reply on without handing it to the sidecar
        ({"records": "held", "state": "awaiting_reply"}, "unavailable"),
        # a state of a newer sidecar
        ({"records": "held", "state": "reviewing"}, "unavailable"),
    ],
    ids=["not judged", "unknown", "reply passed on", "unknown state"],
)
def test_a_reply_the_sidecar_didnt_judge_is_used_and_says_so(
    result: dict[str, Any], judgment: str
) -> None:
    stand_in = StandInSidecar(
        turns=[Turn(text="Sunny.")], methods={"request_result": _answers(result)}
    )

    sample = _run_agent(stand_in)

    # an answer, not a wait
    assert len(_looked_up(stand_in)) == 1
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


def test_a_refusal_is_acted_on_as_request_result_says() -> None:
    rejected = {
        "outcome": "reject",
        "withheld": {
            "message": _turn_json(("call_1", None)),
            "results": {"call_1": "Tokyo is not allowed."},
            "redacted": ["call_1"],
        },
    }
    stand_in = StandInSidecar(
        turns=[Turn(status=400), Turn(text="I can't.")],
        methods={"request_result": _answers(_decided(rejected))},
    )

    sample = _run_agent(stand_in)

    assert sample.error is None
    assert _tool_messages(sample)["call_1"].error is not None


def test_a_sample_the_sidecar_never_accepted_is_never_retried_or_scored() -> None:
    # a task the sidecar's admin registered beforehand, whose tasks folder
    # doesn't hold the sample: a retry would be refused the same way
    stand_in = StandInSidecar(
        turns=[Turn(status=400)] * 3,
        methods={
            "complete_registration": lambda _: {"fixed": True},
            "request_result": _answers(
                {"records": "held", "state": "not_judged", "reason": "unregistered"}
            ),
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


def test_a_sample_whose_registration_the_sidecar_refuses_is_never_retried_or_scored() -> (
    None
):
    # a sample the task's registration doesn't name, under `registered_only`,
    # as one added while the task runs: a retry would be refused the same way
    stand_in = StandInSidecar(
        methods={
            "complete_registration": lambda _: {
                "error": {"code": -32001, "message": "not a registered sample"}
            }
        }
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
    # asked once, never retried, and no model call was made
    assert len(_registered(stand_in, "complete_registration")) == 1
    assert stand_in.model_calls == []


def test_a_sample_the_sidecar_lost_is_retried_and_registered_again() -> None:
    # the sidecar restarts mid-sample and loses the task's registration: the
    # running attempt's call is refused as unregistered, and the retry
    # registers the task again
    completions = [0]

    def complete(_: dict[str, Any]) -> dict[str, Any]:
        completions[0] += 1
        if completions[0] == 2:
            return {"error": {"code": -32009, "message": "no registration"}}
        return {"fixed": False}

    stand_in = StandInSidecar(
        turns=[
            Turn(status=400),
            Turn(text="Sunny.", judgment={"outcome": "proceed", "steps": []}),
        ],
        methods={
            "complete_registration": complete,
            "request_result": _answers(
                {"records": "held", "state": "not_judged", "reason": "unregistered"}
            ),
        },
    )
    task = Task(dataset=[Sample(input="Hi.")], solver=generate(), scorer=_graded())

    [log] = eval(task, model=_model(stand_in), retry_on_error=1, display="none")

    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is None
    assert len(sample.error_retries or []) == 1
    assert len(_registered(stand_in, "register_task")) == 2
    assert sample.scores


@pytest.mark.parametrize("retry_on_error", [0, 1], ids=["no retries", "retries spent"])
def test_a_sample_the_sidecar_lost_isnt_scored_on_what_it_holds_since(
    retry_on_error: int,
) -> None:
    # every attempt is lost, and the sample is scored on its error: the
    # sidecar's store began afresh after the restart, so it isn't the
    # sample's monitor state, and a scorer that reads it is told so
    stand_in = StandInSidecar(
        turns=[Turn(status=400)] * 2,
        methods={
            "request_result": _answers(
                *[{"records": "held", "state": "not_judged", "reason": "unregistered"}]
                * 2
            ),
            "sample_result": _kept({}),
        },
    )
    task = Task(
        dataset=[Sample(input="Hi.")],
        solver=generate(),
        scorer=_reads_monitor_state(),
    )

    [log] = eval(
        task,
        model=_model(stand_in),
        retry_on_error=retry_on_error,
        score_on_error=True,
        display="none",
    )

    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None
    score = (sample.scores or {})["_reads_monitor_state"]
    assert score.value == 0
    assert score.explanation is not None and "lost the sample" in score.explanation
    assert _registered(stand_in, "sample_result") == []


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
    # looked up, once
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


def test_a_retried_sample_numbers_its_attempts_and_is_ended_once() -> None:
    stand_in = StandInSidecar()
    task = Task(dataset=[Sample(input="Hi.")], solver=_fails_once())

    [log] = eval(task, model=_model(stand_in), retry_on_error=1, display="none")

    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is None
    # told once, after the attempt that wasn't retried
    assert _ended(stand_in) == [sample.uuid]
    # one sample, two attempts, the retry numbered after the first
    contexts = [_context(call) for call in stand_in.model_calls]
    assert [c["sample_uuid"] for c in contexts if c] == [sample.uuid] * 2
    assert [c["attempt_number"] for c in contexts if c] == [1, 2]
    assert len({c["attempt"] for c in contexts if c}) == 2


def _sentinel_events(sample: EvalSample) -> list[SentinelEvent]:
    return [e for e in sample.events if isinstance(e, SentinelEvent)]


@pytest.mark.parametrize(
    ("roles", "warned"),
    [
        ({"monitor": "mockllm/other"}, True),
        ({"monitor": "mockllm/judge"}, False),
        ({}, False),
    ],
    ids=["another model", "the same model", "no role"],
)
def test_each_report_says_which_models_judged_it(
    roles: dict[str, str], warned: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai._sentinel._sidecar import _events

    warnings: list[str] = []
    monkeypatch.setattr(
        _events, "warn_once", lambda _, message: warnings.append(message)
    )
    step: dict[str, Any] = {
        "stage": "tool_call",
        "call": "call_1",
        "decision": {"action": "proceed"},
        "recorded": _RECORDED[:1],
        "models": [
            {"role": "monitor", "model": "mockllm/judge"},
            {"model": "mockllm/named"},
        ],
    }
    stand_in = StandInSidecar(
        turns=[
            Turn(
                calls=[("call_1", "weather", {"city": "Oslo"})],
                judgment={"outcome": "proceed", "steps": [step]},
            ),
            Turn(),
        ]
    )
    task = Task(
        dataset=[Sample(input="What's the weather?")],
        solver=[use_tools(weather()), generate()],
    )

    [log] = eval(task, model=_model(stand_in), model_roles=roles, display="none")

    # the sidecar's own roles judged, whatever the eval set, and the log says so
    assert log.samples is not None
    [event] = _sentinel_events(log.samples[0])
    assert event.metadata is not None
    assert event.metadata[SIDECAR_METADATA]["models"] == [
        {"role": "monitor", "model": "mockllm/judge"},
        {"model": "mockllm/named"},
    ]
    if warned:
        [warning] = warnings
        assert "model role 'monitor' (mockllm/other)" in warning
        assert "used mockllm/judge" in warning
    else:
        assert warnings == []


def test_both_generate_stages_report_the_generates_id() -> None:
    proceed = {"action": "proceed"}
    stand_in = StandInSidecar(
        turns=[
            Turn(
                calls=[("call_1", "weather", {"city": "Oslo"})],
                judgment={
                    "outcome": "proceed",
                    "steps": [
                        {"stage": "model_input", "decision": proceed},
                        {"stage": "model_output", "decision": proceed},
                        {"stage": "tool_call", "call": "call_1", "decision": proceed},
                    ],
                },
            ),
            Turn(),
        ]
    )

    sample = _run_agent(stand_in)

    # as in process: the uuid of the generate's first model event, and the call's id
    first = next(e for e in sample.events if isinstance(e, ModelEvent))
    assert [(e.stage, e.step_id) for e in _sentinel_events(sample)] == [
        ("model_input", first.uuid),
        ("model_output", first.uuid),
        ("tool_call", "call_1"),
    ]


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
    judgment: dict[str, Any] = {
        "outcome": "proceed",
        "steps": [step],
        "proposed": {
            "message": _turn_json(("call_1", "Tokyo"), ("call_2", "Oslo")),
            "results": {"call_1": "Tokyo is not allowed."},
        },
    }
    if trimmed:
        judgment["trimmed"] = True
    stand_in = StandInSidecar(
        turns=[
            Turn(calls=[("call_2", "weather", {"city": "Oslo"})], judgment=judgment),
            Turn(),
        ]
    )

    sample = _run_agent(stand_in)

    events = _sentinel_events(sample)
    irid = stand_in.model_calls[0].headers["x-irid"]
    assert all(e.step_id == "call_1" and e.stage == "tool_call" for e in events)
    # where each came from, in its metadata, as the log format has no field
    assert all(e.metadata and SIDECAR_METADATA in e.metadata for e in events)
    assert events[0].metadata is not None
    where = events[0].metadata[SIDECAR_METADATA]
    assert (where["proxy"], where["version"], where["release"], where["request"]) == (
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
            "",
        )
        assert where["trimmed"]
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
        assert not where["trimmed"]


def test_a_step_without_records_keeps_its_decisions_metadata() -> None:
    # a sidecar that sends results, with a step that has no records: the
    # decision's own metadata is kept beside where it came from
    judgment: dict[str, Any] = {
        "outcome": "proceed",
        "steps": [
            {
                "stage": "tool_call",
                "call": "call_1",
                "decision": {
                    "action": "reject",
                    "message": "Tokyo is not allowed.",
                    "metadata": {"rule": "no_tokyo"},
                },
            }
        ],
        "proposed": {
            "message": _turn_json(("call_1", "Tokyo"), ("call_2", "Oslo")),
            "results": {"call_1": "Tokyo is not allowed."},
        },
    }
    stand_in = StandInSidecar(
        turns=[
            Turn(calls=[("call_2", "weather", {"city": "Oslo"})], judgment=judgment),
            Turn(),
        ]
    )

    sample = _run_agent(stand_in)

    [event] = _sentinel_events(sample)
    assert event.metadata is not None
    assert event.metadata["rule"] == "no_tokyo"
    assert event.metadata[SIDECAR_METADATA]["trimmed"] is False


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
    assert _registered(stand_in, "sample_result") == [
        {"sample_uuid": sample.uuid, "eval_id": log.eval.eval_id, "token": "token-1"}
    ]


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


@solver
def _calls_then_fails(retry_calls: bool) -> Solver:
    attempts = 0

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            await generate(state)
            raise RuntimeError("The first attempt fails.")
        return await generate(state) if retry_calls else state

    return solve


@pytest.mark.parametrize(
    ("retry_calls", "read"), [(False, -1), (True, 1)], ids=["no call", "a call"]
)
def test_a_retry_is_scored_on_its_own_attempts_monitor_state(
    retry_calls: bool, read: int
) -> None:
    stand_in = StandInSidecar(methods={"sample_result": _kept({"Tally:lookups": 1})})
    task = Task(
        dataset=[Sample(input="Hi.")],
        solver=_calls_then_fails(retry_calls),
        scorer=_reads_monitor_state(),
    )

    [log] = eval(task, model=_model(stand_in), retry_on_error=1, display="none")

    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is None
    # the sidecar still keeps the first attempt's monitor state, which a retry
    # that makes no call through it never reads, as in process
    assert (sample.scores or {})["_reads_monitor_state"].value == read
    assert len(_registered(stand_in, "sample_result")) == (1 if retry_calls else 0)


def test_a_failed_sample_is_saved_with_its_monitor_state() -> None:
    stand_in = StandInSidecar(methods={"sample_result": _kept({"Tally:lookups": 1})})
    task = Task(
        dataset=[Sample(input="Hi.")],
        solver=_calls_then_fails(retry_calls=False),
        scorer=_reads_monitor_state(),
    )

    [log] = eval(task, model=_model(stand_in), display="none")

    # not scored, as it failed, but saved with the state, as in process, so
    # that scoring the log later reads it
    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None and not sample.scores
    assert sample.store["Tally:lookups"] == 1
    rescored = score_log(log, _reads_monitor_state(), display="none")
    assert rescored.samples is not None
    [again] = rescored.samples
    assert (again.scores or {})["_reads_monitor_state"].value == 1
    # the sidecar the first attempt called is still told the sample ended
    assert _ended(stand_in) == [sample.uuid]


@solver
def _calls_and_fails() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        await generate(state)
        raise RuntimeError("The sample fails.")

    return solve


@pytest.mark.parametrize(
    "answer",
    [{"store": []}, {"store": "Tally"}, {"store": None}, {}],
    ids=["a list", "a string", "null", "no store"],
)
def test_a_failed_sample_saved_with_a_malformed_store_fails_only_its_copy(
    answer: dict[str, Any],
) -> None:
    stand_in = StandInSidecar(
        methods={
            "sample_result": lambda params: {
                "sample_uuid": params["sample_uuid"],
                "outcome": "proceed",
                **answer,
            }
        }
    )
    task = Task(
        dataset=[Sample(input="Hi."), Sample(input="Hello.")],
        solver=_calls_and_fails(),
        scorer=_reads_monitor_state(),
    )

    [log] = eval(task, model=_model(stand_in), display="none", fail_on_error=False)

    # each sample fails on its own error and is saved, and the eval goes on
    assert log.error is None
    assert log.samples is not None and len(log.samples) == 2
    for sample in log.samples:
        assert sample.error is not None
        assert "The sample fails." in sample.error.message
        marker = sample.store[MONITOR_STATE_COPY]
        assert marker["copied"] is False
        assert "answered without the sample's store" in marker["reason"]


def _two_models(first: StandInSidecar, second: StandInSidecar) -> tuple[Model, Model]:
    return (
        _model(first, base_url="http://proxy-a.test"),
        _model(second, base_url="http://proxy-b.test"),
    )


@solver
def _asks_another_twice(other: Model) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await generate(state)
        for _ in range(2):
            await other.generate(state.messages)
        return state

    return solve


def test_required_says_when_an_agent_call_goes_through_a_model_with_no_sidecar() -> (
    None
):
    stand_in = StandInSidecar(
        turns=[Turn(text="Sunny.", judgment={"outcome": "proceed", "steps": []})]
    )
    # a second model reached without a proxy, which no sidecar judges
    other = _model(StandInSidecar(), base_url=None)
    task = Task(dataset=[Sample(input="Hi.")], solver=_asks_another_twice(other))

    [log] = eval(
        task, model=_model(stand_in), sentinel_proxy="required", display="none"
    )

    # `required` covers the task's model; the other goes on, noted once
    assert log.status == "success"
    assert log.samples is not None
    noted = [
        e.data
        for e in log.samples[0].events
        if isinstance(e, InfoEvent) and e.source == "sentinel sidecar"
    ]
    assert len(noted) == 1
    assert isinstance(noted[0], dict) and noted[0]["model"] == str(other)


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
    # once each, though the sample failed after the copy
    assert len(_registered(first, "sample_result")) == 1
    assert len(_registered(second, "sample_result")) == 1


class _Calls(StoreModel):
    count: int = 0


# the keys `counts_calls` kept, for the stand-in sidecar to keep too
_KEPT: list[str] = []


@fake.protocol
def counts_calls() -> fake.Protocol:
    # an in-process protocol keeping a count in its store, as the same rule in
    # the sidecar does
    async def decide(
        context: fake.Context, step: fake.BeforeToolCall, escalations: fake.Escalations
    ) -> fake.Decision | None:
        context.store_as(_Calls).count += 1
        _KEPT.extend(k for k in context.store.keys() if k.endswith(":count"))
        return None

    return decide


@pytest.mark.usefixtures("fake_sentinel")
def test_a_sidecar_that_keeps_an_in_process_sentinels_key_fails_the_sample() -> None:
    _KEPT.clear()
    stand_in = StandInSidecar(
        turns=[Turn(calls=[("call_1", "weather", {"city": "Oslo"})]), Turn()],
        methods={"sample_result": lambda params: _kept({_KEPT[0]: 10})(params)},
    )
    task = Task(
        dataset=[Sample(input="What's the weather?")],
        solver=[use_tools(weather()), generate()],
        scorer=_reads_monitor_state(),
        sentinel=counts_calls(),
    )

    [log] = eval(task, model=_model(stand_in), display="none")

    # the same rule in both: the copy would overwrite the count the sentinel
    # inside Inspect carries on from, so the sample fails, as two sidecars
    # keeping one key do, and the count stays its own
    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None
    assert "inside Inspect and the one in the sidecar" in sample.error.message
    assert sample.store[_KEPT[0]] == 1


class _Tally(StoreModel):
    # the monitor state a scorer reads with `store_as()`, as a monitor keeps it
    lookups: int = 0


@scorer(metrics=[mean()])
def _reads_tally() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        # reading puts the model's defaults into the sample store
        return Score(value=1 if state.store_as(_Tally).lookups >= 1 else 0)

    return score


def test_a_scorer_reading_monitor_state_between_attempts_fakes_no_conflict() -> None:
    # The agent submits before it uses the monitored tool, and the scorer
    # reads the monitor's state, which the sidecar hasn't written yet, so the
    # read puts the model's defaults into the store. The agent then uses the
    # tool, the sidecar writes the state, and the final copy must take it
    # for its own earlier state, not for a sentinel's inside Inspect.
    key = f"{_Tally.__name__}:lookups"
    copies = 0

    def tally(params: dict[str, Any]) -> dict[str, Any]:
        nonlocal copies
        copies += 1
        return _kept({} if copies == 1 else {key: 1})(params)

    stand_in = StandInSidecar(
        turns=[
            Turn(calls=[("call_1", "submit", {"answer": "sunny"})]),
            Turn(calls=[("call_2", "weather", {"city": "Oslo"})]),
            Turn(calls=[("call_3", "submit", {"answer": "sunny"})]),
        ],
        methods={"sample_result": tally},
    )
    task = Task(
        dataset=[Sample(input="What's the weather?")],
        solver=react(tools=[weather()], attempts=2),
        scorer=_reads_tally(),
    )

    [log] = eval(task, model=_model(stand_in), display="none")

    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is None, sample.error
    assert copies == 2
    assert sample.store[key] == 1
    assert (sample.scores or {})["_reads_tally"].value == 1


class _HungCopy(StandInSidecar):
    # a sidecar that never answers `sample_result`, while `hangs`
    hangs = True

    def http_client(self) -> httpx2.AsyncClient:
        async def handle(request: httpx2.Request) -> httpx2.Response:
            if self.hangs and request.url.path == "/sentinel/v1":
                if json.loads(request.content)["method"] == "sample_result":
                    self.requests.append(request)
                    await anyio.sleep_forever()
            return self._handle(request)

        return httpx2.AsyncClient(transport=httpx2.MockTransport(handle))


async def test_a_copy_cut_short_keeps_the_record_of_what_earlier_copies_wrote() -> None:
    # a copy, then one an interim scoring's deadline cuts short, then the
    # final one: the keys the first wrote are still the copy's, not taken for
    # a sentinel's inside Inspect
    stand_in = _HungCopy(methods={"sample_result": _kept({"Tally:lookups": 1})})
    stand_in.hangs = False
    sidecars = TaskSidecars("required", _FACTS)
    sidecar = await sidecars.sidecar(_model(stand_in).api)
    assert sidecar is not None
    sidecars.called_through("sample_123", 1, sidecar)
    store = Store()

    await sidecars.copy_monitor_state("sample_123", 1, store)
    stand_in.hangs = True
    with anyio.move_on_after(0.1):
        await sidecars.copy_monitor_state("sample_123", 1, store)
    stand_in.hangs = False
    await sidecars.copy_monitor_state("sample_123", 1, store)

    assert store.get("Tally:lookups") == 1
    marker = store.get(MONITOR_STATE_COPY)
    assert marker["copied"] is True


def test_a_copy_cut_short_by_the_scoring_deadline_says_the_state_is_missing() -> None:
    stand_in = _HungCopy(methods={"sample_result": _kept({"Tally:lookups": 1})})
    # the scoring's deadline is half the sample's time limit
    task = Task(
        dataset=[Sample(input="Hi.")],
        solver=generate(),
        scorer=_reads_monitor_state(),
        time_limit=1,
    )

    [log] = eval(task, model=_model(stand_in), display="none")

    # the deadline fails the sample, and scoring the log later is told why
    # the monitor state is missing, rather than reading none as nothing flagged
    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None
    assert _registered(stand_in, "sample_result") == [
        {"sample_uuid": sample.uuid, "eval_id": log.eval.eval_id, "token": "token-1"}
    ]
    rescored = score_log(log, _reads_monitor_state(), display="none")
    assert rescored.samples is not None
    again = (rescored.samples[0].scores or {})["_reads_monitor_state"]
    assert again.value == 0
    assert again.explanation is not None and "didn't finish" in again.explanation


class _Unanswering(StandInSidecar):
    # a sidecar that judges calls but never answers `sample_result` or
    # `end_sample`, as one that has stopped responding
    def http_client(self) -> httpx2.AsyncClient:
        async def handle(request: httpx2.Request) -> httpx2.Response:
            if request.url.path == "/sentinel/v1":
                method = json.loads(request.content)["method"]
                if method in ("sample_result", "end_sample"):
                    self.requests.append(request)
                    await anyio.sleep_forever()
            return self._handle(request)

        return httpx2.AsyncClient(transport=httpx2.MockTransport(handle))


@solver
def _asks_then_is_cancelled() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await generate(state)
        active = sample_active()
        assert active is not None
        active.interrupt("cancel")
        await anyio.sleep_forever()
        return state

    return solve


def test_a_cancelled_sample_doesnt_wait_on_its_sidecar() -> None:
    stand_in = _Unanswering(methods={"sample_result": _kept({"Tally:lookups": 1})})
    task = Task(
        dataset=[Sample(input="Hi.")],
        solver=_asks_then_is_cancelled(),
        scorer=_reads_monitor_state(),
    )

    [log] = eval(task, model=_model(stand_in), display="none")

    # neither asked, and scoring the log later is told why the monitor state
    # is missing, rather than reading none as nothing flagged
    assert _registered(stand_in, "sample_result") == []
    assert _registered(stand_in, "end_sample") == []
    assert log.samples is not None
    [sample] = log.samples
    marker = sample.store[MONITOR_STATE_COPY]
    assert marker["copied"] is False and "cancelled" in marker["reason"]


@solver
def _asks_both_then_fails(other: Model) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await generate(state)
        await other.generate(state.messages)
        raise RuntimeError("The agent fails.")

    return solve


def test_a_failed_sample_whose_sidecars_keep_the_same_key_says_why_it_has_none() -> (
    None
):
    first = StandInSidecar(methods={"sample_result": _kept({"Tally:lookups": 2})})
    second = StandInSidecar(methods={"sample_result": _kept({"Tally:lookups": 5})})
    assigned, other = _two_models(first, second)
    task = Task(
        dataset=[Sample(input="Hi.")],
        solver=_asks_both_then_fails(other),
        scorer=_reads_monitor_state(),
    )

    [log] = eval(task, model=assigned, display="none")

    # saved with its own error, and scoring the log later is told why the
    # monitor state is missing
    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None and "The agent fails." in sample.error.message
    rescored = score_log(log, _reads_monitor_state(), display="none")
    assert rescored.samples is not None
    explanation = (rescored.samples[0].scores or {})["_reads_monitor_state"].explanation
    assert explanation is not None and "both keep 'Tally:lookups'" in explanation


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


_BILLED = {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}


def _total_tokens(sample: EvalSample) -> int:
    return sum(usage.total_tokens for usage in sample.model_usage.values())


def test_a_refused_turn_counts_the_usage_the_provider_billed() -> None:
    withheld = {
        "message": _turn_json(("call_1", "Tokyo")),
        "results": {"call_1": "Tokyo is not allowed."},
    }
    refused = {"outcome": "reject", "withheld": withheld, "usage": _BILLED}
    stand_in = StandInSidecar(
        turns=[Turn(status=400, judgment=refused), Turn(text="I can't look that up.")]
    )
    task = Task(
        dataset=[Sample(input="What's the weather?")],
        solver=[use_tools(weather()), generate()],
        token_limit=10,
    )

    [log] = eval(task, model=_model(stand_in), display="none")

    # the refused reply's tokens and the next reply's, as in process, where
    # they reach the token limit
    assert log.samples is not None
    [sample] = log.samples
    assert _total_tokens(sample) == 14
    assert sample.limit is not None and sample.limit.type == "token"


# a refusal Inspect doesn't retry (400), or one it would retry (503) once no
# retries are left: each is looked up inside the model call
@pytest.mark.parametrize("status", [400, 503], ids=["not retried", "retries spent"])
def test_a_refused_turn_past_the_token_limit_is_counted_once(status: int) -> None:
    withheld = {
        "message": _turn_json(("call_1", "Tokyo")),
        "results": {"call_1": "Tokyo is not allowed."},
    }
    step = {
        "stage": "tool_call",
        "call": "call_1",
        "decision": {"action": "reject", "message": "Tokyo is not allowed."},
    }
    refused = {
        "outcome": "reject",
        "steps": [step],
        "withheld": withheld,
        "usage": _BILLED,
    }
    stand_in = StandInSidecar(turns=[Turn(status=status, judgment=refused)])
    task = Task(
        dataset=[Sample(input="What's the weather?")],
        solver=[use_tools(weather()), generate()],
        token_limit=6,
    )

    [log] = eval(task, model=_model(stand_in), max_retries=0, display="none")

    # the limit stops the sample at the refused reply, whose tokens count
    # once, and the rejection is still recorded
    assert log.samples is not None
    [sample] = log.samples
    assert _total_tokens(sample) == 7
    assert sample.limit is not None and sample.limit.type == "token"
    [event] = _sentinel_events(sample)
    assert (event.step_id, event.action) == ("call_1", "reject")


def test_a_reply_past_the_token_limit_keeps_what_the_sidecar_decided() -> None:
    # the sidecar judged the reply before Inspect counted its tokens
    step = {"stage": "model_output", "decision": {"action": "proceed"}}
    stand_in = StandInSidecar(
        turns=[Turn(judgment={"outcome": "proceed", "steps": [step]})]
    )
    task = Task(
        dataset=[Sample(input="What's the weather?")],
        solver=generate(),
        token_limit=6,
    )

    [log] = eval(task, model=_model(stand_in), display="none")

    # the sample ends on the limit, counting the reply once, and the
    # transcript shows what the sidecar decided of it
    assert log.samples is not None
    [sample] = log.samples
    assert sample.limit is not None and sample.limit.type == "token"
    assert _total_tokens(sample) == 7
    [call] = stand_in.model_calls
    assert _looked_up(stand_in) == [call.headers["x-irid"]]
    assert [e.stage for e in _sentinel_events(sample)] == ["model_output"]


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
                judgment={
                    "outcome": "reject",
                    "steps": [step],
                    "withheld": withheld,
                    "usage": _BILLED,
                },
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
    # the refused reply was billed, and counts
    assert _total_tokens(log.samples[0]) == 7


def test_a_bridged_rejection_past_the_token_limit_is_recorded_and_counted_once() -> (
    None
):
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
                judgment={
                    "outcome": "reject",
                    "steps": [step],
                    "withheld": withheld,
                    "usage": _BILLED,
                },
            )
        ]
    )
    seen: list[ModelOutput | Exception] = []
    task = Task(
        dataset=[Sample(input="Hi.")], solver=_bridged_turn(seen), token_limit=6
    )

    [log] = eval(task, model=_model(stand_in), display="none")

    # the refused reply's billed tokens take the sample past its limit, and
    # count once; the rejection is in the transcript all the same
    [handed] = seen
    assert isinstance(handed, LimitExceededError)
    assert log.samples is not None
    [sample] = log.samples
    assert _total_tokens(sample) == 7
    [event] = _sentinel_events(sample)
    assert (event.step_id, event.action) == ("call_1", "reject")


def test_a_bridged_agent_ends_at_the_model_call_for_a_terminate_at_a_call() -> None:
    judgment = {
        "outcome": "terminate",
        "steps": [_ends("tool_call", "call_1")],
        "withheld": _ended_turn(("call_1", "Tokyo")),
    }
    stand_in = StandInSidecar(turns=[Turn(status=400, judgment=judgment)])
    seen: list[ModelOutput | Exception] = []
    task = Task(dataset=[Sample(input="Hi.")], solver=_bridged_turn(seen))

    eval(task, model=_model(stand_in), display="none")

    # it runs its own tools, so it is never handed the turn
    [handed] = seen
    assert isinstance(handed, TerminateSampleError)
    assert handed.reason == "Too far."


def test_a_bridged_agent_ends_at_the_model_call_for_a_terminate_looked_up() -> None:
    judgment = {
        "outcome": "terminate",
        "steps": [_ends("tool_call", "call_1")],
        "withheld": _ended_turn(("call_1", "Tokyo")),
    }
    stand_in = StandInSidecar(
        # the reply came back with its call
        turns=[Turn(calls=[("call_1", "weather", {"city": "Tokyo"})])],
        methods={"request_result": _answers(_decided(judgment))},
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
                judgment={"outcome": "proceed", "steps": [], "proposed": proposed},
            )
        ]
    )
    seen: list[ModelOutput | Exception] = []
    task = Task(dataset=[Sample(input="Hi.")], solver=_bridged_turn(seen))

    eval(task, model=_model(stand_in), display="none")

    [handed] = seen
    assert isinstance(handed, ModelOutput)
    assert [c.id for c in handed.message.tool_calls or []] == ["call_2"]


_ANTHROPIC_REQUEST = {
    "model": "inspect",
    "max_tokens": 64,
    "messages": [{"role": "user", "content": "Hi."}],
}


@solver
def _sandbox_bridged_turn(monkeypatch: pytest.MonkeyPatch) -> Solver:
    # a sandbox-bridged agent's call, through the model service's own method
    # as `run_model_service` registers it, the service dispatcher and the
    # bridge's failure monitor, which `sandbox_agent_bridge` runs in one task
    # group
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        bridge = SandboxAgentBridge(
            state=AgentState(messages=state.messages),
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
        )
        service = dispatching_service(
            monkeypatch,
            "generate_anthropic",
            _forward_provider_errors(generate_anthropic(None, None, bridge), bridge),
            {"json_data": _ANTHROPIC_REQUEST},
            [],
        )
        unwound = await serve_beside_failure_monitor(service, bridge)

        # the failure the monitor raised unwinds the agent, and reaches the
        # sample runner as the sample's error
        if unwound:
            [failure] = unwound
            raise failure
        return state

    return solve


def test_a_sandbox_bridged_sample_the_sidecar_never_accepted_is_never_retried_or_scored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stand_in = StandInSidecar(
        turns=[Turn(status=400)] * 3,
        methods={
            "complete_registration": lambda _: {"fixed": True},
            "request_result": _answers(
                {"records": "held", "state": "not_judged", "reason": "unregistered"}
            ),
        },
    )
    task = Task(
        dataset=[Sample(input="Hi.")],
        solver=_sandbox_bridged_turn(monkeypatch),
        scorer=_graded(),
    )

    [log] = eval(
        task,
        model=_model(stand_in),
        retry_on_error=2,
        score_on_error=True,
        display="none",
    )

    # failed, not handed to the agent as a provider's error to carry on from
    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is not None
    assert "SampleRefusedError" in sample.error.message
    assert sample.scores is None or sample.scores == {}
    assert len(stand_in.model_calls) == 1


def test_a_sandbox_bridged_sample_the_sidecar_lost_is_retried_and_registered_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completions = [0]

    def complete(_: dict[str, Any]) -> dict[str, Any]:
        completions[0] += 1
        if completions[0] == 2:
            return {"error": {"code": -32009, "message": "no registration"}}
        return {"fixed": False}

    stand_in = StandInSidecar(
        turns=[
            Turn(status=400),
            Turn(text="Sunny.", judgment={"outcome": "proceed", "steps": []}),
        ],
        methods={
            "complete_registration": complete,
            "request_result": _answers(
                {"records": "held", "state": "not_judged", "reason": "unregistered"}
            ),
        },
    )
    task = Task(
        dataset=[Sample(input="Hi.")],
        solver=_sandbox_bridged_turn(monkeypatch),
        scorer=_graded(),
    )

    [log] = eval(task, model=_model(stand_in), retry_on_error=1, display="none")

    # the retry registers the task again, and its call goes through
    assert log.samples is not None
    [sample] = log.samples
    assert sample.error is None
    assert len(sample.error_retries or []) == 1
    assert len(_registered(stand_in, "register_task")) == 2
    assert len(_registered(stand_in, "complete_registration")) == 3
    assert sample.scores


def test_a_sandbox_bridged_reply_whose_judgment_is_unavailable_fails_a_required_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stand_in = StandInSidecar(
        turns=[Turn(text="Sunny.")],
        methods={"request_result": _answers({"records": "dropped"})},
    )
    task = Task(
        dataset=[Sample(input="Hi.")], solver=_sandbox_bridged_turn(monkeypatch)
    )

    [log] = eval(
        task, model=_model(stand_in), sentinel_proxy="required", display="none"
    )

    assert log.samples is not None
    error = log.samples[0].error
    assert error is not None
    assert "SidecarNotJudgedError" in error.message
    assert "a sidecar is required" in error.message


def test_a_sandbox_bridged_sample_the_sidecar_couldnt_register_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stand_in = StandInSidecar(
        methods={
            "complete_registration": lambda _: {
                "error": {"code": -32000, "message": "The sidecar is full."}
            }
        },
    )
    task = Task(
        dataset=[Sample(input="Hi.")], solver=_sandbox_bridged_turn(monkeypatch)
    )

    [log] = eval(task, model=_model(stand_in), display="none")

    assert log.samples is not None
    error = log.samples[0].error
    assert error is not None
    assert "SentinelProxyError" in error.message
    assert "The sidecar is full." in error.message
    assert stand_in.model_calls == []


# a provider error Inspect doesn't retry, which the Anthropic provider raises
# (403) or returns with the call it made (400): each is looked up at its own
# place in the model call
_RAISED, _RETURNED = 403, 400

_CANCELLED = "cancelled by the deadline"


@solver
def _turn_within(
    seconds: float, seen: list[ModelOutput | BaseException | str]
) -> Solver:
    # an agent call that a deadline can cancel, as an interim-scoring deadline
    # does
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        with anyio.move_on_after(seconds) as scope:
            try:
                seen.append(await get_model().generate(state.messages))
            except Exception as ex:
                seen.append(ex)
                raise
        if scope.cancelled_caught:
            seen.append(_CANCELLED)
        return state

    return solve


def _discards(monkeypatch: pytest.MonkeyPatch) -> list[None]:
    # each time a failed attempt's partial streamed output is dropped
    from inspect_ai.model._stream import ModelStreamObserver

    discarded: list[None] = []
    original = ModelStreamObserver.discard_partial_output

    def discard(self: ModelStreamObserver) -> None:
        discarded.append(None)
        original(self)

    monkeypatch.setattr(ModelStreamObserver, "discard_partial_output", discard)
    return discarded


def _model_events(log: EvalLog) -> list[ModelEvent]:
    assert log.samples is not None
    return [e for e in log.samples[0].events if isinstance(e, ModelEvent)]


@pytest.mark.parametrize("status", [_RAISED, _RETURNED], ids=["raised", "returned"])
async def test_a_lookup_a_deadline_cancels_completes_the_calls_event(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    discarded = _discards(monkeypatch)
    stand_in = StandInSidecar(
        turns=[Turn(status=status)],
        # still judging whenever it is asked
        methods={
            "request_result": lambda params: {
                "id": params["id"],
                "records": "held",
                "state": "judging",
            }
        },
    )
    seen: list[ModelOutput | BaseException | str] = []
    task = Task(dataset=[Sample(input="Hi.")], solver=_turn_within(0.3, seen))

    [log] = await eval_async(task, model=_model(stand_in), sentinel_proxy="auto")

    # the cancellation went on to the deadline's scope
    assert seen == [_CANCELLED]
    # and the event isn't left pending: it has the call's own error
    [event] = _model_events(log)
    assert event.pending is None
    assert event.error is not None and str(status) in event.error
    assert discarded


@pytest.mark.parametrize("status", [_RAISED, _RETURNED], ids=["raised", "returned"])
async def test_a_judgment_that_cant_be_read_completes_the_calls_event(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    discarded = _discards(monkeypatch)
    stand_in = StandInSidecar(
        turns=[Turn(status=status, judgment={"outcome": "perhaps"})]
    )
    seen: list[ModelOutput | BaseException | str] = []
    task = Task(dataset=[Sample(input="Hi.")], solver=_turn_within(10, seen))

    [log] = await eval_async(task, model=_model(stand_in), sentinel_proxy="auto")

    # the judgment's error is the sample's
    [failed] = seen
    assert isinstance(failed, ValueError)
    assert log.samples is not None
    error = log.samples[0].error
    assert error is not None and "judgment can't be read" in error.message
    # and the event has the call's own error
    [event] = _model_events(log)
    assert event.pending is None
    assert event.error is not None and str(status) in event.error
    assert discarded


@pytest.mark.parametrize("status", [_RAISED, _RETURNED], ids=["raised", "returned"])
async def test_a_refusal_at_either_place_is_still_acted_on_as_the_models_turn(
    status: int,
) -> None:
    withheld = {
        "message": _turn_json(("call_1", "Tokyo")),
        "results": {"call_1": "Tokyo is not allowed."},
    }
    stand_in = StandInSidecar(
        turns=[
            Turn(status=status, judgment={"outcome": "reject", "withheld": withheld})
        ]
    )
    seen: list[ModelOutput | BaseException | str] = []
    task = Task(dataset=[Sample(input="Hi.")], solver=_turn_within(10, seen))

    [log] = await eval_async(task, model=_model(stand_in), sentinel_proxy="auto")

    [handed] = seen
    assert isinstance(handed, ModelOutput)
    assert [c.id for c in handed.message.tool_calls or []] == ["call_1"]
    [event] = _model_events(log)
    assert event.pending is None and event.error is None


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
                judgment={
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
        # a refusal Inspect retries, with the judgment lost every time
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


def test_a_limit_tripped_before_a_retry_dispatches_looks_nothing_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the first attempt is refused and retried; a limit then trips before the
    # retry is dispatched, so there is no request of this attempt to look up,
    # and the first attempt's id must not be looked up in its place
    from inspect_ai.model import _model as model_module

    checked = model_module._check_limits_before_dispatch
    checks = 0

    def check_limits() -> None:
        nonlocal checks
        checks += 1
        # an attempt checks twice before dispatching: the third check is the
        # retry's first
        if checks == 3:
            raise LimitExceededError("token", value=7, limit=7)
        checked()

    monkeypatch.setattr(model_module, "_check_limits_before_dispatch", check_limits)
    stand_in = StandInSidecar(
        # refused on each of the SDK's own tries, so Inspect's attempt fails
        turns=[Turn(status=503)] * 3,
        methods={
            "request_result": _answers(
                {"records": "held", "state": "not_judged", "reason": "error"}
            )
        },
    )

    [log] = eval(
        Task(dataset=[Sample(input="Hi.")], solver=generate()),
        model=_model(stand_in),
        max_retries=1,
        display="none",
    )

    assert log.samples is not None
    [sample] = log.samples
    assert sample.limit is not None and sample.limit.type == "token"
    assert _looked_up(stand_in) == []


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
