from contextlib import contextmanager
from typing import Generator, Type
from uuid import uuid4

from inspect_ai import Task, eval
from inspect_ai._util.registry import _registry
from inspect_ai.dataset import Sample
from inspect_ai.event import ModelEvent
from inspect_ai.hooks import (
    Hooks,
    SampleEvent,
    SampleStart,
    TaskStart,
    TerminateSampleError,
    TerminateTaskError,
    hooks,
)
from inspect_ai.solver import Generate, Solver, TaskState, solver


@contextmanager
def registered_hook(hook_type: Type[Hooks]) -> Generator[None, None, None]:
    name = f"test_termination_{uuid4().hex}"
    hooks(name, description="Test hook termination")(hook_type)
    try:
        yield
    finally:
        del _registry[f"hooks:{name}"]


def test_sample_hook_can_terminate_current_sample() -> None:
    completed: list[int | str] = []

    class TerminatingHook(Hooks):
        async def on_sample_start(self, data: SampleStart) -> None:
            if data.summary.id == 1:
                raise TerminateSampleError("sample condition failed")

    @solver
    def recording_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            completed.append(state.sample_id)
            return state

        return solve

    with registered_hook(TerminatingHook):
        log = eval(
            Task(
                dataset=[Sample(id=1, input="one"), Sample(id=2, input="two")],
                solver=recording_solver(),
            ),
            model="mockllm/model",
        )[0]

    assert log.status == "success"
    assert completed == [2]
    assert log.samples is not None
    terminated = next(sample for sample in log.samples if sample.id == 1)
    assert terminated.error is None
    assert terminated.limit is not None
    assert terminated.limit.type == "operator"
    assert terminated.limit.reason == "sample condition failed"


def test_ordinary_hook_exception_does_not_terminate_sample() -> None:
    class RaisingHook(Hooks):
        async def on_sample_start(self, data: SampleStart) -> None:
            raise RuntimeError("ordinary hook failure")

    with registered_hook(RaisingHook):
        log = eval(
            Task(dataset=[Sample(id=1, input="one")]),
            model="mockllm/model",
        )[0]

    assert log.status == "success"
    assert log.samples is not None
    assert log.samples[0].error is None


def test_task_hook_termination_ignores_error_configuration() -> None:
    class TerminatingHook(Hooks):
        async def on_sample_start(self, data: SampleStart) -> None:
            raise TerminateTaskError("task condition failed")

    with registered_hook(TerminatingHook):
        log = eval(
            Task(dataset=[Sample(id=1, input="one")]),
            model="mockllm/model",
            fail_on_error=False,
            retry_on_error=2,
            score_on_error=True,
        )[0]

    assert log.status == "error"
    assert log.error is not None
    assert "task condition failed" in log.error.message
    assert log.samples is not None
    assert len(log.samples) == 1
    assert log.samples[0].error is not None
    assert "task condition failed" in log.samples[0].error.message
    assert log.samples[0].error_retries == []


def test_task_start_hook_can_terminate_task() -> None:
    class TerminatingHook(Hooks):
        async def on_task_start(self, data: TaskStart) -> None:
            raise TerminateTaskError("task start condition failed")

    with registered_hook(TerminatingHook):
        log = eval(
            Task(dataset=[Sample(id=1, input="one")]),
            model="mockllm/model",
            fail_on_error=False,
        )[0]

    assert log.status == "error"
    assert log.error is not None
    assert "task start condition failed" in log.error.message
    assert log.samples == []


def test_sample_event_hook_can_terminate_current_sample() -> None:
    class TerminatingHook(Hooks):
        async def on_sample_event(self, data: SampleEvent) -> None:
            if isinstance(data.event, ModelEvent):
                raise TerminateSampleError("event condition failed")

    with registered_hook(TerminatingHook):
        log = eval(
            Task(dataset=[Sample(id=1, input="one")]),
            model="mockllm/model",
        )[0]

    assert log.status == "success"
    assert log.samples is not None
    assert log.samples[0].error is None
    assert log.samples[0].limit is not None
    assert log.samples[0].limit.type == "operator"
    assert log.samples[0].limit.reason == "event condition failed"


def test_sample_event_hook_can_terminate_task() -> None:
    class TerminatingHook(Hooks):
        async def on_sample_event(self, data: SampleEvent) -> None:
            if isinstance(data.event, ModelEvent):
                raise TerminateTaskError("event task condition failed")

    with registered_hook(TerminatingHook):
        log = eval(
            Task(dataset=[Sample(id=1, input="one")]),
            model="mockllm/model",
            fail_on_error=False,
            retry_on_error=2,
        )[0]

    assert log.status == "error"
    assert log.error is not None
    assert "event task condition failed" in log.error.message
    assert log.samples is not None
    assert len(log.samples) == 1
    assert log.samples[0].error is not None
    assert "event task condition failed" in log.samples[0].error.message
    assert log.samples[0].error_retries == []
