import os
import tempfile
from typing import Set

import pytest
from test_helpers.utils import failing_solver_deterministic

from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.log import list_eval_logs, read_eval_log_sample, read_eval_log_samples


@pytest.fixture
def streaming_log():
    return os.path.join("tests", "log", "test_eval_log", "log_streaming.eval")


def test_read_eval_log_sample(streaming_log: str) -> None:
    sample = read_eval_log_sample(streaming_log, 1, 1)
    assert sample.id == 1
    assert sample.epoch == 1


def test_read_eval_log_sample_index_error(streaming_log: str) -> None:
    with pytest.raises(IndexError):
        read_eval_log_sample(streaming_log, 3, 1)


def test_read_eval_log_samples(streaming_log: str) -> None:
    ids: Set[str | int] = set()
    epochs: Set[int] = set()

    total_samples = 0
    for sample in read_eval_log_samples(streaming_log):
        ids.add(sample.id)
        epochs.add(sample.epoch)
        total_samples += 1

    assert total_samples == 4
    assert ids == set([1, 2])
    assert epochs == set([1, 2])


def test_read_eval_log_samples_with_error():
    @task
    def failing_task():
        return Task(
            dataset=[Sample("Hello"), Sample("Hello")],
            plan=[failing_solver_deterministic([False, True])],
        )

    with tempfile.TemporaryDirectory() as log_dir:
        eval(
            failing_task(),
            model="mockllm/model",
            log_format="eval",
            log_dir=log_dir,
            max_samples=1,
        )
        log_file = list_eval_logs(log_dir)[0]

        # we expect a runtime error when we know the second sample failed
        # (as we will fail validation of status == "complete")
        with pytest.raises(RuntimeError):
            for _ in read_eval_log_samples(log_file):
                pass

        # we should be able to ignore the index error with all_samples_required=False
        total_samples = 0
        for _ in read_eval_log_samples(log_file, all_samples_required=False):
            total_samples += 1
        assert total_samples == 1
