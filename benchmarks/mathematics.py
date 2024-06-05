"""
Measuring Mathematical Problem Solving With the MATH Dataset

Dan Hendrycks, Collin Burns, Saurav Kadavath, Akul Arora,
Steven Basart, Eric Tang, Dawn Song, Jacob Steinhardt
https://arxiv.org/abs/2103.03874

Based on: https://github.com/openai/simple-evals/blob/main/math_eval.py
"""

import re

from inspect_ai import Task, task
from inspect_ai.dataset import FieldSpec, csv_dataset
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    AnswerPattern,
    Score,
    Target,
    accuracy,
    bootstrap_std,
    scorer,
)
from inspect_ai.solver import TaskState, generate, prompt_template

# setup for problem + instructions for providing answer
PROMPT_TEMPLATE = """
Solve the following math problem step by step. The last line of your response should be of the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the problem.

{prompt}

Remember to put your answer on its own line at the end in the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the problem, and you do not need to use a \\boxed command.
""".strip()


@task
def math(shuffle=True):
    return Task(
        dataset=csv_dataset(
            csv_file="https://openaipublic.blob.core.windows.net/simple-evals/math_test.csv",
            sample_fields=FieldSpec(input="Question", target="Answer"),
            shuffle=shuffle,
        ),
        plan=[
            prompt_template(PROMPT_TEMPLATE),
            generate(),
        ],
        scorer=expression_equivalance(),
        config=GenerateConfig(temperature=0.5),
    )


@scorer(metrics=[accuracy(), bootstrap_std()])
def expression_equivalance():
    async def score(state: TaskState, target: Target):
        # extract answer
        match = re.search(AnswerPattern.LINE, state.output.completion)
        if match:
            # ask the model to judge equivalance
            answer = match.group(1)
            prompt = EQUIVALANCE_TEMPLATE % (
                {"expression1": target.text, "expression2": answer}
            )
            result = await get_model().generate(prompt)

            # return the score
            correct = result.completion.lower() == "yes"
            return Score(
                value=CORRECT if correct else INCORRECT,
                answer=answer,
                explanation=state.output.completion,
            )
        else:
            return Score(
                value=INCORRECT,
                explanation="Answer not found in model output: "
                + f"{state.output.completion}",
            )

    return score


EQUIVALANCE_TEMPLATE = r"""
Look at the following two expressions (answers to a math problem) and judge whether they are equivalent. Only perform trivial simplifications

Examples:

  Expression 1: $2x+3$
  Expression 2: $3+2x$

Yes

  Expression 1: 3/2
  Expression 2: 1.5

Yes

  Expression 1: $x^2+2x+1$
  Expression 2: $y^2+2y+1$

No

  Expression 1: $x^2+2x+1$
  Expression 2: $(x+1)^2$

Yes

  Expression 1: 3245/5
  Expression 2: 649

No
(these are actually equal, don't mark them equivalent if you need to
do nontrivial simplifications)

  Expression 1: 2/(-3)
  Expression 2: -2/3

Yes
(trivial simplifications are allowed)

  Expression 1: 72 degrees
  Expression 2: 72

Yes
(give benefit of the doubt to units)

  Expression 1: 64
  Expression 2: 64 square feet

Yes
(give benefit of the doubt to units)

---

YOUR TASK


Respond with only "Yes" or "No" (without quotes). Do not include a rationale.

  Expression 1: %(expression1)s
  Expression 2: %(expression2)s
""".strip()
