import os
from pathlib import Path

import pytest
from test_helpers.tasks import popularity

from inspect_ai import Task, eval, eval_retry, task
from inspect_ai._eval.loader import shuffle_requested, shuffle_seed
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog
from inspect_ai.solver import solver


def test_sample_shuffle():
    check_sample_shuffle()


def test_sample_shuffle_limit():
    check_sample_shuffle(limit=20)


def test_sample_shuffle_no_id():
    with pytest.raises(ValueError):
        check_sample_shuffle(sample_id=[1, 2, 3, 4, 5])


def test_sample_no_shuffle():
    ids = range(100, 200)
    dataset = [Sample(id=id, input=f"Do you like the id '{id}'?") for id in ids]
    log1 = eval(Task(dataset=dataset), model="mockllm/model", limit=20)[0]
    log2 = eval(Task(dataset=dataset), model="mockllm/model", limit=20)[0]
    check_samples_equal(log1, log2)


def check_sample_shuffle(**kwargs):
    log1 = eval(popularity(), model="mockllm/model", sample_shuffle=42, **kwargs)[0]
    log2 = eval(popularity(), model="mockllm/model", sample_shuffle=42, **kwargs)[0]
    check_samples_equal(log1, log2)


def check_samples_equal(log1: EvalLog, log2: EvalLog) -> None:
    assert log1.samples and log2.samples
    assert [sample.input for sample in log1.samples] == [
        sample.input for sample in log2.samples
    ]


# `0` is a seed like any other int, and `False` means "no shuffle". The two
# compare equal in Python, so eval() and eval_retry() must resolve them the
# same way or a retry reruns a different set of samples. See issue #6203.


def test_shuffle_requested_semantics():
    assert shuffle_requested(None) is False
    assert shuffle_requested(False) is False
    assert shuffle_requested(True) is True
    assert shuffle_requested(0) is True
    assert shuffle_requested(42) is True


def test_shuffle_seed_semantics():
    assert shuffle_seed(True) is None
    assert shuffle_seed(0) == 0
    assert shuffle_seed(42) == 42


def test_sample_shuffle_seed_zero_shuffles():
    dataset = [Sample(id=id, input=f"q{id}") for id in range(100, 200)]
    plain = eval(Task(dataset=dataset), model="mockllm/model", limit=20)[0]
    seeded = eval(
        Task(dataset=dataset), model="mockllm/model", sample_shuffle=0, limit=20
    )[0]
    assert plain.samples and seeded.samples
    assert [s.id for s in plain.samples] != [s.id for s in seeded.samples]


def test_sample_shuffle_seed_zero_is_deterministic():
    dataset = [Sample(id=id, input=f"q{id}") for id in range(100, 200)]
    log1 = eval(
        Task(dataset=dataset), model="mockllm/model", sample_shuffle=0, limit=20
    )[0]
    log2 = eval(
        Task(dataset=dataset), model="mockllm/model", sample_shuffle=0, limit=20
    )[0]
    check_samples_equal(log1, log2)


def test_sample_shuffle_false_does_not_shuffle():
    dataset = [Sample(id=id, input=f"q{id}") for id in range(100, 200)]
    plain = eval(Task(dataset=dataset), model="mockllm/model", limit=20)[0]
    explicit = eval(
        Task(dataset=dataset), model="mockllm/model", sample_shuffle=False, limit=20
    )[0]
    check_samples_equal(plain, explicit)


@solver
def _fail_on_sample_2():
    async def solve(state, generate):
        if os.environ.get("INSPECT_TEST_FAIL") == "1" and state.sample_id == 2:
            raise RuntimeError("transient failure")
        return state

    return solve


@task
def shuffle_retry_task():
    return Task(
        dataset=[Sample(id=id, input=f"q{id}") for id in range(1, 21)],
        solver=_fail_on_sample_2(),
    )


def test_eval_retry_reruns_same_samples_with_seed_zero(tmp_path: Path):
    """A retry must rerun the samples the original ran, not a fresh selection."""
    task_spec = f"{__file__}@shuffle_retry_task"

    os.environ["INSPECT_TEST_FAIL"] = "1"
    try:
        original = eval(
            task_spec,
            model="mockllm/model",
            sample_shuffle=0,
            limit=4,
            log_dir=str(tmp_path),
            display="none",
        )[0]
    finally:
        os.environ.pop("INSPECT_TEST_FAIL", None)

    retried = eval_retry(original, log_dir=str(tmp_path), display="none")[0]

    assert original.samples and retried.samples
    assert sorted(s.id for s in original.samples) == sorted(
        s.id for s in retried.samples
    )
