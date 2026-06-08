import tempfile
from collections.abc import Iterator

import anyio
import pytest

from inspect_ai import Task, eval
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai.dataset import Sample
from inspect_ai.log._file import (
    read_eval_log_sample,
    read_eval_log_sample_async,
    read_eval_log_samples_by_id,
    read_eval_log_samples_by_id_async,
)
from inspect_ai.solver import generate


def build_log(tmp_dir: str, n_samples: int = 4, epochs: int = 2) -> str:
    """Build a small .eval log and return its location.

    Sample ids are auto-assigned 1..n_samples and epochs 1..epochs, so the
    available (id, epoch) keys are the cartesian product of those ranges.
    """
    task = Task(
        dataset=[
            Sample(input=f"Question {i}", target=f"Answer {i}")
            for i in range(n_samples)
        ],
        solver=generate(),
    )
    return eval(task, model="mockllm/model", epochs=epochs, log_dir=tmp_dir)[0].location


@pytest.fixture(scope="module")
def log_file() -> Iterator[str]:
    # Build the log eagerly (outside any event loop) so async tests can read it
    # without nesting eval()'s own asyncio.run inside a running loop.
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield build_log(tmp_dir)


def test_read_samples_by_id_preserves_request_order(log_file: str):
    requested = [(2, 2), (1, 1), (4, 1), (3, 2)]
    samples = read_eval_log_samples_by_id(log_file, requested)
    assert [(s.id, s.epoch) for s in samples] == requested


def test_read_samples_by_id_matches_read_eval_log_sample(log_file: str):
    requested = [(3, 1), (1, 2), (2, 1)]
    samples = read_eval_log_samples_by_id(log_file, requested)
    for (id, epoch), sample in zip(requested, samples):
        expected = read_eval_log_sample(log_file, id=id, epoch=epoch)
        assert sample.model_dump() == expected.model_dump()


def test_read_samples_by_id_honors_exclude_fields(log_file: str):
    samples = read_eval_log_samples_by_id(
        log_file, [(1, 1), (2, 1)], exclude_fields={"store", "events"}
    )
    assert len(samples) == 2
    for sample in samples:
        assert sample.input is not None
        assert not sample.store
        assert not sample.events


def test_read_samples_by_id_concurrency_is_invariant(log_file: str):
    requested = [(4, 2), (1, 1), (3, 1), (2, 2), (1, 2)]
    serial = read_eval_log_samples_by_id(log_file, requested, concurrency=1)
    parallel = read_eval_log_samples_by_id(log_file, requested, concurrency=4)
    assert [s.model_dump() for s in serial] == [s.model_dump() for s in parallel]


def test_read_samples_by_id_missing_raises_index_error(log_file: str):
    with pytest.raises(IndexError):
        read_eval_log_samples_by_id(log_file, [(1, 1), (99, 1)])


def test_read_samples_by_id_empty_request_returns_empty_list(log_file: str):
    assert read_eval_log_samples_by_id(log_file, []) == []


async def test_read_samples_by_id_async_matches_sync(log_file: str):
    requested = [(2, 2), (1, 1), (4, 1)]
    async with AsyncFilesystem():
        samples = await read_eval_log_samples_by_id_async(log_file, requested)
        assert [(s.id, s.epoch) for s in samples] == requested
        for (id, epoch), sample in zip(requested, samples):
            expected = await read_eval_log_sample_async(log_file, id=id, epoch=epoch)
            assert sample.model_dump() == expected.model_dump()


def test_read_samples_by_id_async_runs_under_anyio(log_file: str):
    requested = [(3, 2), (1, 1)]

    async def main() -> None:
        async with AsyncFilesystem():
            samples = await read_eval_log_samples_by_id_async(log_file, requested)
        assert [(s.id, s.epoch) for s in samples] == requested

    anyio.run(main)
