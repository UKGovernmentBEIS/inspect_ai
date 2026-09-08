from typing import Any

import pytest

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.event._error import ErrorEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.log import EvalLog, EvalSample
from inspect_ai.log._refusal import refusal_count
from inspect_ai.model import (
    GenerateConfig,
    Model,
    ModelOutput,
    StopDetails,
    get_model,
)
from inspect_ai.scorer import includes
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver


def test_refusal_count():
    """Single content_filter increments refusal_count."""
    task = Task(
        dataset=[Sample(input="test", target="ignored")],
        solver=[generate()],
        scorer=includes(),
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content(
                model="mockllm/model",
                content="I cannot help with that.",
                stop_reason="content_filter",
            ),
        ],
    )
    eval(task, model=model)
    assert refusal_count() == 1


def test_refusal_count_multiple():
    """Multiple content_filter outputs accumulate in refusal_count."""
    task = Task(
        dataset=[
            Sample(input="test1", target="ignored"),
            Sample(input="test2", target="ignored"),
        ],
        solver=[generate()],
        scorer=includes(),
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content(
                model="mockllm/model",
                content="Refused 1",
                stop_reason="content_filter",
            ),
            ModelOutput.from_content(
                model="mockllm/model",
                content="Refused 2",
                stop_reason="content_filter",
            ),
        ],
    )
    eval(task, model=model)
    assert refusal_count() == 2


def test_no_refusals():
    """Normal outputs don't increment refusal_count."""
    task = Task(
        dataset=[Sample(input="test", target="hello")],
        solver=[generate()],
        scorer=includes(),
    )
    eval(task, model="mockllm/model")
    assert refusal_count() == 0


def test_refusal_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refusals log a warning with refusal text."""
    warnings: list[str] = []
    monkeypatch.setattr(
        "inspect_ai.log._refusal.logger",
        type("MockLogger", (), {"warning": lambda self, msg: warnings.append(msg)})(),
    )

    task = Task(
        dataset=[Sample(input="test", target="ignored")],
        solver=[generate()],
        scorer=includes(),
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content(
                model="mockllm/model",
                content="Content policy violation.",
                stop_reason="content_filter",
            ),
        ],
    )
    eval(task, model=model, log_refusals=True)
    assert any("Model refusal" in w for w in warnings)
    assert any("Content policy violation." in w for w in warnings)


def test_refusal_no_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refusals do not log warnings when log_refusals is not set."""
    warnings: list[str] = []
    monkeypatch.setattr(
        "inspect_ai.log._refusal.logger",
        type("MockLogger", (), {"warning": lambda self, msg: warnings.append(msg)})(),
    )

    task = Task(
        dataset=[Sample(input="test", target="ignored")],
        solver=[generate()],
        scorer=includes(),
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content(
                model="mockllm/model",
                content="Content policy violation.",
                stop_reason="content_filter",
            ),
        ],
    )
    eval(task, model=model)
    assert not any("Model refusal" in w for w in warnings)


# ---------- fail_on_refusal ----------


def _refusal(
    content: str = "I cannot help with that.", category: str | None = None
) -> ModelOutput:
    return ModelOutput.from_content(
        model="mockllm/model",
        content=content,
        stop_reason="content_filter",
        stop_details=StopDetails(type="refusal", category=category)
        if category
        else None,
    )


def _refusing_model(
    category: str | None = None, config: GenerateConfig = GenerateConfig()
) -> Model:
    return get_model(
        "mockllm/model", custom_outputs=[_refusal(category=category)], config=config
    )


def _task(solver: Solver | list[Solver] | None = None, **kwargs: Any) -> Task:
    return Task(
        dataset=[Sample(input="test", target="ignored")],
        solver=solver or [generate()],
        scorer=includes(),
        **kwargs,
    )


def _sample(log: EvalLog) -> EvalSample:
    assert log.samples
    return log.samples[0]


def test_fail_on_refusal_errors_sample() -> None:
    """A refusal under fail_on_refusal fails the sample as an ordinary sample error."""
    log = eval(
        _task(),
        model=_refusing_model(category="cyber"),
        fail_on_refusal=True,
        fail_on_error=False,
    )[0]
    assert log.status == "success"
    sample = _sample(log)
    assert sample.error is not None
    assert (
        "Model refusal (mockllm/model, category cyber): I cannot help with that."
        in sample.error.message
    )
    assert not sample.scores
    # the refusal is still counted
    assert refusal_count() == 1

    # the ModelEvent is complete (with timing) and precedes the ErrorEvent
    events = sample.events
    model_index = next(i for i, e in enumerate(events) if isinstance(e, ModelEvent))
    error_index = next(i for i, e in enumerate(events) if isinstance(e, ErrorEvent))
    assert model_index < error_index
    model_event = events[model_index]
    error_event = events[error_index]
    assert isinstance(model_event, ModelEvent)
    assert isinstance(error_event, ErrorEvent)
    assert model_event.output.stop_reason == "content_filter"
    assert model_event.completed is not None
    assert model_event.working_time is not None
    assert "Model refusal" in error_event.error.message


