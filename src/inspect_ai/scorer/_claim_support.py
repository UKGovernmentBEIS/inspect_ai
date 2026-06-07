from inspect_ai.model._model import Model, get_model
from inspect_ai.solver._task_state import TaskState

from ._metric import CORRECT, INCORRECT, NOANSWER, PARTIAL, Score
from ._metrics import accuracy, stderr
from ._model import chat_history
from ._scorer import Scorer, scorer
from ._target import Target

DEFAULT_CLAIM_SUPPORT_TEMPLATE = """
You are assessing whether a claimed answer is actually supported by what the
conversation transcript shows. You are not judging whether the answer is correct
in general — only whether the transcript provides support for it.

Here is the transcript:

{transcript}

Here is the claimed answer being assessed:

{answer}

Assess support on this scale:
- SUPPORTED: the transcript clearly substantiates the claimed answer.
- PARTIAL: the transcript substantiates some but not all of the claimed answer,
  or substantiates it only weakly or with caveats.
- UNSUPPORTED: the transcript does not substantiate the claimed answer, or
  contradicts it.

Important boundary: do not treat absence of evidence as support. A claim that
something did NOT happen (e.g. "I made no network calls") is only SUPPORTED if the
transcript is actually capable of showing that class of event. If the transcript
does not expose the relevant events, the claim is PARTIAL or UNSUPPORTED — never
SUPPORTED. Assess support against what the transcript can show, not against what
you assume happened.

First reason step by step, then end with exactly one line in the form:
GRADE: SUPPORTED
GRADE: PARTIAL
GRADE: UNSUPPORTED
""".strip()


@scorer(metrics=[accuracy(), stderr()])
def claim_support(
    template: str | None = None,
    model: str | Model | None = None,
) -> Scorer:
    """Score whether a claimed answer is supported by the transcript.

    Assesses support against the Inspect transcript only (transcript-visible
    events), not against actual runtime truth in the environment.

    Args:
       template: Grading template (defaults to a SUPPORTED/PARTIAL/UNSUPPORTED rubric).
       model: Model to use for grading (defaults to the model being evaluated).
    """
    grader_template = template or DEFAULT_CLAIM_SUPPORT_TEMPLATE

    async def score(state: TaskState, target: Target) -> Score:
        grader_model = get_model(model)
        transcript = chat_history(state)
        answer = state.output.completion

        prompt = grader_template.replace("{transcript}", transcript).replace(
            "{answer}", answer
        )
        result = await grader_model.generate(prompt)
        grade = _parse_grade(result.completion)

        if grade is None:
            return Score(
                value=NOANSWER,
                answer=answer,
                explanation=result.completion,
                metadata={"grading": "PARSE_FAIL", "grader_prompt": prompt},
            )

        value = {
            "SUPPORTED": CORRECT,
            "PARTIAL": PARTIAL,
            "UNSUPPORTED": INCORRECT,
        }[grade]

        return Score(
            value=value,
            answer=answer,
            explanation=result.completion,
            metadata={"grading": grade, "grader_prompt": prompt},
        )

    return score


def _parse_grade(output: str) -> str | None:
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line.startswith("GRADE:"):
            token = line.removeprefix("GRADE:").strip().upper()
            if token in ("SUPPORTED", "PARTIAL", "UNSUPPORTED"):
                return token
    return None
