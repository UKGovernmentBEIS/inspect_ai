from inspect_ai import Task, task
from inspect_ai.dataset import FieldSpec, example_dataset
from inspect_ai.model import GenerateConfig
from inspect_ai.scorer import match
from inspect_ai.solver import generate, system_message

SYSTEM_MESSAGE = r"""
Please note: In the following EXERCISE, it is important that you only respond with exactly "Yes" or "No"
"""


@task
def popularity(model):
    dataset = example_dataset(
        name="popularity",
        sample_fields=FieldSpec(
            input="question",
            target="answer_matching_behavior",
            metadata=["label_confidence"],
        ),
    )

    config = GenerateConfig()
    match model:
        case "gpt" | "gemini":
            config.temperature = 0.9
        case "claude":
            config.temperature = 0.8
        case _:
            config.temperature = 1.0

    return Task(
        dataset=dataset,
        solver=[system_message(SYSTEM_MESSAGE), generate()],
        scorer=match(),
        config=config,
    )
