"""Reproductions for surfacing task-level retries at the sample level.

When an eval-set retries a whole task (``retry_attempts`` / the default
``retry_immediate`` path), the failed sample is re-run in a fresh log and
the failed attempt's log is removed by ``retry_cleanup``. The re-run sample
must therefore carry the prior attempt's error in ``error_retries`` so that:

- ``EvalSample.error_retries`` records the prior error (run path), and
- the stored ``EvalSampleSummary.retries`` reflects it (the path the
  control channel reads — both the live recorder and the on-disk log).
"""

import tempfile
from pathlib import Path
from typing import Literal

import anyio
import pytest

from inspect_ai import Task, eval_set, task
from inspect_ai._eval.task.run import _eval_retry_error_from_sample
from inspect_ai.dataset import Sample
from inspect_ai.event._model import ModelEvent
from inspect_ai.log import (
    EvalError,
    EvalSample,
    read_eval_log,
    read_eval_log_sample_summaries,
    write_eval_log,
)
from inspect_ai.log._condense import ATTACHMENT_PROTOCOL
from inspect_ai.model import ContentImage
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.solver import Generate, Solver, TaskState, solver


def _fail_once_task() -> Task:
    """A one-sample task whose sample errors on its first attempt only."""
    attempts = {"n": 0}

    @solver
    def fail_first_attempt() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("transient task failure")
            return state

        return solve

    @task
    def retry_task() -> Task:
        return Task(
            dataset=[Sample(id=1, input="x", target="y")],
            solver=[fail_first_attempt()],
            name="retry_task",
        )

    return retry_task()


def _run_task_retry(log_dir: str) -> str:
    """Run an eval-set that retries one failing task; return the log path."""
    ok, logs = eval_set(
        tasks=[_fail_once_task()],
        log_dir=log_dir,
        model="mockllm/model",
        retry_attempts=2,
        retry_on_error=0,  # no sample-level retry -> task-level retry kicks in
    )
    assert ok, "eval-set did not succeed after task retry"
    assert len(logs) == 1
    return logs[0].location


def test_task_retry_seeds_error_retries_on_sample() -> None:
    """Run path: the re-run sample carries the prior attempt's error."""
    with tempfile.TemporaryDirectory() as d:
        log_dir = str(Path(d) / "logs")
        Path(log_dir).mkdir()
        location = _run_task_retry(log_dir)

        log = read_eval_log(location)
        assert log.samples is not None and len(log.samples) == 1
        sample = log.samples[0]
        assert sample.error is None, "final attempt should have succeeded"
        assert sample.error_retries is not None
        assert len(sample.error_retries) == 1
        assert "transient task failure" in sample.error_retries[0].message


def test_task_retry_resolves_attachments_in_seeded_error_events() -> None:
    image_data_uri = "data:image/png;base64,iVBORw0KGgo="
    attachment_ref = f"{ATTACHMENT_PROTOCOL}image"
    event = ModelEvent(
        model="test-model",
        input=[
            ChatMessageUser(content=[ContentImage(image=attachment_ref)]),
        ],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("test-model", "response"),
        call=ModelCall.create(
            {"messages": [{"role": "user", "content": attachment_ref}]}, None
        ),
    )
    sample = EvalSample(
        id="sample",
        epoch=1,
        input="input",
        target="target",
        error=EvalError(message="boom", traceback="", traceback_ansi=""),
        events=[event],
        attachments={"image": image_data_uri},
    )

    retry_error = _eval_retry_error_from_sample(sample)

    assert retry_error.events is not None
    retry_json = retry_error.model_dump_json()
    assert ATTACHMENT_PROTOCOL not in retry_json
    assert image_data_uri in retry_json


def test_task_retry_retries_in_sample_summaries() -> None:
    """Endpoint path: the stored summary reports the retry count.

    This is the exact data the control channel reads for a finished /
    keep-alive-parked eval (recorder gone -> on-disk summaries).
    """
    with tempfile.TemporaryDirectory() as d:
        log_dir = str(Path(d) / "logs")
        Path(log_dir).mkdir()
        location = _run_task_retry(log_dir)

        summaries = read_eval_log_sample_summaries(location)
        assert len(summaries) == 1
        assert summaries[0].retries == 1


def test_is_cancellation_error_distinguishes_cancellations() -> None:
    """The cancellation guard matches backend cancellation reprs only."""
    from inspect_ai._eval.task.run import _is_cancellation_error
    from inspect_ai.log import EvalError

    def err(message: str) -> EvalError:
        return EvalError(message=message, traceback="", traceback_ansi="")

    # asyncio / trio cancellation reprs
    assert _is_cancellation_error(err("CancelledError('Cancelled via cancel scope 1')"))
    assert _is_cancellation_error(err("CancelledError()"))
    assert _is_cancellation_error(err("Cancelled()"))
    # genuine errors must not be treated as cancellations
    assert not _is_cancellation_error(err("RuntimeError('boom')"))
    assert not _is_cancellation_error(err("CancelledByUserError('nope')"))


