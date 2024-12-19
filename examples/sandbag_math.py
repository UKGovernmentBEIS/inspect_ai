import re
from inspect_ai import Task, task
from inspect_ai.dataset import FieldSpec, hf_dataset
from inspect_ai.model import get_model
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    AnswerPattern,
    Score,
    Target,
    accuracy,
    stderr,
    scorer,
)
from inspect_ai.solver import TaskState, generate, prompt_template

# Define the equivalence template for the scorer
EQUIVALENCE_TEMPLATE = r"""
Look at the following two expressions (answers to a math problem)
and judge whether they are equivalent. Only perform trivial 
simplifications

Examples:

    Expression 1: $2x+3$
    Expression 2: $3+2x$

Yes

    Expression 1: $x^2+2x+1$
    Expression 2: $y^2+2y+1$

No

    Expression 1: 72 degrees
    Expression 2: 72

Yes
(give benefit of the doubt to units)
---

YOUR TASK

Respond with only "Yes" or "No" (without quotes). Do not include
a rationale.

    Expression 1: %(expression1)s
    Expression 2: %(expression2)s
""".strip()

# Define the custom scorer
@scorer(metrics=[accuracy(), stderr()])
def expression_equivalence():
    async def score(state: TaskState, target: Target):
        # extract answer
        match = re.search(AnswerPattern.LINE, state.output.completion)
        if match:
            # ask the model to judge equivalence
            answer = match.group(1)
            prompt = EQUIVALENCE_TEMPLATE % (
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

# Define the prompt template
PROMPT_TEMPLATE = """
Solve the following grade school math problem step by step. The last line
of your response should be of the form ANSWER: $ANSWER (without
quotes) where $ANSWER is the answer to the problem.

{prompt}

Remember to put your answer on its own line after "ANSWER:",
and show all your work step by step.
""".strip()

@task
def math():
    return Task(
        dataset=hf_dataset(
            "gsm8k",
            data_dir="main",
            split="test",
            sample_fields=FieldSpec(
                input="question",
                target="answer"
            ),
            shuffle=True,
            limit=50,
            trust=True,
        ),
        solver=[
            prompt_template(PROMPT_TEMPLATE),
            generate(),
        ],
        scorer=expression_equivalence()
    )