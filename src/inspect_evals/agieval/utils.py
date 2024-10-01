import re
from typing import Any

from inspect_ai import Task
from inspect_ai.dataset import Dataset, Sample, json_dataset
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    AnswerPattern,
    Score,
    Scorer,
    Target,
    accuracy,
    choice,
    scorer,
    stderr,
)
from inspect_ai.solver import (
    Solver,
    TaskState,
    chain,
    generate,
    multiple_choice,
    prompt_template,
)

ROOT_URL = "https://raw.githubusercontent.com/ruixiangcui/AGIEval/84ab72d94318290aad2e4ec820d535a95a1f7552/data/v1_1/"

EN_TASK = [
    "lsat-ar",
    "lsat-lr",
    "lsat-rc",
    "sat-math",
    "sat-en",
    "sat-en-without-passage",
    "aqua-rat",
    "logiqa-en",
    "math",
]

CLOZE_TASK = [
    "math",
]

# setup for problem + instructions for providing answer
COT_STRING_EN = r"""Think step by step before answering."""

# The cloze template is copied from the mathematic benchmark in inspect. I have added the possibility to add chain of though in the prompt.
# https://github.com/UKGovernmentBEIS/inspect_ai/blob/52688ccdc88b1dee6abaaa1144e731257b637f6b/benchmarks/mathematics.py

CLOZE_TEMPLATE_EN = r"""
{fewshot_string}

Solve the following math problem step by step. The last line of your response should be of the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the problem. {cot_string}

{prompt}

Remember to put your answer on its own line at the end in the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the problem, and you do not need to use a \\boxed command.
""".strip()

MULTIPLE_CHOICE_TEMPLATE_EN = r"""
{fewshot_string}

Answer the following multiple choice question. The last line of your response should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is one of {letters}. {cot_string}

{question}

{choices}
""".strip()

CHOICE_PREFIX = ["(A)", "(B)", "(C)", "(D)", "(E)"]


def record_to_sample(record: dict[str, Any]) -> Sample:
    input_str = (
        str(record["question"])
        if record["passage"] is None
        else f"{record['passage']}\n\n{record['question']}"
    )

    # the target is different if the task is a MCQ (label) or a coze test (answer)
    target_str = str(record["label"]) if record["label"] else record["answer"]

    # the letter are in the choice string (4 first character) and need to be removed
    choices_list = [o[3:] for o in record["options"]] if record["options"] else None

    return Sample(
        input=input_str,
        choices=choices_list,
        target=target_str,
        metadata=record["other"] if record["other"] else {},
    )


def agieval_solver(
    dataset_name: str,
    cot: bool = False,
    fewshot_samples: Dataset | None = None,
) -> Solver:
    # Determine the template for the tasks in the proper language and for the correct type (MCQ, Cloze)
    if dataset_name in EN_TASK:
        template_prompt = (
            CLOZE_TEMPLATE_EN
            if dataset_name in CLOZE_TASK
            else MULTIPLE_CHOICE_TEMPLATE_EN
        )
        # set the Chain of Thought (CoT) string
        cot_string = COT_STRING_EN if cot else ""

        # set few-shots if needed
        fewshot_string = fewshot_to_str(fewshot_samples) if fewshot_samples else ""

    else:
        # Raise an error if the task name is not recognized
        raise ValueError(f"Dataset '{dataset_name}' not recognized.")

    # Create a solver according to the task type and options (cot, fewshots...)
    if dataset_name in CLOZE_TASK:
        template_prompt = template_prompt.format(
            prompt="{prompt}", cot_string=cot_string, fewshot_string=fewshot_string
        )

        solver = chain(
            [
                prompt_template(template=template_prompt),
                generate(),
            ]
        )
    else:
        template_prompt = template_prompt.format(
            letters="{letters}",
            cot_string=cot_string,
            question="{question}",
            choices="{choices}",
            fewshot_string=fewshot_string,
        )

        solver = chain(
            [
                multiple_choice(template=template_prompt),
                generate(),
            ]
        )

    return solver


def task_template(
    dataset_name: str,
    cot: bool = False,
    fewshot: int | None = None,
    fewshot_seed: int = 42,
) -> Task:
    # Load the dataset
    dataset = json_dataset(
        json_file=f"{ROOT_URL}{dataset_name}.jsonl",
        name=dataset_name,
        sample_fields=record_to_sample,
    )

    # Randomly chose the few-shots examples if specified
    if fewshot:
        fewshot_samples = dataset
        fewshot_samples.shuffle(seed=fewshot_seed)
        dataset = fewshot_samples[fewshot:]
        fewshot_samples = fewshot_samples[:fewshot]
    else:
        fewshot_samples = None

    # create a solver according to the type of task and language
    solver = agieval_solver(
        dataset_name=dataset_name, cot=cot, fewshot_samples=fewshot_samples
    )

    # define the scorer according to the task type
    scorer = expression_equivalence() if dataset_name in CLOZE_TASK else choice()

    return Task(
        dataset=dataset,
        solver=solver,
        scorer=scorer,
        # from source paper 4.2.4: Implementation Details
        config=GenerateConfig(
            temperature=0, max_tokens=2048, frequency_penalty=0, top_p=1
        ),
    )


def fewshot_to_str(fewshot_samples: Dataset) -> str:
    """Generate a formatted string from a Dataset of samples to be used as few shot examples"""
    return convert_math_str(
        "\n\nHere are the answers for the questions in exams.\n\n"
        + "".join(
            [
                f'\n\nPROBLEM:\n\n{s.input}\n\n{choices_to_str(s.choices) if s.choices else ""}\n\nANSWER: {s.target}'
                for s in fewshot_samples
            ]
        )
    )


def choices_to_str(choices: list[str]) -> str:
    """Generate formatted strings from choices"""
    return "".join(
        [f"{prefix} {choice}\n\n" for prefix, choice in zip(CHOICE_PREFIX, choices)]
    ).strip()


def convert_math_str(input_string: str) -> str:
    """This formatting escape curly brackets from maths questions to avoid conflict with the format method"""
    return input_string.replace("{", "{{").replace("}", "}}")


# adapt scorer to the type of task
# # https://github.com/UKGovernmentBEIS/inspect_ai/blob/52688ccdc88b1dee6abaaa1144e731257b637f6b/benchmarks/mathematics.py
@scorer(metrics=[accuracy(), stderr()])
def expression_equivalence() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
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


EQUIVALENCE_TEMPLATE = r"""
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
