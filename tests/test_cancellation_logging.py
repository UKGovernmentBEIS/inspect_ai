"""Tests for cancellation error handling and logging.

Verifies that when samples are cancelled (due to another sample's error
with fail_on_error, or due to a KeyboardInterrupt), the cancelled samples
are fully logged with their errors in the eval log.
"""

import os
import signal
import threading
from pathlib import Path

import anyio

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import list_eval_logs, read_eval_log
from inspect_ai.scorer import includes
from inspect_ai.solver import Generate, TaskState, generate, solver, user_message


@solver
def error_or_sleep_solver():
    """First sample errors after brief delay; others sleep indefinitely."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if state.sample_id == 1:
            # Brief delay to allow other samples to start
            await anyio.sleep(0.1)
            raise ValueError("Intentional test error")
        # Sleep long enough to still be running when sample 1 errors
        await anyio.sleep(30)
        return state

    return solve


def _conversation_then_error_solvers() -> list:
    """Build a solver chain with conversation turns before the error/sleep."""
    return [
        generate(),
        user_message("follow up question"),
        generate(),
        user_message("another follow up"),
        generate(),
        error_or_sleep_solver(),
    ]


@solver
def sleep_solver():
    """All samples sleep; used with external SIGINT."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        await anyio.sleep(60)
        return state

    return solve


def _make_samples(n: int) -> list[Sample]:
    """Create n samples with explicit integer IDs (1-indexed)."""
    return [Sample(input=f"Sample {i}", target="target", id=i) for i in range(1, n + 1)]


def test_fail_on_error_logs_cancelled_samples():
    """When fail_on_error=True and one sample errors, concurrent samples should be cancelled and all samples should appear in the log."""
    num_samples = 5
    task = Task(
        dataset=_make_samples(num_samples),
        solver=_conversation_then_error_solvers(),
        scorer=includes(),
        fail_on_error=True,
    )

    log = eval(task, model="mockllm/model", max_samples=num_samples)[0]

    # the eval should have error status (fail_on_error threshold exceeded)
    assert log.status == "error"
    assert log.samples is not None

    # the errored sample should be logged with a ValueError
    errored = [s for s in log.samples if s.id == 1]
    assert len(errored) == 1
    assert errored[0].error is not None
    assert "Intentional test error" in errored[0].error.message

    # the errored sample should have conversation history from before the error:
    # initial user msg + assistant + user follow-up + assistant + user follow-up + assistant = 6
    assert len(errored[0].messages) >= 6

    # at least some of the other samples should be logged with cancellation errors
    cancelled = [s for s in log.samples if s.id != 1 and s.error is not None]
    assert len(cancelled) > 0

    # cancelled samples should preserve their conversation history and events
    for sample in cancelled:
        # should have at least the initial message + some conversation turns
        assert len(sample.messages) >= 1
        # should have transcript events (SampleInitEvent, ModelEvents, ErrorEvent, etc.)
        assert len(sample.events) >= 2

    # every logged sample should have an error (either ValueError or cancellation)
    for sample in log.samples:
        assert sample.error is not None


def test_fail_on_error_threshold_logs_cancelled_samples():
    """When fail_on_error is a count threshold and enough samples error, concurrent samples should be cancelled and logged."""
    num_samples = 6

    @solver
    def error_first_three_solver():
        """Samples 1-3 error after brief delay; samples 4-6 sleep."""

        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if int(state.sample_id) <= 3:
                await anyio.sleep(0.1)
                raise ValueError(f"Error in sample {state.sample_id}")
            await anyio.sleep(30)
            return state

        return solve

    task = Task(
        dataset=_make_samples(num_samples),
        solver=[error_first_three_solver()],
        scorer=includes(),
        # fail after 3 errors
        fail_on_error=3,
    )

    log = eval(task, model="mockllm/model", max_samples=num_samples)[0]

    assert log.status == "error"
    assert log.samples is not None

    # the errored samples should have ValueError
    errored = [s for s in log.samples if s.id is not None and s.id <= 3]
    for s in errored:
        assert s.error is not None
        assert "Error in sample" in s.error.message

    # some sleeping samples should have been cancelled and logged
    cancelled = [
        s for s in log.samples if s.id is not None and s.id > 3 and s.error is not None
    ]
    assert len(cancelled) > 0


def test_all_concurrent_samples_accounted_for():
    """When fail_on_error cancels concurrent samples, ALL samples should appear in the log."""
    num_samples = 5
    task = Task(
        dataset=_make_samples(num_samples),
        solver=[error_or_sleep_solver()],
        scorer=includes(),
        fail_on_error=True,
    )

    log = eval(task, model="mockllm/model", max_samples=num_samples)[0]

    assert log.status == "error"
    assert log.samples is not None

    # all samples should be present in the log
    assert len(log.samples) == num_samples

    # every sample should have a completed_at timestamp
    for sample in log.samples:
        assert sample.completed_at is not None

    # collect the sample ids to verify all are accounted for
    logged_ids = {s.id for s in log.samples}
    expected_ids = set(range(1, num_samples + 1))
    assert logged_ids == expected_ids


def test_fail_on_error_no_retry_for_cancelled():
    """Cancelled samples should not be retried even when retry_on_error > 0."""
    num_samples = 3
    task = Task(
        dataset=_make_samples(num_samples),
        solver=[error_or_sleep_solver()],
        scorer=includes(),
        fail_on_error=True,
    )

    log = eval(task, model="mockllm/model", max_samples=num_samples, retry_on_error=2)[
        0
    ]

    assert log.status == "error"
    assert log.samples is not None

    # cancelled samples should not have retries (they should appear once)
    cancelled = [s for s in log.samples if s.id != 1 and s.error is not None]
    for s in cancelled:
        # cancelled samples should have no error retries
        assert s.error_retries is None or len(s.error_retries) == 0


def test_keyboard_interrupt_logs_cancelled_samples(tmp_path: Path):
    """When SIGINT (KeyboardInterrupt) occurs, all running samples should be cancelled and logged."""
    num_samples = 5
    task = Task(
        dataset=_make_samples(num_samples),
        solver=[sleep_solver()],
        scorer=includes(),
    )

    # send SIGINT from a background thread after samples have started
    def send_sigint() -> None:
        import time

        time.sleep(1)
        os.kill(os.getpid(), signal.SIGINT)

    sigint_thread = threading.Thread(target=send_sigint, daemon=True)
    sigint_thread.start()

    # eval() raises KeyboardInterrupt after logging the cancelled eval
    try:
        eval(
            task,
            model="mockllm/model",
            max_samples=num_samples,
            log_dir=str(tmp_path),
        )
    except KeyboardInterrupt:
        pass

    sigint_thread.join(timeout=5)

    # read the log that was written to disk before KeyboardInterrupt propagated
    log_files = list_eval_logs(str(tmp_path))
    assert len(log_files) == 1
    log = read_eval_log(log_files[0].name)

    assert log.status == "cancelled"
    assert log.samples is not None

    # at least some samples should be logged with cancellation errors
    samples_with_errors = [s for s in log.samples if s.error is not None]
    assert len(samples_with_errors) > 0

    # every logged sample should have an error
    for sample in log.samples:
        assert sample.error is not None
