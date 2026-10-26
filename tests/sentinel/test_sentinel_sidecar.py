from typing import Any

import pytest
from test_helpers.stand_in_sidecar import StandInSidecar

from inspect_ai import Task, eval
from inspect_ai._sentinel._sidecar._endpoint import (
    SentinelProxyError,
    Sidecar,
    probe,
    proxy_client,
)
from inspect_ai._sentinel._sidecar._task import TaskSidecars
from inspect_ai._util._async import tg_collect
from inspect_ai.dataset import Sample
from inspect_ai.model import Model, get_model
from inspect_ai.solver import Generate, Solver, TaskState, solver

_MODELS = {
    "anthropic": "anthropic/claude-haiku-4-5",
    "openai": "openai/gpt-5-mini",
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
    sidecars = TaskSidecars("required")

    with pytest.raises(SentinelProxyError, match="has no sidecar"):
        await sidecars.start(_model(StandInSidecar(info=None)))


async def test_a_task_that_requires_a_sidecar_fails_for_a_model_never_probed() -> None:
    sidecars = TaskSidecars("required")

    with pytest.raises(SentinelProxyError, match="base URL was not set"):
        await sidecars.start(_model(StandInSidecar(), base_url=None))


async def test_an_endpoint_is_probed_once_for_samples_asking_at_once() -> None:
    stand_in = StandInSidecar()
    model = _model(stand_in)
    sidecars = TaskSidecars("auto")

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
