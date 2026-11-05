import glob
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
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


def test_disk_sample_store_constructor_failure_cleans_up() -> None:
    """If pickling fails in __init__, the temp file must not be leaked."""
    bad_sample = Sample(input="ok", metadata={"fn": lambda: None})
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), "*.pkl")))
    with pytest.raises(Exception):
        DiskSampleStore([bad_sample])
    after = set(glob.glob(os.path.join(tempfile.gettempdir(), "*.pkl")))
    leaked = after - before
    assert not leaked, f"Temp file leaked: {leaked}"


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


@pytest.mark.parametrize("abandon_at", ["start", "register"])
def test_eval_abandoned_attempt_unlinks_paged_store(
    abandon_at: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An attempt abandoned by a task drain/cancel leaves no paged temp file.

    The attempt-start retry-abandon checks bail out of ``task_run`` before its
    ordinary tail runs, so the paged-to-disk store's temp file must be
    unlinked on that path too — whether the abandon is seen by the first
    check (before paging) or only by the pre-register backstop (after).
    """
    import inspect_ai._eval.task.run as task_run_module

    calls = {"n": 0}

    def fake_task_retry_abandoned(task_id: str) -> bool:
        calls["n"] += 1
        return abandon_at == "start" or calls["n"] > 1

    monkeypatch.setattr(
        task_run_module, "task_retry_abandoned", fake_task_retry_abandoned
    )
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    task = Task(dataset=_make_samples(3), solver=[generate()])
    logs = eval(
        task,
        model="mockllm/model",
        max_dataset_memory=0,
        log_dir=str(tmp_path / "logs"),
    )

    # the abandon was seen by the intended check (the backstop is the second
    # consult, after paging), the attempt produced no log, and the paged
    # dataset's temp file was unlinked
    assert calls["n"] == (1 if abandon_at == "start" else 2)
    assert logs == []
    assert not list(tmp_path.glob("*.pkl"))
