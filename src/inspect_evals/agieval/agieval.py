"""
AGIEval: A Human-Centric Benchmark for Evaluating Foundation Models

Wanjun Zhong, Ruixiang Cui, Yiduo Guo, Yaobo Liang, Shuai Lu, Yanlin Wang,
Amin Saied, Weizhu Chen and Nan Duan
https://arxiv.org/pdf/2304.06364

# to run a specific task (eg: sat_math)
inspect eval inspect_evals/agie_sat_math

# to run agieval (english group)
inspect eval inspect_evals/agieval

# to run agieval_en with fewshots and/or Chain of Thoughts
inspect eval inspect_evals/agieval -T fewshot=5 cot=True

"""

from inspect_ai import Task, task

from .utils import task_template


## English Tasks
@task
def agie_lsat_ar(
    cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42
) -> Task:
    """
    Inspect Task implementation for AGIE LSAT Analytics

    Args:
        cot (bool): Whether to use chain of thought
        fewshot (int): Number of fewshot samples
        fewshot_seed (int): Seed used to determine fewshot samples
    """
    return task_template(
        dataset_name="lsat-ar", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )


@task
def agie_lsat_lr(
    cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42
) -> Task:
    """
    Inspect Task implementation for AGIE LSAT Logic

    Args:
        cot (bool): Whether to use chain of thought
        fewshot (int): Number of fewshot samples
        fewshot_seed (int): Seed used to determine fewshot samples
    """
    return task_template(
        dataset_name="lsat-lr", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )


@task
def agie_lsat_rc(
    cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42
) -> Task:
    """
    Inspect Task implementation for AGIE LSAT Reading

    Args:
        cot (bool): Whether to use chain of thought
        fewshot (int): Number of fewshot samples
        fewshot_seed (int): Seed used to determine fewshot samples
    """
    return task_template(
        dataset_name="lsat-rc", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )


@task
def agie_sat_math(
    cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42
) -> Task:
    """
    Inspect Task implementation for AGIE SAT Math

    Args:
        cot (bool): Whether to use chain of thought
        fewshot (int): Number of fewshot samples
        fewshot_seed (int): Seed used to determine fewshot samples
    """
    return task_template(dataset_name="sat-math", cot=cot, fewshot=fewshot)


@task
def agie_sat_en(
    cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42
) -> Task:
    """
    Inspect Task implementation for AGIE SAT English

    Args:
        cot (bool): Whether to use chain of thought
        fewshot (int): Number of fewshot samples
        fewshot_seed (int): Seed used to determine fewshot samples
    """
    return task_template(
        dataset_name="sat-en", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )


@task
def agie_sat_en_without_passage(
    cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42
) -> Task:
    """
    Inspect Task implementation for AGIE SAT English without passsages

    Args:
        cot (bool): Whether to use chain of thought
        fewshot (int): Number of fewshot samples
        fewshot_seed (int): Seed used to determine fewshot samples
    """
    return task_template(
        dataset_name="sat-en-without-passage",
        cot=cot,
        fewshot=fewshot,
        fewshot_seed=fewshot_seed,
    )


@task
def agie_aqua_rat(
    cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42
) -> Task:
    """
    Inspect Task implementation for AGIE GRE/GMAT Math

    Args:
        cot (bool): Whether to use chain of thought
        fewshot (int): Number of fewshot samples
        fewshot_seed (int): Seed used to determine fewshot samples
    """
    return task_template(
        dataset_name="aqua-rat", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )


@task()
def agie_logiqa_en(
    cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42
) -> Task:
    """
    Inspect Task implementation for AGIE Civil Service Exam Logic

    Args:
        cot (bool): Whether to use chain of thought
        fewshot (int): Number of fewshot samples
        fewshot_seed (int): Seed used to determine fewshot samples
    """
    return task_template(
        dataset_name="logiqa-en", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )
