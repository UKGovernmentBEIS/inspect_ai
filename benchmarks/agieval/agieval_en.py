"""
AGIEval: A Human-Centric Benchmark for Evaluating Foundation Models

Wanjun Zhong, Ruixiang Cui, Yiduo Guo, Yaobo Liang, Shuai Lu, Yanlin Wang,
Amin Saied, Weizhu Chen and Nan Duan
https://arxiv.org/pdf/2304.06364

# to run a specific task (eg: sat_math)
inspect eval agieval_en.py@sat_math

# to run agieval (english group)
inspect eval agieval_en.py

# to run agieval_en with fewshots and/or Chain of Thoughts
inspect eval agieval_en.py  -T fewshot=5 cot=True

"""

from agieval import task_template

from inspect_ai import task


## English Tasks
@task
def lsat_ar(cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42):
    return task_template(
        dataset_name="lsat-ar", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )


@task
def lsat_lr(cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42):
    return task_template(
        dataset_name="lsat-lr", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )


@task
def lsat_rc(cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42):
    return task_template(
        dataset_name="lsat-rc", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )


@task
def sat_math(cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42):
    return task_template(dataset_name="sat-math", cot=cot, fewshot=fewshot)


@task
def sat_en(cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42):
    return task_template(
        dataset_name="sat-en", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )


@task
def sat_en_without_passage(
    cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42
):
    return task_template(
        dataset_name="sat-en-without-passage",
        cot=cot,
        fewshot=fewshot,
        fewshot_seed=fewshot_seed,
    )


@task
def aqua_rat(cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42):
    return task_template(
        dataset_name="aqua-rat", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )


@task()
def logiqa_en(cot: bool = False, fewshot: int | None = None, fewshot_seed: int = 42):
    return task_template(
        dataset_name="logiqa-en", cot=cot, fewshot=fewshot, fewshot_seed=fewshot_seed
    )
