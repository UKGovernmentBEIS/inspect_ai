import re
from typing import Callable

from inspect_ai.model import Model, ModelOutput, get_model
from inspect_ai.solver import TaskState
from inspect_ai.util import resource

from ._common import match_str
from ._metric import CORRECT, INCORRECT, Score
from ._metrics import accuracy, bootstrap_std
from ._scorer import Scorer, Target, scorer

# this is based on the openai cot_classify template here:
# https://github.com/openai/evals/blob/main/evals/elsuite/modelgraded/classify_utils.py
COT_ANSWER = """
First, write out in a step by step manner your reasoning about the criterion
to be sure that your conclusion is correct. Avoid simply stating the correct
answers at the outset. Then print only the single character "Y" or "N"
(without quotes or punctuation) on its own line corresponding to the correct
answer. At the end, repeat just the letter again by itself on a new line.

Reasoning:
"""

# these templates are based on the openai closedqa templates here:
# https://github.com/openai/evals/blob/main/evals/registry/modelgraded/closedqa.yaml
DEFAULT_MODEL_GRADED_QA_TEMPLATE = f"""
You are assessing a submitted answer on a given task based on a criterion. Here is the data:

[BEGIN DATA]
***
[Task]: {{question}}
***
[Submission]: {{answer}}
***
[Criterion]: {{criterion}}
***
[END DATA]

Does the submission meet the criterion?

{COT_ANSWER}
"""

DEFAULT_MODEL_GRADED_FACT_TEMPLATE = f"""
You are comparing a submitted answer to an expert answer on a given question. Here is the data:

[BEGIN DATA]
************
[Question]: {{question}}
************
[Expert]: {{criterion}}
************
[Submission]: {{answer}}
************
[END DATA]

Compare the factual content of the submitted answer with the expert answer.
Ignore any differences in style, grammar, or punctuation.

Does the submission contain the content in the expert answer?

{COT_ANSWER}
"""


@scorer(metrics=[accuracy(), bootstrap_std()])
def model_graded_fact(
    template: str = DEFAULT_MODEL_GRADED_FACT_TEMPLATE,
    model: str | Model | None = None,
) -> Scorer:
    """Score a question/answer task with a fact response using a model.

    Args:
      template: Template for grading prompt. This template uses
         three variables: `question`, `criterion`, and `answer`.
      model (str | Model | none): Model to use for grading
         (by default the model being evaluated is used).
    """

    def extractor(output: ModelOutput) -> str:
        if match_str(output.completion, "Y", location="end"):
            return CORRECT
        else:
            return INCORRECT

    return model_graded_qa(template=template, extractor=extractor, model=model)


@scorer(metrics=[accuracy(), bootstrap_std()])
def model_graded_qa(
    template: str = DEFAULT_MODEL_GRADED_QA_TEMPLATE,
    extractor: Callable[[ModelOutput], str] | None = None,
    model: str | Model | None = None,
) -> Scorer:
    """Score a question/answer task using a model.

    Args:
       template: Template for grading prompt. This template uses
         three variables: `question`, `criterion`, and `answer`.
       extractor: Function to extract grade from the grader
         model output (by default looks for string "Grade: ")
       model (str | Model | none): Model to use for grading
         (by default the model being evaluated is used).
    """
    # resolve model
    grader_model = get_model(model)

    # resolve grading template
    grading_template = resource(template)

    # provide default scoring function if required
    extractor = extractor if extractor else extract_grade

    async def score(state: TaskState, target: Target) -> Score:
        # format the scoring template
        score_prompt = grading_template.format(
            question=state.input_text,
            answer=state.output.completion,
            criterion=target.text,
        )

        # query the model for the score
        score = await grader_model.generate(score_prompt)

        # return score (reduced by extractor) with explanation
        return Score(
            value=extractor(score),
            explanation=score.completion,
        )

    return score


def extract_grade(output: ModelOutput) -> str:
    text: str = output.completion
    match = re.search("Grade: .", text)
    if match is None:
        return "Error"
    else:
        return text[match.end() - 1]
