from agieval import task_template

from inspect_ai import task


## English Tasks
@task()
def lsat_ar(cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42):
    return task_template(
        dataset_name="lsat-ar", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )


@task()
def lsat_lr(cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42):
    return task_template(
        dataset_name="lsat-lr", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )


@task()
def lsat_rc(cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42):
    return task_template(
        dataset_name="lsat-rc", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )


@task()
def sat_math(cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42):
    return task_template(dataset_name="sat-math", cot=cot, fewshot=fewshot)


@task()
def sat_en(cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42):
    return task_template(
        dataset_name="sat-en", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )


@task()
def sat_en_without_passage(
    cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42
):
    return task_template(
        dataset_name="sat-en-without-passage",
        cot=cot,
        fewshot=fewshot,
        fewshot_seed=fewshot_seed,
    )


@task()
def aqua_rat(cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42):
    return task_template(
        dataset_name="aqua-rat", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )


@task()
def logiqa_en(cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42):
    return task_template(
        dataset_name="logiqa-en", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )
