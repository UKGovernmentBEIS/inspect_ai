import pytest

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentText
from inspect_ai.dataset import Sample
from inspect_ai.model._model import get_model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer import CORRECT, INCORRECT, NOANSWER, PARTIAL, claim_support


def _mock(text: str):
    return get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content("mockllm/model", [ContentText(text=text)])
        ],
    )


def _run(grader_output: str, subject_answer: str):
    """Run a single-sample eval; grader and subject are independent mock models."""
    task = Task(
        dataset=[Sample(input="Did the run satisfy the claim?", target="")],
        scorer=claim_support(model=_mock(grader_output)),
    )
    log = eval(task, model=_mock(subject_answer))[0]
    assert log.samples
    scores = log.samples[0].scores
    assert scores is not None
    return scores["claim_support"]


@pytest.mark.parametrize(
    ["grader_output", "expected"],
    [
        pytest.param("Reasoning.\nGRADE: SUPPORTED", CORRECT, id="supported_correct"),
        pytest.param("Reasoning.\nGRADE: PARTIAL", PARTIAL, id="partial_partial"),
        pytest.param(
            "Reasoning.\nGRADE: UNSUPPORTED", INCORRECT, id="unsupported_incorrect"
        ),
    ],
)
def test_claim_support_grade_mapping(grader_output, expected):
    score = _run(grader_output, "The transcript shows the file was read.")
    assert score.value == expected


def test_claim_support_parse_failure_returns_noanswer():
    # No parseable GRADE: line → NOANSWER, but the subject answer must still be
    # preserved on the score (matching the model_graded convention, #4025).
    subject_answer = "The file was read successfully."
    score = _run("I think this looks fine, but no verdict here.", subject_answer)
    assert score.value == NOANSWER
    assert score.answer == subject_answer
    assert score.metadata is not None
    assert score.metadata["grading"] == "PARSE_FAIL"


def test_claim_support_handles_literal_braces():
    # Regression: the scorer fills the template with str.replace (not str.format),
    # so transcript/answer containing literal { } must not raise.
    subject_answer = 'Returned JSON {"calls": [{"id": 1}], "ok": true}.'
    score = _run("Looks substantiated.\nGRADE: SUPPORTED", subject_answer)
    assert score.value == CORRECT
    assert score.answer == subject_answer


def test_claim_support_absence_boundary_reaches_grader():
    # The absence-of-evidence boundary must actually reach the grader prompt, not
    # just exist in the template constant — and an UNSUPPORTED verdict on an
    # unprovable negative maps to INCORRECT.
    score = _run(
        "The transcript cannot show network activity, so this is unprovable.\n"
        "GRADE: UNSUPPORTED",
        "I made no network calls during this task.",
    )
    assert score.value == INCORRECT
    assert "absence of evidence" in score.metadata["grader_prompt"]
