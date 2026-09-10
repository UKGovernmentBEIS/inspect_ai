from pathlib import Path

import pytest

from inspect_ai import Task, eval, eval_retry, task
from inspect_ai._eval.eval_set_manifest import samples_selected
from inspect_ai._eval.run import ensure_unique_ids
from inspect_ai._eval.task.util import resolve_task_sample_ids, slice_dataset
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


def test_resolve_task_sample_ids_colon_in_id_is_not_a_selector() -> None:
    # a prefix that names no task in the run is part of the id
    assert resolve_task_sample_ids("t", ["a:b"]) == ["a:b"]
    assert resolve_task_sample_ids("t", ["a:b"], task_names=["t"]) == ["a:b"]
    assert resolve_task_sample_ids("t", "a:b", task_names=["t"]) == "a:b"

    # several colons survive whole
    assert resolve_task_sample_ids(
        "veevals/exploit_gym_hardened", ["user:cybergym/x:y"]
    ) == ["user:cybergym/x:y"]

    # ...and a task-qualified id keeps the rest intact
    assert resolve_task_sample_ids(
        "veevals/exploit_gym_hardened",
        ["veevals/exploit_gym_hardened:user:cybergym/x:y"],
    ) == ["user:cybergym/x:y"]


def test_resolve_task_sample_ids_prefix_naming_a_task_is_a_selector() -> None:
    names = ["t", "a"]
    assert resolve_task_sample_ids("t", ["a:b"], task_names=names) == []
    assert resolve_task_sample_ids("a", ["a:b"], task_names=names) == ["b"]
    assert resolve_task_sample_ids("t", ["a:b", "t:c", "d"], task_names=names) == [
        "c",
        "d",
    ]
    # case-insensitive, as before
    assert resolve_task_sample_ids("A", ["a:b"], task_names=names) == ["b"]


def test_slice_dataset_empty_sample_id_selects_nothing() -> None:
    dataset = MemoryDataset([Sample(id="user:1", input="a")])
    assert len(slice_dataset(dataset, None, [], dynamic=False)) == 0
    assert len(slice_dataset(dataset, None, [], dynamic=True)) == 0


def test_sample_id_with_colon_runs_exactly_that_sample() -> None:
    task = Task(
        name="exploit_gym",
        dataset=[
            Sample(id=f"user:cybergym/arvo_{n}", input="hi") for n in (6008, 10096)
        ],
    )
    log = eval(task, sample_id=["user:cybergym/arvo_6008"], model="mockllm/model")[0]
    assert log.status == "success"
    assert log.samples
    assert [s.id for s in log.samples] == ["user:cybergym/arvo_6008"]

    log = eval(task, sample_id="user:cybergym/arvo_6008", model="mockllm/model")[0]
    assert log.samples and len(log.samples) == 1

    # the count eval_set plans by agrees with what ran
    assert (
        samples_selected(task.dataset, None, ["user:cybergym/arvo_6008"], "exploit_gym")
        == 1
    )


def test_sample_id_with_colon_and_sandbox() -> None:
    task = Task(
        name="exploit_gym",
        dataset=[Sample(id="user:cybergym/arvo_6008", input="hi")],
        sandbox="local",
    )
    log = eval(task, sample_id="user:cybergym/arvo_6008", model="mockllm/model")[0]
    assert log.status == "success"
    assert log.samples and len(log.samples) == 1


def test_sample_id_ambiguous_prefix_resolves_as_selector() -> None:
    # a dataset id shaped like `<other task>:<id>` while that task is in the
    # run reads as a selector for the other task, not as this task's id
    foo = Task(name="foo", dataset=[Sample(id="bar:1", input="hi")])
    bar = Task(name="bar", dataset=[Sample(id=1, input="hi")])
    logs = eval([foo, bar], sample_id="bar:1", model="mockllm/model")
    assert logs[0].status == "success" and not logs[0].samples
    assert logs[1].samples and [s.id for s in logs[1].samples] == [1]


def test_sample_id_task_preface_unaddressed_task_runs_no_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai._eval import run as run_module

    warnings: list[str] = []
    monkeypatch.setattr(
        run_module.log, "warning", lambda msg, *a, **k: warnings.append(msg)
    )

    foo = Task(name="foo", dataset=[Sample(id=i, input="hi") for i in range(3)])
    bar = Task(name="bar", dataset=[Sample(id=i, input="hi") for i in range(3)])
    logs = eval([foo, bar], sample_id=["foo:1"], model="mockllm/model")
    assert logs[0].samples and [s.id for s in logs[0].samples] == [1]
    assert logs[1].status == "success"
    assert not logs[1].samples
    assert any("names task 'bar'" in w for w in warnings)


@task
def one_sample_task() -> Task:
    return Task(dataset=[Sample(id=1, input="hi")])


@task
def cybergym() -> Task:
    return Task(dataset=[Sample(id=f"cybergym:arvo_{n}", input="hi") for n in (1, 2)])


def test_sample_id_empty_list_selects_nothing() -> None:
    # `[]` is what resolution leaves for a task no selector names, and a log
    # records it that way, so it is one value with one meaning everywhere
    log = eval(one_sample_task(), sample_id=[], model="mockllm/model")[0]
    assert log.status == "success"
    assert not log.samples
    assert log.eval.config.sample_id == []

    retried = eval_retry(log)[0]
    assert retried.status == "success"
    assert not retried.samples


def test_samples_selected_scalar_zero_is_a_sample_id() -> None:
    dataset = MemoryDataset([Sample(id=0, input="x")])
    assert samples_selected(dataset, None, 0, "t") == 1
    assert samples_selected(dataset, None, "other:0", "t", ["t", "other"]) == 0


def test_sample_id_retry_keeps_task_qualified_ids_intact() -> None:
    # a retry replays the log's resolved selection through resolution again;
    # an id that itself begins with `<task>:` must not lose that prefix twice
    log = eval(cybergym(), sample_id="cybergym:cybergym:arvo_1", model="mockllm/model")[
        0
    ]
    assert [s.id for s in log.samples or []] == ["cybergym:arvo_1"]
    assert log.eval.config.sample_id == "cybergym:arvo_1"

    retried = eval_retry(log)[0]
    assert retried.status == "success"
    assert [s.id for s in retried.samples or []] == ["cybergym:arvo_1"]


def test_sample_id_eval_set_tasks_resolve_selectors_for_a_subset() -> None:
    # a retried subset of an eval set resolves `task:id` selectors against the
    # whole set: `foo:1` names a task outside this batch, so bar runs nothing
    bar = Task(name="bar", dataset=[Sample(id=i, input="hi") for i in range(3)])
    log = eval(
        bar, sample_id=["foo:1"], eval_set_tasks=["foo", "bar"], model="mockllm/model"
    )[0]
    assert log.status == "success"
    assert not log.samples

    # without the set's names `foo` is unknown, so `foo:1` is a literal id
    with pytest.raises(PrerequisiteError, match="foo:1"):
        eval(bar, sample_id=["foo:1"], model="mockllm/model")
