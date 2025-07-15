import pytest

from inspect_ai import Task, eval
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.dataset import Sample
from inspect_ai.log._log import EvalLog


def test_sample_id():
    task = Task(dataset=[Sample(id=id, input=f"Input for {id}") for id in range(0, 10)])
    log = eval(task, sample_id=5, model="mockllm/model")[0]
    assert log.samples
    assert len(log.samples) == 1
    assert log.samples[0].id == 5

    log = eval(task, sample_id=[5, 9], model="mockllm/model")[0]
    assert log.samples
    assert len(log.samples) == 2
    assert log.samples[0].id == 5
    assert log.samples[1].id == 9

    task = Task(
        dataset=[
            Sample(id=f"sample-{id}", input=f"Input for {id}") for id in range(0, 10)
        ]
    )
    log = eval(task, sample_id="sample-5", model="mockllm/model")[0]
    assert log.samples
    assert len(log.samples) == 1
    assert log.samples[0].id == "sample-5"

    def check_multiple_samples(log: EvalLog) -> None:
        assert log.samples
        assert len(log.samples) == 2
        assert log.samples[0].id == "sample-5"
        assert log.samples[1].id == "sample-6"

    log = eval(task, sample_id=["sample-5", "sample-6"], model="mockllm/model")[0]
    check_multiple_samples(log)

    log = eval(task, sample_id=["sample-[56]"], model="mockllm/model")[0]
    check_multiple_samples(log)

    log = eval(task, sample_id=["sample-*"], model="mockllm/model")[0]
    assert log.samples
    assert len(log.samples) == 10


def test_sample_id_task_preface():
    task = Task(
        name="foo",
        dataset=[Sample(id=id, input=f"Input for {id}") for id in range(0, 10)],
    )
    # qualifier
    log = eval(task, sample_id="foo:5", model="mockllm/model")[0]
    assert log.samples
    assert len(log.samples) == 1

    # two qualifiers
    log = eval(task, sample_id=["foo:5", "foo:6"], model="mockllm/model")[0]
    assert log.samples
    assert len(log.samples) == 2

    # two misses
    with pytest.raises(PrerequisiteError):
        log = eval(task, sample_id=["bar:5", "bar:6"], model="mockllm/model")[0]


def test_sample_id_task_preface_with_sandbox():
    task = Task(
        name="foo",
        dataset=[Sample(id="sample", input="Input for sample")],
        sandbox="local",
    )
    # qualifier
    log = eval(task, sample_id="foo:sample", model="mockllm/model")[0]
    assert log.samples
    assert len(log.samples) == 1


def test_sample_id_task_preface_multiple():
    task1 = Task(
        name="foo",
        dataset=[Sample(id=id, input=f"Input for {id}") for id in range(0, 10)],
    )
    task2 = Task(
        name="bar",
        dataset=[Sample(id=id, input=f"Input for {id}") for id in range(0, 10)],
    )
    logs = eval([task1, task2], sample_id=["foo:5", "bar:6"], model="mockllm/model")
    assert logs[0].samples
    assert len(logs[0].samples) == 1
    assert logs[0].samples[0].id == 5

    assert logs[1].samples
    assert len(logs[1].samples) == 1
    assert logs[1].samples[0].id == 6
