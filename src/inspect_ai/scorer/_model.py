import re

from inspect_ai.model import ChatMessageUser, Model, get_model
from inspect_ai.solver import TaskState
from inspect_ai.util import resource

from ._metric import INCORRECT, Score
from ._metrics import accuracy, bootstrap_std
from ._scorer import Scorer, Target, scorer


@scorer(metrics=[accuracy(), bootstrap_std()])
def model_graded_fact(
    template: str | None = None,
    instructions: str | None = None,
    grade_pattern: str | None = None,
    partial_credit: bool = False,
    model: str | Model | None = None,
) -> Scorer:
    """Score a question/answer task with a fact response using a model.

    Args:
      template (str): Template for grading prompt. This template uses
        four variables: `question`, `criterion`, `answer`, and
        `instructions` (which is fed from the `instructions` parameter)
      instructions (str): Grading instructions. This should
        include a prompt for the model to answer (e.g. with
        with chain of thought reasoning) in a way that matches
        the specified `grade_pattern`, for example, the default
        `grade_pattern` looks for one of GRADE: C, GRADE: P, or
        GRADE: I).
      grade_pattern (str): Regex to extract the grade from the
        model response. Defaults to looking for e.g. GRADE: C
        The regex should have a single capture group that
        extracts exactly the letter C, P, or I.
      partial_credit (bool): Whether to allow for "partial" credit for
         answers (by default assigned a score of 0.5). Defaults
         to `False`. Note that this parameter is only used
         with the default `instructions` (as custom instructions
         provide their own prompts for grades).
      model (str | Model | none): Model to use for grading
         (by default the model being evaluated is used).
    """
    return model_graded_qa(
        template=template if template else DEFAULT_MODEL_GRADED_FACT_TEMPLATE,
        instructions=instructions,
        grade_pattern=grade_pattern,
        partial_credit=partial_credit,
        model=model,
    )


@scorer(metrics=[accuracy(), bootstrap_std()])
def model_graded_qa(
    template: str | None = None,
    instructions: str | None = None,
    grade_pattern: str | None = None,
    partial_credit: bool = False,
    model: str | Model | None = None,
) -> Scorer:
    """Score a question/answer task using a model.

    Args:
      template (str): Template for grading prompt. This template uses
        four variables: `question`, `criterion`, `answer`, and
        `instructions` (which is fed from the `instructions` parameter)
      instructions (str): Grading instructions. This should
        include a prompt for the model to answer (e.g. with
        with chain of thought reasoning) in a way that matches
        the specified `grade_pattern`, for example, the default
        `grade_pattern` looks for one of GRADE: C, GRADE: P, or
        GRADE: I.
      grade_pattern (str): Regex to extract the grade from the
        model response. Defaults to looking for e.g. GRADE: C
        The regex should have a single capture group that
        extracts exactly the letter C, P, I.
      partial_credit (bool): Whether to allow for "partial" credit for
        answers (by default assigned a score of 0.5). Defaults
        to `False`. Note that this parameter is only used
        with the default `instructions` (as custom instructions
        provide their own prompts for grades).
      model (str | Model | None): Model to use for grading
        (by default the model being evaluated is used).
    """
    # resolve model
    grader_model = get_model(model)

    # resolve grading template, instructions, and grade_pattern
    template = template if template else DEFAULT_MODEL_GRADED_QA_TEMPLATE
    grading_template = resource(template)
    instructions = (
        instructions if instructions else default_instructions(partial_credit)
    )
    grade_pattern = grade_pattern if grade_pattern else DEFAULT_GRADE_PATTERN

    async def score(state: TaskState, target: Target) -> Score:
        # format the scoring template
        score_prompt = grading_template.format(
            question=state.input_text,
            answer=state.output.completion,
            criterion=target.text,
            instructions=instructions,
        )

        # query the model for the score
        result = await grader_model.generate(score_prompt)

        # extract the grade
        match = re.search(grade_pattern, result.completion)
        if match:
            return Score(
                value=match.group(1),
                answer=state.output.completion,
                explanation=result.completion,
                metadata=dict(
                    grading=[
                        ChatMessageUser(content=score_prompt),
                        result.choices[0].message,
                    ]
                ),
            )
        else:
            return Score(
                value=INCORRECT,
                explanation="Grade not found in model output: "
                + f"{result.completion}",
            )

    return score


# these templates are based on the openai closedqa templates here:
# https://github.com/openai/evals/blob/main/evals/registry/modelgraded/closedqa.yaml
DEFAULT_MODEL_GRADED_QA_TEMPLATE = """
You are assessing a submitted answer on a given task based on a criterion. Here is the data:

[BEGIN DATA]
***
[Task]: {question}
***
[Submission]: {answer}
***
[Criterion]: {criterion}
***
[END DATA]

Does the submission meet the criterion?

{instructions}
"""

DEFAULT_MODEL_GRADED_FACT_TEMPLATE = """
You are comparing a submitted answer to an expert answer on a given question. Here is the data:

[BEGIN DATA]
************
[Question]: {question}
************
[Expert]: {criterion}
************
[Submission]: {answer}
************
[END DATA]

Compare the factual content of the submitted answer with the expert answer. Ignore any differences in style, grammar, or punctuation.

Does the submission contain the content in the expert answer?

{instructions}
"""


def default_instructions(partial_credit: bool) -> str:
    partial_letter = "P" if partial_credit else ""
    partial_prompt = '"P" for partially correct answers,' if partial_credit else ""
    return f"""
After assessing the submitted answer, reply with 'GRADE: $LETTER' (without quotes) where LETTER is one of C{partial_letter}I.  Please choose ONE option for the grade: either "C" for correct answers, {partial_prompt}or "I" for incorrect answers.

For example, after reviewing a correct answer you might write 'GRADE: C' or after reviewing an incorrect answer you might write 'GRADE: I'.

First, write out in a step by step manner your reasoning about the criterion to be sure that your conclusion is correct. Avoid simply stating the correct answers at the outset. Then, end with your answer formatted as 'GRADE: $LETTER' (without quotes) where LETTER is one of C{partial_letter}I.
"""


DEFAULT_GRADE_PATTERN = r"(?i)GRADE\s*:\s*([CPI])(.*)$"
"""Regex to extract the grade from the COT above."""
