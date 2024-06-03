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

PROMPT_TEMPLATE = """
Solve the following math problem step by step. The last line of your response should be of the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the problem.

{prompt}

Remember to put your answer on its own line at the end in the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the problem, and you do not need to use a \\boxed command.
""".strip()


@task
def math(shuffle=True):
    return Task(
        dataset=csv_dataset(
            csv_file="datasets/math_exampel.csv",
            sample_fields=FieldSpec(
                input="Question", 
                target="Answer"
            ),
            shuffle=shuffle,
        ),
        plan=[
            prompt_template(PROMPT_TEMPLATE),
            generate(),
        ],
        scorer=expression_equivalence(),
        config=GenerateConfig(temperature=0.5),
    )