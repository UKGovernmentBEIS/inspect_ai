"""Tests for driving a running eval from a `TaskSource` (batch-at-a-time).

The source seeds the run with `initial_tasks()`, observes each batch's results
via `sample_complete` / `task_complete`, and produces the next batch from
`next_tasks()` until it returns `None` — all under one run_id.
"""

import pytest

from inspect_ai import Task, TaskSource, eval
from inspect_ai._eval.loader import resolve_tasks
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog, EvalSample
from inspect_ai.model import get_model
from inspect_ai.solver import generate


def _task(name: str) -> Task:
    return Task(
        dataset=[Sample(input="hi", target="ok")], solver=[generate()], name=name
    )


class _Generations(TaskSource):
    """Runs `count` tasks one batch at a time; each produced after the prior."""

    def __init__(self, count: int) -> None:
        self.count = count
        self.tasks_seen: list[str] = []
        self.samples_seen = 0
        self._produced = 1  # gen0 is the initial seed

    def initial_tasks(self) -> list[Task]:
        return [_task("gen0")]

    async def sample_complete(self, sample: EvalSample) -> None:
        self.samples_seen += 1

    async def task_complete(self, log: EvalLog) -> None:
        self.tasks_seen.append(log.eval.task)

    async def next_tasks(self) -> list[Task] | None:
        if self._produced < self.count:
            name = f"gen{self._produced}"
            self._produced += 1
            return [_task(name)]
        return None


def test_task_source_runs_batches_in_one_run() -> None:
    source = _Generations(3)
    logs = eval(tasks=source, model="mockllm/model", display="none")

    # all generations ran, under a single run, in order observed by the source
    assert sorted(log.eval.task for log in logs) == ["gen0", "gen1", "gen2"]
    assert len({log.eval.run_id for log in logs}) == 1
    assert source.tasks_seen == ["gen0", "gen1", "gen2"]
    assert source.samples_seen == 3  # one sample per task, observed per batch


def test_task_source_single_batch_when_next_is_none() -> None:
    # next_tasks() returns None immediately -> only the seed runs
    logs = eval(tasks=_Generations(1), model="mockllm/model", display="none")
    assert [log.eval.task for log in logs] == ["gen0"]


def test_task_source_rejected_outside_eval() -> None:
    # a TaskSource isn't a concrete task list — resolving one (e.g. via eval_set)
    # is a clear error
    with pytest.raises(ValueError, match="only be passed to eval"):
        resolve_tasks(_Generations(1), {}, get_model("mockllm/model"), None, None, None)
