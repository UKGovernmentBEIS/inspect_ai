"""Sample-level retry_on_error composed with model-level retries."""

# pyright: reportImplicitRelativeImport=false

from _helpers.event_assertions import model_events
from _helpers.retry_provider import (
    RetryableModelError,
    install_retry_classifier,
    make_mockllm_with_callable,
)

from inspect_ai import Task
from inspect_ai import eval as inspect_eval
from inspect_ai.dataset import Sample
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.solver import Generate, TaskState, solver


@solver
def _model_retry_then_solver_fail(should_fail: list[bool]):
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await generate(state)
        if should_fail.pop(0):
            raise ValueError("solver-level failure")
        return state

    return solve


def test_model_retries_inside_sample_retry_have_distinct_call_groups() -> None:
    remaining_model_failures = [2]

    def custom_outputs(input, tools, tool_choice, config):
        if remaining_model_failures[0] > 0:
            remaining_model_failures[0] -= 1
            raise RetryableModelError("transient")
        return ModelOutput.from_content("mockllm", "ok")

    model = make_mockllm_with_callable(custom_outputs)
    install_retry_classifier(model)
    log = inspect_eval(
        Task(
            dataset=[Sample(input="hello")],
            solver=_model_retry_then_solver_fail([True, False]),
        ),
        model=model,
        retry_on_error=1,
    )[0]

    assert log.samples is not None
    sample = log.samples[0]
    assert sample.error_retries is not None
    first_attempt_events = model_events(sample.error_retries[0])
    second_attempt_events = model_events(sample)

    assert [event.attempt for event in first_attempt_events] == [3]
    assert first_attempt_events[0].call_retries == 2
    assert [event.attempt for event in second_attempt_events] == [1]
    assert first_attempt_events[0].call_id != second_attempt_events[0].call_id
