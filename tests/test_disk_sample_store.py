import os
from typing import TYPE_CHECKING

from pydantic import JsonValue

from inspect_ai import Task, eval
from inspect_ai._eval.task.store import (
    DiskSampleStore,
    deep_getsizeof,
    maybe_page_to_disk,
)
from inspect_ai.dataset import Sample
from inspect_ai.dataset._dataset import MemoryDataset
from inspect_ai.scorer import match
from inspect_ai.solver._solver import generate
from inspect_ai.util._early_stopping import EarlyStop

if TYPE_CHECKING:
    from inspect_ai.log._log import EvalSpec
    from inspect_ai.scorer._metric import SampleScore


def _make_samples(n: int = 5) -> list[Sample]:
    return [
        Sample(input=f"Question {i}", target=f"Answer {i}", id=str(i)) for i in range(n)
    ]


# -- Part 1: DiskSampleStore unit tests --


def test_disk_sample_store_roundtrip() -> None:
    samples = _make_samples(5)
    store = DiskSampleStore(samples)

    assert len(store) == 5
    for i, original in enumerate(samples):
        restored = store[i]
        assert restored.input == original.input
        assert restored.target == original.target
        assert restored.id == original.id

    # Backing file exists while store is open
    assert os.path.exists(store._path)

    store.close()

    # Backing file removed after close
    assert not os.path.exists(store._path)


def test_disk_sample_store_close_is_defensive() -> None:
    store = DiskSampleStore(_make_samples(2))
    # Manually remove the backing file before close
    os.unlink(store._path)
    # close() should not raise
    store.close()


def test_disk_sample_store_close_after_close() -> None:
    store = DiskSampleStore(_make_samples(2))
    store.close()
    # Second close should not raise
    store.close()


# -- Part 2: deep_getsizeof --


def test_deep_getsizeof_basic() -> None:
    assert deep_getsizeof({"a": 1}) > 0
    assert deep_getsizeof([1, 2, 3]) > 0
    assert deep_getsizeof(Sample(input="hello")) > 0

    small = deep_getsizeof([1])
    large = deep_getsizeof([1, "a longer string", {"nested": [1, 2, 3]}])
    assert large > small


# -- Part 3: maybe_page_to_disk --


def test_maybe_page_to_disk_returns_dataset_when_no_limit() -> None:
    dataset = MemoryDataset(_make_samples(3))
    result = maybe_page_to_disk(dataset, None)
    assert result is dataset


def test_maybe_page_to_disk_returns_dataset_when_under_budget() -> None:
    dataset = MemoryDataset(_make_samples(3))
    result = maybe_page_to_disk(dataset, 1000)
    assert result is dataset


def test_maybe_page_to_disk_returns_store_when_over_budget() -> None:
    dataset = MemoryDataset(_make_samples(5))
    result = maybe_page_to_disk(dataset, 0)

    assert isinstance(result, DiskSampleStore)
    assert len(result) == 5
    assert result[0].input == "Question 0"
    result.close()


# -- Part 4: Integration test --


def test_eval_with_max_dataset_memory() -> None:
    samples = [Sample(input=f"Say {i}", target=str(i)) for i in range(3)]
    task = Task(
        dataset=samples,
        solver=[generate()],
        scorer=match(),
    )
    log = eval(task, model="mockllm/model", max_dataset_memory=0)[0]

    assert log.status == "success"
    assert log.samples is not None
    assert len(log.samples) == 3


# -- Part 5: Early stopping + disk paging integration test --


class _NoopEarlyStopping:
    """Minimal early stopping that never stops anything."""

    async def start_task(
        self, task: "EvalSpec", samples: list[Sample], epochs: int
    ) -> str:
        return "noop"

    async def schedule_sample(self, id: str | int, epoch: int) -> EarlyStop | None:
        return None

    async def complete_sample(
        self,
        id: str | int,
        epoch: int,
        scores: dict[str, "SampleScore"],
    ) -> None:
        pass

    async def complete_task(self) -> dict[str, JsonValue]:
        return {}


def test_eval_with_max_dataset_memory_and_early_stopping() -> None:
    samples = [Sample(input=f"Say {i}", target=str(i)) for i in range(3)]
    task = Task(
        dataset=samples,
        solver=[generate()],
        scorer=match(),
        early_stopping=_NoopEarlyStopping(),
    )
    log = eval(task, model="mockllm/model", max_dataset_memory=0)[0]

    assert log.status == "success"
    assert log.samples is not None
    assert len(log.samples) == 3