def test_task_retry_does_not_count_cancelled_siblings() -> None:
    """A sibling cancelled by another sample's failure isn't a retry.

    Sample 1 errors on its first attempt; sample 2 is in-flight and gets
    cancelled when the task is torn down for the task-level retry. On the
    retry sample 1 succeeds. Sample 1 should report ``retries == 1`` (a
    genuine failure) while sample 2 reports ``retries == 0`` (it was only
    cancelled, never genuinely failed).
    """
    import anyio

    attempts = {"n": 0}

    @solver
    def mixed() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if int(state.sample_id) == 1:
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise RuntimeError("boom")
            else:
                # in-flight when sample 1 errors -> cancelled on attempt 1;
                # completes on the retry (sample 1 succeeds, no teardown)
                await anyio.sleep(2)
            return state

        return solve

    @task
    def mixed_task() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="y") for i in (1, 2)],
            solver=[mixed()],
            name="mixed_task",
        )

    with tempfile.TemporaryDirectory() as d:
        log_dir = str(Path(d) / "logs")
        Path(log_dir).mkdir()
        ok, logs = eval_set(
            tasks=[mixed_task()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=2,
            retry_on_error=0,
            max_samples=2,
        )
        assert ok

        summaries = {s.id: s for s in read_eval_log_sample_summaries(logs[0].location)}
        assert summaries[1].retries == 1, "genuine error should count as a retry"
        assert summaries[2].retries == 0, "cancelled sibling must not count as a retry"


def test_task_retry_accumulates_across_attempts() -> None:
    """Retries accumulate across multiple sequential task attempts.

    Sample 3 errors on its first two runs and succeeds on the third, so its
    history must grow to two entries (``retries == 2``); sample 1 errors once
    (``retries == 1``); sample 2 never errors (``retries == 0``). No solver
    awaits before raising, so there is no cancellation point and the schedule
    is deterministic.
    """
    runs = {1: 0, 2: 0, 3: 0}

    @solver
    def flaky() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            sid = int(state.sample_id)
            runs[sid] += 1
            if sid == 1 and runs[1] == 1:
                raise RuntimeError("s1 fail")
            if sid == 3 and runs[3] <= 2:
                raise RuntimeError(f"s3 fail {runs[3]}")
            return state

        return solve

    @task
    def accum_task() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="y") for i in (1, 2, 3)],
            solver=[flaky()],
            name="accum_task",
        )

    with tempfile.TemporaryDirectory() as d:
        log_dir = str(Path(d) / "logs")
        Path(log_dir).mkdir()
        ok, logs = eval_set(
            tasks=[accum_task()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=5,
            retry_on_error=0,
            max_samples=3,
        )
        assert ok

        summaries = {s.id: s for s in read_eval_log_sample_summaries(logs[0].location)}
        assert summaries[1].retries == 1
        assert summaries[2].retries == 0
        assert summaries[3].retries == 2


@pytest.mark.parametrize("log_format", ["eval", "json"])
def test_eval_set_retry_preserves_shared_json_id_history(
    log_format: Literal["eval", "json"],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai._eval.task.log import TaskLogger

    failing = True

    @solver
    def fail_prior() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if failing:
                raise RuntimeError("prior padded ID failure")
            return state

        return solve

    task = Task(
        dataset=[Sample(id=id, input="x") for id in (1, "001")],
        solver=fail_prior(),
        name="shared_json_id_history",
    )
    success, logs = eval_set(
        task,
        log_dir=str(tmp_path),
        model="mockllm/model",
        log_format="json",
        retry_attempts=1,
        retry_immediate=False,
        retry_on_error=0,
    )
    assert not success
    prior = read_eval_log(logs[0].location)
    assert prior.samples is not None
    # Model an incomplete prior that recorded the padded ID but never wrote
    # the distinct integer ID from the same dataset.
    prior.samples = [s for s in prior.samples if s.id == "001"]
    assert len(prior.samples) == 1 and prior.samples[0].error is not None
    write_eval_log(prior, location=prior.location)
    failing = False
    first_completed = anyio.Event()
    complete = TaskLogger.complete_sample
    read_prior = TaskLogger.read_prior_sample

    async def complete_first(
        logger: TaskLogger, sample: EvalSample, *, flush: bool
    ) -> None:
        await complete(logger, sample, flush=flush)
        if sample.id == 1:
            first_completed.set()

    async def read_after_first(
        logger: TaskLogger, id: str | int, epoch: int
    ) -> EvalSample | None:
        if id == "001":
            await first_completed.wait()
        return await read_prior(logger, id, epoch)

    monkeypatch.setattr(TaskLogger, "complete_sample", complete_first)
    monkeypatch.setattr(TaskLogger, "read_prior_sample", read_after_first)
    success, logs = eval_set(
        task,
        log_dir=str(tmp_path),
        model="mockllm/model",
        log_format=log_format,
        retry_attempts=1,
        retry_immediate=False,
        retry_on_error=0,
        max_samples=2,
    )
    assert success and first_completed.is_set()
    final = read_eval_log(logs[0].location)
    assert final.samples is not None and {s.id for s in final.samples} == {1, "001"}
    for sample in final.samples:
        assert sample.error is None
        assert sample.error_retries is not None and len(sample.error_retries) == 1
        assert "prior padded ID failure" in sample.error_retries[0].message
    assert {
        s.id: s.retries for s in read_eval_log_sample_summaries(final.location)
    } == {
        1: 1,
        "001": 1,
    }
