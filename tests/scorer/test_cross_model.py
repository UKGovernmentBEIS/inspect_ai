import math

import pytest

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentText
from inspect_ai.dataset import Sample
from inspect_ai.model import get_model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer import CORRECT, INCORRECT, cross_model_verifier


def _grader(text: str):
    return get_model(
        "mockllm/grader",
        custom_outputs=[
            ModelOutput.from_content("mockllm/grader", [ContentText(text=text)])
        ],
    )


def _actor(text: str = "Paris"):
    # a mock actor whose model name differs from the grader's
    return get_model(
        "mockllm/actor",
        custom_outputs=[
            ModelOutput.from_content("mockllm/actor", [ContentText(text=text)])
        ],
    )


def _qa_task(scorer):
    return Task(
        dataset=[Sample(input="What is the capital of France?", target="Paris")],
        scorer=scorer,
    )


@pytest.mark.parametrize(
    "grader_output, expected",
    [
        pytest.param("GRADE: C", CORRECT, id="correct"),
        pytest.param("GRADE: I", INCORRECT, id="incorrect"),
    ],
)
def test_distinct_models_grade_normally(grader_output: str, expected: str) -> None:
    # When actor and verifier are different models, grading proceeds and the
    # grade resolves to its value, exactly like model_graded_qa.
    task = _qa_task(cross_model_verifier(model=_grader(grader_output)))
    log = eval(task, model=_actor())[0]

    assert log.samples
    score = log.samples[0].scores["cross_model_verifier"]
    assert score.value == expected
    assert score.metadata is not None
    assert score.metadata["actor_verifier_distinct"] is True
    assert score.metadata["actor_model"] == "mockllm/actor"
    assert score.metadata["verifier_model"] == "mockllm/grader"


def test_same_model_errors_by_default() -> None:
    # Grading a model's own output is the failure this scorer exists to prevent;
    # by default it raises rather than producing a self-graded score.
    task = _qa_task(cross_model_verifier(model="mockllm/model"))
    log = eval(task, model="mockllm/model")[0]

    # the ValueError surfaces as a sample error (the eval does not crash)
    assert log.samples
    assert log.samples[0].error is not None
    assert "same as the model under evaluation" in log.samples[0].error.message


def test_same_model_warn_still_grades() -> None:
    # With on_same_model="warn" the scorer grades anyway but records that the
    # actor and verifier were not distinct.
    grader = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content("mockllm/model", [ContentText(text="GRADE: C")])
        ],
    )
    task = _qa_task(cross_model_verifier(model=grader, on_same_model="warn"))
    log = eval(task, model="mockllm/model")[0]

    assert log.samples
    score = log.samples[0].scores["cross_model_verifier"]
    assert score.value == CORRECT
    assert score.metadata is not None
    assert score.metadata["actor_verifier_distinct"] is False


def test_default_grader_role_falls_back_to_actor_and_errors() -> None:
    # The default model_role="grader" is unbound here, so the verifier resolves
    # to the model under evaluation — the same-model case must be caught.
    task = _qa_task(cross_model_verifier())
    log = eval(task, model="mockllm/model")[0]

    assert log.samples
    assert log.samples[0].error is not None


def test_bound_grader_role_is_used_and_distinct() -> None:
    # Binding a distinct grader role satisfies the actor≠verifier requirement.
    grader = _grader("GRADE: C")
    task = _qa_task(cross_model_verifier())
    log = eval(task, model=_actor(), model_roles={"grader": grader})[0]

    assert log.samples
    score = log.samples[0].scores["cross_model_verifier"]
    assert score.value == CORRECT
    assert score.metadata is not None
    assert score.metadata["actor_verifier_distinct"] is True


def test_grade_parse_failure_is_unscored() -> None:
    # A grader response with no parseable grade is unscored (NaN) but still
    # records the actor/verifier provenance.
    task = _qa_task(cross_model_verifier(model=_grader("looks right to me")))
    log = eval(task, model=_actor())[0]

    assert log.samples
    score = log.samples[0].scores["cross_model_verifier"]
    assert isinstance(score.value, float) and math.isnan(score.value)
    assert score.metadata is not None
    assert score.metadata["unscored_reason"] == "grade_parse_failure"
    assert score.metadata["actor_verifier_distinct"] is True
