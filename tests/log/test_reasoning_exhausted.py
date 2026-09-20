"""Tests for detecting responses whose output budget was consumed by reasoning.

The failure being guarded against is a *silent zero*: the request succeeds, the completion
is empty (the whole output budget went to the reasoning channel), and the sample is scored
as a wrong answer rather than an unanswered one. The negative controls matter as much as
the positive case -- flagging ordinary completions would make the warning noise.

The last two tests run a real `eval()` on a mock model, so the wiring is exercised end to
end: the mechanism has to fire on its own, not only when called directly.
"""

import pathlib

import pytest

from inspect_ai import Task, eval, task
from inspect_ai._util import logger as logger_mod
from inspect_ai.dataset import Sample
from inspect_ai.log import _reasoning as reasoning_mod
from inspect_ai.log._reasoning import (
    init_reasoning_exhausted_tracking,
    reasoning_exhausted_budget,
    reasoning_exhausted_count,
    report_reasoning_exhausted,
)
from inspect_ai.model import get_model
from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.model._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
)
from inspect_ai.scorer import match
from inspect_ai.solver import generate


def make_output(
    completion: str = "",
    stop_reason: str = "max_tokens",
    reasoning_tokens: int | None = 16,
    output_tokens: int = 16,
    with_usage: bool = True,
) -> ModelOutput:
    usage = (
        ModelUsage(
            input_tokens=10,
            output_tokens=output_tokens,
            total_tokens=10 + output_tokens,
            reasoning_tokens=reasoning_tokens,
        )
        if with_usage
        else None
    )
    return ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(content=completion, source="generate"),
                stop_reason=stop_reason,
            )
        ],
        usage=usage,
    )


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    init_reasoning_exhausted_tracking()
    logger_mod._warned.clear()


def test_detects_budget_consumed_by_reasoning() -> None:
    assert reasoning_exhausted_budget(make_output()) is True


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"stop_reason": "stop"}, "budget did not bind (normal stop)"),
        ({"stop_reason": "content_filter"}, "another stop reason"),
        ({"completion": "ANSWER: B"}, "a visible completion was produced"),
        ({"reasoning_tokens": 5}, "reasoning used only part of the budget"),
        ({"reasoning_tokens": None}, "provider reports no reasoning tokens"),
        ({"output_tokens": 0}, "no output tokens reported"),
        ({"with_usage": False}, "no usage reported at all"),
    ],
)
def test_negative_controls(kwargs: dict, reason: str) -> None:
    assert reasoning_exhausted_budget(make_output(**kwargs)) is False, reason


def test_reports_once_but_counts_every_occurrence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(reasoning_mod.logger, "warning", lambda message: warnings.append(message))

    for _ in range(3):
        assert report_reasoning_exhausted(make_output()) is True

    assert reasoning_exhausted_count() == 3
    assert len(warnings) == 1
    assert "consumed by" in warnings[0]
    assert "reasoning_tokens=16" in warnings[0]


def test_does_not_report_or_count_negative_controls() -> None:
    assert report_reasoning_exhausted(make_output(stop_reason="stop")) is False
    assert reasoning_exhausted_count() == 0


def test_init_resets_the_counter() -> None:
    report_reasoning_exhausted(make_output())
    assert reasoning_exhausted_count() == 1
    init_reasoning_exhausted_tracking()
    assert reasoning_exhausted_count() == 0


@task
def _tiny_task() -> Task:
    return Task(
        dataset=[Sample(input="What is 2+2?", target="4")],
        solver=generate(),
        scorer=match(),
    )


def _run(custom_outputs: list[ModelOutput], log_dir: pathlib.Path):
    model = get_model("mockllm/model", custom_outputs=custom_outputs)
    logs = eval(
        _tiny_task(),
        model=model,
        log_dir=str(log_dir / "logs"),
        display="none",
    )
    return logs[0]


def test_fires_during_a_real_eval(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mechanism must fire by itself during a real eval, not only when called directly."""
    warnings: list[str] = []
    monkeypatch.setattr(reasoning_mod.logger, "warning", lambda message: warnings.append(message))

    log = _run([make_output()], tmp_path)

    assert reasoning_exhausted_count() == 1
    assert any("consumed by" in warning for warning in warnings), warnings
    # reporting only: the sample is still scored, with no error
    assert log.samples is not None and log.samples[0].error is None
    assert log.results is not None
    assert log.results.scores[0].metrics["accuracy"].value == 0.0


def test_stays_silent_on_a_normal_completion(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(reasoning_mod.logger, "warning", lambda message: warnings.append(message))

    _run([make_output(completion="4", stop_reason="stop", reasoning_tokens=3)], tmp_path)

    assert reasoning_exhausted_count() == 0
    assert not [warning for warning in warnings if "consumed by" in warning], warnings