def test_fail_on_refusal_default_fail_on_error_fails_eval() -> None:
    """With the default fail_on_error, the first refusal fails the whole eval."""
    log = eval(_task(), model=_refusing_model(), fail_on_refusal=True)[0]
    assert log.status == "error"


def test_fail_on_refusal_score_on_error_still_scores() -> None:
    log = eval(
        _task(),
        model=_refusing_model(),
        fail_on_refusal=True,
        score_on_error=True,
    )[0]
    sample = _sample(log)
    assert sample.error is not None
    assert sample.scores


def test_fail_on_refusal_off_by_default() -> None:
    log = eval(_task(), model=_refusing_model())[0]
    assert log.status == "success"
    sample = _sample(log)
    assert sample.error is None
    assert sample.output.stop_reason == "content_filter"


def test_fail_on_refusal_per_call_overrides_eval_wide() -> None:
    @solver
    def generate_tolerating_refusals() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            state.output = await get_model().generate(
                state.messages, config=GenerateConfig(fail_on_refusal=False)
            )
            return state

        return solve

    log = eval(
        _task(generate_tolerating_refusals()),
        model=_refusing_model(),
        fail_on_refusal=True,
    )[0]
    assert log.status == "success"
    sample = _sample(log)
    assert sample.error is None
    assert sample.output.stop_reason == "content_filter"


def test_fail_on_refusal_model_config() -> None:
    """The option set on the model itself (--model-spec / get_model(config=...))."""
    log = eval(
        _task(),
        model=_refusing_model(config=GenerateConfig(fail_on_refusal=True)),
        fail_on_error=False,
    )[0]
    assert _sample(log).error is not None


def test_fail_on_refusal_eval_wide_overrides_active_model_config() -> None:
    """Existing merge order: eval-wide config wins over the active model's own config."""
    log = eval(
        _task(),
        model=_refusing_model(config=GenerateConfig(fail_on_refusal=False)),
        fail_on_refusal=True,
        fail_on_error=False,
    )[0]
    assert _sample(log).error is not None


def test_fail_on_refusal_task_config() -> None:
    log = eval(
        _task(config=GenerateConfig(fail_on_refusal=True)),
        model=_refusing_model(),
        fail_on_error=False,
    )[0]
    assert _sample(log).error is not None


# ---------- fail_on_refusal and model roles ----------


@solver
def ask_grader() -> Solver:
    """Solver that asks the grader role to generate (the grader refuses in tests)."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.output = await get_model(role="grader").generate("grade this")
        return state

    return solve


def test_fail_on_refusal_eval_wide_reaches_roles() -> None:
    log = eval(
        _task(ask_grader()),
        model="mockllm/model",
        model_roles={"grader": _refusing_model()},
        fail_on_refusal=True,
        fail_on_error=False,
    )[0]
    sample = _sample(log)
    assert sample.error is not None
    assert "Model refusal (mockllm/model, role grader)" in sample.error.message


def test_fail_on_refusal_task_config_reaches_roles() -> None:
    log = eval(
        _task(ask_grader(), config=GenerateConfig(fail_on_refusal=True)),
        model="mockllm/model",
        model_roles={"grader": _refusing_model()},
        fail_on_error=False,
    )[0]
    assert _sample(log).error is not None


def test_fail_on_refusal_role_opt_out_wins_over_eval_wide() -> None:
    """A role's own fail_on_refusal=False beats an eval-wide True (role-wins)."""
    log = eval(
        _task(ask_grader()),
        model="mockllm/model",
        model_roles={
            "grader": _refusing_model(config=GenerateConfig(fail_on_refusal=False))
        },
        fail_on_refusal=True,
    )[0]
    assert log.status == "success"
    sample = _sample(log)
    assert sample.error is None
    assert sample.output.stop_reason == "content_filter"


def test_fail_on_refusal_role_opt_in_only_affects_that_role() -> None:
    """A role set to True fails on its refusals while the active model is unaffected."""
    log = eval(
        _task([generate(), ask_grader()]),
        model=_refusing_model(),
        model_roles={
            "grader": _refusing_model(config=GenerateConfig(fail_on_refusal=True))
        },
        fail_on_error=False,
    )[0]
    sample = _sample(log)
    # the active model's refusal (first generate) did not fail the sample; the
    # grader's did
    assert sample.error is not None
    assert "role grader" in sample.error.message
    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert len(model_events) == 2
    assert model_events[0].role is None
    assert model_events[1].role == "grader"
