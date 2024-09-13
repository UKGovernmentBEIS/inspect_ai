"""
Measuring Mathematical Problem Solving With the MATH Dataset

Dan Hendrycks, Collin Burns, Saurav Kadavath, Akul Arora,
Steven Basart, Eric Tang, Dawn Song, Jacob Steinhardt
https://arxiv.org/abs/2103.03874

Based on:
1. https://github.com/openai/simple-evals/blob/main/math_eval.py
2. https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/tasks/minerva_math
3. https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/tasks/hendrycks_math

# default run - zero shot
inspect eval mathematics/mathematics.py

# run with fewshot samples
inspect eval mathematics/mathematics.py -T fewshot=4

# run for specific levels and/or subjects
inspect eval mathematics/mathematics.py -T levels=4,5 -T subjects=algebra

# run using a different grader model
inspect eval mathematics/mathematics.py -T grader_model=openai/gpt-4o
"""

from utils import (
    filter_dataset,
    record_to_sample,
    sample_to_fewshot,
    score_helper,
)

from inspect_ai import Task, task
from inspect_ai.dataset import hf_dataset
from inspect_ai.model import GenerateConfig, Model
from inspect_ai.scorer import (
    Target,
    accuracy,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState, generate, prompt_template, system_message

# Few-shot prompt template partially based on https://arxiv.org/pdf/2206.14858 - Appendix D.2
SYSTEM_W_EXAMPLES_PROMPT_TEMPLATE = """
You will be asked to solve a math problem. Some examples of problems and solutions are provided below.

{examples}
""".strip()

# Setup for problem + instructions for providing answer
USER_PROMPT_TEMPLATE = """
Solve the following math problem step by step. The last line of your response should be of the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the problem.

{prompt}

Remember to put your answer on its own line at the end in the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the problem, and you do not need to use a \\boxed command.
""".strip()


@task
def math(
    levels: list = [],
    subjects: list = [],
    fewshot: int = 0,
    fewshot_seed: int = 42,
    grader_model: str | None = None,
):
    dataset = hf_dataset(
        "hendrycks/competition_math",
        split="test",
        trust=True,
        sample_fields=record_to_sample,
        shuffle=True,
    )
    # Subset the data based on levels and/or subjects
    dataset = filter_dataset(dataset=dataset, levels=levels, subjects=subjects)

    return Task(
        dataset=dataset,
        plan=build_plan(fewshot=fewshot, fewshot_seed=fewshot_seed),
        scorer=[
            expression_equivalance(model=grader_model),
            expression_exact_match(),
            expression_exact_match_sympy(),
        ],
        config=GenerateConfig(temperature=0.5),
    )


@scorer(metrics=[accuracy(), stderr()])
def expression_equivalance(model: str | Model | None):
    async def score(state: TaskState, target: Target):
        return await score_helper(
            state=state,
            target=target,
            model=model,
            exact_match=False,
        )

    return score


# Exact match using sympy based on: https://arxiv.org/pdf/2206.14858
@scorer(metrics=[accuracy(), stderr()])
def expression_exact_match_sympy():
    async def score(state: TaskState, target: Target):
        return await score_helper(
            state=state,
            target=target,
            exact_match=True,
            use_sympy=True,
        )

    return score


# Exact match based on:
# https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/tasks/hendrycks_math/utils.py#L36
@scorer(metrics=[accuracy(), stderr()])
def expression_exact_match():
    async def score(state: TaskState, target: Target):
        return await score_helper(
            state=state,
            target=target,
            exact_match=True,
            use_sympy=False,
        )

    return score


def build_plan(
    fewshot: int,
    fewshot_seed: int,
) -> list:
    """Builds plan using various solvers for the MATH task.

    Arguments:
        fewshot (int): Number of few shot examples to use.
        fewshot_seed (int): Random seed for sampling few shot examples.
    """
    plan = [prompt_template(USER_PROMPT_TEMPLATE), generate()]

    if fewshot:
        fewshot_samples = hf_dataset(
            "hendrycks/competition_math",
            split="train",
            trust=True,
            sample_fields=record_to_sample,
            shuffle=True,
            seed=fewshot_seed,
            limit=fewshot,
        )
        plan.insert(
            0,
            system_message(
                SYSTEM_W_EXAMPLES_PROMPT_TEMPLATE.format(
                    examples="\n\n".join(
                        [sample_to_fewshot(sample=sample) for sample in fewshot_samples]
                    )
                )
            ),
        )

    return plan
