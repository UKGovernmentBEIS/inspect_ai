from agieval import task_template

from inspect_ai import task


## Cloze Tasks
@task
def math(cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42):
    return task_template(
        dataset_name="math", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )
