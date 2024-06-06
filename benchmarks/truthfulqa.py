"""
TruthfulQA: Measuring How Models Mimic Human Falsehoods

Stephanie Lin, Jacob Hilton, Owain Evans
https://arxiv.org/abs/2109.07958v2

# Eval truthful QA with reference questions (mc1 - single true answer)
inspect eval truthfulqa.py

# Eval against the control questions (mc2 - multi-true answer)
inspect eval truthfulqa.py -T target=mc2
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import choice
from inspect_ai.solver import multiple_choice


# The dataset uses a binary list for each target, where 1 indicates an answer is
# correct and 0 is incorrect. For example, if there are three options and the
# second is correct, the target would be [0, 1, 0].
#
# This function converts that to a list of letters corresponding to the correct
# answers, which allows us to use the `choice("letter")` scorer.
#     e.g. [0, 1, 1] -> ["B", "C"]
def labels_to_positions(labels: list[int]) -> list[str]:
    return [chr(ord("A") + i) for i, label in enumerate(labels) if label == 1]


@task
def truthfulqa(target="mc1"):
    def record_to_sample(record):
        return Sample(
            input=record["question"],
            choices=record[f"{target}_targets"]["choices"],
            target=labels_to_positions(record[f"{target}_targets"]["labels"]),
        )

    dataset = hf_dataset(
        path="truthful_qa",
        name="multiple_choice",
        sample_fields=record_to_sample,
        split="validation",
        shuffle=True,
    )

    # As per the reference (), mc1 only has a single true answer whereas there
    # can be multiple true answers in mc2. See:
    # https://github.com/sylinrl/TruthfulQA/blob/fdd8ad1c0d00a478cf8b0bb41a3ad8378c16293b/README.md#multiple-choice
    if target == "mc1":
        multiple_correct = False
    else:
        multiple_correct = True

    return Task(
        dataset=dataset,
        plan=[multiple_choice(multiple_correct=multiple_correct, shuffle=True)],
        scorer=choice(),
    )
