import pytest

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log._refusal import refusal_count
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import includes
from inspect_ai.solver import generate


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
        type(
            "MockLogger", (), {"warning": lambda self, msg: warnings.append(msg)}
        )(),
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
    assert any("Model refusal" in w for w in warnings)
    assert any("Content policy violation." in w for w in warnings)
