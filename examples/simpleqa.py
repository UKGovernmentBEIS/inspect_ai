from inspect_ai import Task, task
from inspect_ai.dataset import FieldSpec, hf_dataset
from inspect_ai.scorer import model_graded_qa
from inspect_ai.solver import generate


@task
def simpleqa():
    return Task(
        dataset=hf_dataset(
            "codelion/SimpleQA-Verified",
            split="train",
            sample_fields=FieldSpec(
                input="problem",
                target="answer",
            ),
        ),
        solver=generate(),
        scorer=model_graded_qa(),
    )
