from inspect_ai import Task, task

from .utils import task_template


## Cloze Tasks
@task
def agie_math(
    cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42
) -> Task:
    """
    Inspect Task implementation for AGIE Cloze Math

    Args:
        cot (bool): Whether to use chain of thought
        fewshot (int): Number of fewshot samples
        fewshot_seed (int): Seed used to determine fewshot samples
    """
    return task_template(
        dataset_name="math", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )
