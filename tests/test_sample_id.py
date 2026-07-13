from pathlib import Path

import pytest

from inspect_ai import Task, eval
from inspect_ai._eval.run import ensure_unique_ids
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log import read_eval_log_sample
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


def test_sample_id_uniqueness_str_collision():
    # exact duplicates are rejected
    with pytest.raises(PrerequisiteError, match="duplicate"):
        ensure_unique_ids(
            MemoryDataset([Sample(id=1, input="a"), Sample(id=1, input="b")])
        )

    # int 1 and str "1" are distinct under set equality but collide when
    # coerced to str (which downstream log storage / score reduction /
    # buffer db all do), so they must also be rejected at validation time
    with pytest.raises(PrerequisiteError, match="string representation"):
        ensure_unique_ids(
            MemoryDataset([Sample(id=1, input="a"), Sample(id="1", input="b")])
        )

    # non-colliding mixed-type ids are fine
    ensure_unique_ids(
        MemoryDataset([Sample(id=1, input="a"), Sample(id="2", input="b")])
    )


@pytest.mark.parametrize("log_format", ["eval", "json"])
def test_read_sample_distinguishes_numeric_string_id_from_int(
    tmp_path: Path, log_format: str
) -> None:
    # `Sample(id=1)` and `Sample(id="001")` have distinct string reprs (so
    # `ensure_unique_ids` allows them) but `normalise_sample_id` maps both to
    # the same zero-filled key. Reading by id must still resolve each exactly,
    # falling back to the normalised match only for loose addressing ("1" -> 1).
    task = Task(
        dataset=[
            Sample(id=1, input="hi", target="ok"),
            Sample(id="001", input="hi", target="ok"),
        ],
        name="collide",
    )
    log = eval(
        task,
        model="mockllm/model",
        log_dir=str(tmp_path),
        log_format=log_format,  # type: ignore[arg-type]
    )[0]
    assert log.status == "success"

    assert read_eval_log_sample(log.location, "001").id == "001"
    assert read_eval_log_sample(log.location, 1).id == 1
    assert read_eval_log_sample(log.location, "1").id == 1
