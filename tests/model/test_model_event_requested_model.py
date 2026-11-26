"""`ModelEvent.requested_model` is stamped from the `requested_model()` block.

The block's reset must hold when a generation is cancelled or raises, and the
name must not leak between concurrent tasks.
"""

from typing import Any, Iterator

import anyio
import pytest

from inspect_ai._util._async import tg_collect
from inspect_ai._util.registry import _registry
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import GenerateConfig, ModelOutput, get_model
from inspect_ai.model._model import ModelAPI, _requested_model, requested_model
from inspect_ai.model._registry import modelapi


class _StubAPI(ModelAPI):
    """ModelAPI whose `generate` runs the coroutine passed as `behavior`."""

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            api_key_vars=[],
            config=config,
        )
        self._behavior = model_args["behavior"]

    async def generate(self, *args: Any, **kwargs: Any) -> ModelOutput:
        await self._behavior()
        return ModelOutput.from_content(self.model_name, "stub")


@pytest.fixture(autouse=True)
def _stub_modelapi() -> Iterator[None]:
    @modelapi(name="requestedstub")
    def requestedstub() -> type[ModelAPI]:
        return _StubAPI

    try:
        yield
    finally:
        del _registry["modelapi:requestedstub"]


def _model_events() -> list[ModelEvent]:
    return [e for e in transcript().events if isinstance(e, ModelEvent)]


async def test_requested_model_stamps_event() -> None:
    init_transcript(Transcript())
    model = get_model("mockllm/model")

    with requested_model("gpt-4o-mini"):
        await model.generate("outer")
        with requested_model("claude-haiku-4-5"):
            await model.generate("nested")
        await model.generate("outer again")
    await model.generate("direct")

    assert [e.requested_model for e in _model_events()] == [
        "gpt-4o-mini",
        "claude-haiku-4-5",
        "gpt-4o-mini",
        None,
    ]


async def test_requested_model_reset_after_cancel() -> None:
    init_transcript(Transcript())
    started = anyio.Event()
    never = anyio.Event()

    async def block() -> None:
        started.set()
        await never.wait()

    stub = get_model("requestedstub/x", memoize=False, behavior=block)

    with anyio.CancelScope() as scope:
        async with anyio.create_task_group() as tg:

            async def cancel_when_started() -> None:
                await started.wait()
                scope.cancel()

            tg.start_soon(cancel_when_started)
            with requested_model("gpt-4o-mini"):
                await stub.generate("hello")
    assert scope.cancelled_caught

    assert _requested_model.get() is None
    await get_model("mockllm/model").generate("after cancel")
    assert _model_events()[-1].requested_model is None


async def test_requested_model_reset_after_failure() -> None:
    init_transcript(Transcript())

    async def fail() -> None:
        raise RuntimeError("provider failed")

    stub = get_model("requestedstub/x", memoize=False, behavior=fail)

    with pytest.raises(RuntimeError, match="provider failed"):
        with requested_model("gpt-4o-mini"):
            await stub.generate("hello")

    assert _requested_model.get() is None
    await get_model("mockllm/model").generate("after failure")
    failed, after = _model_events()
    assert failed.error is not None
    assert failed.requested_model == "gpt-4o-mini"
    assert after.requested_model is None


async def test_requested_model_isolated_between_tasks() -> None:
    init_transcript(Transcript())
    both_started = anyio.Event()
    in_flight = 0

    async def wait_for_both() -> None:
        nonlocal in_flight
        in_flight += 1
        if in_flight == 2:
            both_started.set()
        await both_started.wait()

    stub = get_model("requestedstub/x", memoize=False, behavior=wait_for_both)

    async def bridged(name: str) -> str | None:
        with requested_model(name):
            await stub.generate(name)
            return _requested_model.get()

    seen = await tg_collect(
        [lambda: bridged("gpt-4o-mini"), lambda: bridged("claude-haiku-4-5")]
    )

    assert seen == ["gpt-4o-mini", "claude-haiku-4-5"]
    events = _model_events()
    assert len(events) == 2
    for event in events:
        assert event.requested_model == event.input[0].text
    assert _requested_model.get() is None
