import pytest
from test_helpers.tasks import popularity

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog


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
