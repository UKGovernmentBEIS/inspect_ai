"""Tests for cancellation error handling and logging.

Verifies that when samples are cancelled (due to another sample's error
with fail_on_error, or due to a KeyboardInterrupt), the cancelled samples
are fully logged with their errors in the eval log.
"""

import asyncio
import contextlib
import os
import signal
import threading
from pathlib import Path

import anyio
import anyio.lowlevel
import pytest
from test_helpers.utils import skip_if_trio

from inspect_ai import Task, eval, eval_async
from inspect_ai._util.error import is_cancellation_message
from inspect_ai.dataset import Sample
from inspect_ai.event import ErrorEvent
from inspect_ai.log import (
    EvalLog,
    list_eval_logs,
    read_eval_log,
    read_eval_log_async,
)
from inspect_ai.scorer import includes
from inspect_ai.solver import Generate, TaskState, generate, solver, user_message
from inspect_ai.util import background


@pytest.fixture(params=[True, False], ids=["with_sandbox", "no_sandbox"])
def sandbox_kwarg(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> str | None:
    """Run each cancellation test on both branches of `run.py`'s sandbox split.

    `with_sandbox`: monkeypatches `sandboxenv_context` to a fake whose teardown
    awaits, and returns `sandbox="local"` so the Task takes the `sandboxenv_cm`
    branch -- the path whose unshielded `__aexit__` checkpoint drops in-flight
    samples on cancel.

    `no_sandbox`: returns `None` so the Task takes the `nullcontext()` branch.
    No monkeypatch needed -- nullcontext's `__aexit__` has no await.

    Each test uses `sandbox=sandbox_kwarg` on its `Task` so pytest runs it once
    per branch, keeping the existing no-sandbox regression coverage while
    adding the sandbox-path coverage that the bug requires.
    """
    if request.param:

        @contextlib.asynccontextmanager
        async def fake_sandboxenv_context(*args, **kwargs):
            try:
                yield
            finally:
                # any unshielded checkpoint here trips the still-cancelled scope
                await anyio.sleep(0.05)

        monkeypatch.setattr(
            "inspect_ai._eval.task.run.sandboxenv_context", fake_sandboxenv_context
        )
        return "local"
    return None


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


def test_fail_on_error_logs_cancelled_samples(sandbox_kwarg: str | None):
    """When fail_on_error=True and one sample errors, concurrent samples should be cancelled and all samples should appear in the log."""
    num_samples = 5
    task = Task(
        dataset=_make_samples(num_samples),
        solver=_conversation_then_error_solvers(),
        scorer=includes(),
        sandbox=sandbox_kwarg,
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


def test_fail_on_error_threshold_logs_cancelled_samples(sandbox_kwarg: str | None):
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
        sandbox=sandbox_kwarg,
        # fail after 3 errors
        fail_on_error=3,
    )

    log = eval(task, model="mockllm/model", max_samples=num_samples)[0]

    assert log.status == "error"
    assert log.samples is not None

    # the errored samples should have ValueError
    errored = [s for s in log.samples if s.id is not None and int(s.id) <= 3]
    for s in errored:
        assert s.error is not None
        assert "Error in sample" in s.error.message

    # some sleeping samples should have been cancelled and logged
    cancelled = [
        s
        for s in log.samples
        if s.id is not None and int(s.id) > 3 and s.error is not None
    ]
    assert len(cancelled) > 0


def test_all_concurrent_samples_accounted_for(sandbox_kwarg: str | None):
    """When fail_on_error cancels concurrent samples, ALL samples should appear in the log."""
    num_samples = 5
    task = Task(
        dataset=_make_samples(num_samples),
        solver=[error_or_sleep_solver()],
        scorer=includes(),
        sandbox=sandbox_kwarg,
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


def test_fail_on_error_no_retry_for_cancelled(sandbox_kwarg: str | None):
    """Cancelled samples should not be retried even when retry_on_error > 0."""
    num_samples = 3
    task = Task(
        dataset=_make_samples(num_samples),
        solver=[error_or_sleep_solver()],
        scorer=includes(),
        sandbox=sandbox_kwarg,
        fail_on_error=True,
    )

    log = eval(task, model="mockllm/model", max_samples=num_samples, retry_on_error=2)[
        0
    ]

    assert log.status == "error"
    assert log.samples is not None

    # cancelled samples should not have retries (they should appear once)
    cancelled = [s for s in log.samples if s.id != 1 and s.error is not None]
    # rule out vacuous pass: at least one cancelled sample must actually be present
    assert len(cancelled) > 0
    for s in cancelled:
        # cancelled samples should have no error retries
        assert s.error_retries is None or len(s.error_retries) == 0


def test_keyboard_interrupt_logs_cancelled_samples(
    tmp_path: Path, sandbox_kwarg: str | None
):
    """When SIGINT (KeyboardInterrupt) occurs, all running samples should be cancelled and logged."""
    num_samples = 5
    task = Task(
        dataset=_make_samples(num_samples),
        solver=[sleep_solver()],
        scorer=includes(),
        sandbox=sandbox_kwarg,
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


# --- unattributed ("foreign") cancellation escaping the solver ---------------

UNATTRIBUTED_PREFIX = (
    "RuntimeError('Sample errored: solver cancelled by an unattributed"
)


@solver
def saved_cancellation_solver(
    calls: list[int] | None = None, succeed_on_attempt: int | None = None
):
    """Re-raise the backend's cancellation after the scope that issued it exited.

    Backend-neutral: trio's `Cancelled` has no public constructor, but a
    library can save a real one and raise it later, which no inspect scope
    is delivering.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if calls is not None:
            calls.append(1)
            if succeed_on_attempt is not None and len(calls) >= succeed_on_attempt:
                return state
        saved: BaseException | None = None
        with anyio.CancelScope() as scope:
            scope.cancel()
            try:
                await anyio.sleep(10)
            except anyio.get_cancelled_exc_class() as ex:
                saved = ex
        assert saved is not None
        raise saved

    return solve


@solver
def fresh_cancelled_error_solver():
    """The issue's reproduction: a fresh `asyncio.CancelledError` (asyncio only)."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        raise asyncio.CancelledError()

    return solve


def _assert_unattributed_sample_errors(log: EvalLog, n_samples: int) -> None:
    assert log.status == "success"
    assert log.samples is not None and len(log.samples) == n_samples
    for sample in log.samples:
        assert sample.error is not None
        assert sample.error.message.startswith(UNATTRIBUTED_PREFIX)
        assert not is_cancellation_message(sample.error.message)
        assert not sample.scores
        assert any(isinstance(event, ErrorEvent) for event in sample.events)
    # every sample errored unscored, so no aggregate results are built
    assert log.results is None


async def test_unattributed_cancel_in_solver_is_sample_error(tmp_path: Path):
    (log,) = await eval_async(
        Task(
            dataset=_make_samples(2),
            solver=saved_cancellation_solver(),
            scorer=includes(),
        ),
        model="mockllm/model",
        log_dir=str(tmp_path),
        fail_on_error=False,
        ctl_server=False,
    )
    _assert_unattributed_sample_errors(log, 2)


async def test_unattributed_cancel_in_solver_fails_eval_by_default(tmp_path: Path):
    (log,) = await eval_async(
        Task(
            dataset=_make_samples(1),
            solver=saved_cancellation_solver(),
            scorer=includes(),
        ),
        model="mockllm/model",
        log_dir=str(tmp_path),
        ctl_server=False,
    )
    assert log.status == "error"
    assert log.error is not None
    assert log.error.message.startswith(UNATTRIBUTED_PREFIX)


async def test_unattributed_cancel_in_solver_is_retried(tmp_path: Path):
    calls: list[int] = []
    cleanups: list[int] = []

    async def cleanup(state: TaskState) -> None:
        await anyio.lowlevel.checkpoint()
        cleanups.append(1)

    (log,) = await eval_async(
        Task(
            dataset=_make_samples(1),
            solver=saved_cancellation_solver(calls=calls, succeed_on_attempt=2),
            scorer=includes(),
            cleanup=cleanup,
        ),
        model="mockllm/model",
        log_dir=str(tmp_path),
        retry_on_error=1,
        ctl_server=False,
    )
    assert log.status == "success"
    assert log.samples is not None
    (sample,) = log.samples
    assert sample.error is None
    assert sample.error_retries is not None and len(sample.error_retries) == 1
    assert sample.error_retries[0].message.startswith(UNATTRIBUTED_PREFIX)
    assert sample.scores
    assert len(calls) == 2
    assert len(cleanups) == 2


@skip_if_trio
async def test_fresh_asyncio_cancelled_error_is_sample_error(tmp_path: Path):
    (log,) = await eval_async(
        Task(
            dataset=_make_samples(2),
            solver=fresh_cancelled_error_solver(),
            scorer=includes(),
        ),
        model="mockllm/model",
        log_dir=str(tmp_path),
        fail_on_error=False,
        ctl_server=False,
    )
    _assert_unattributed_sample_errors(log, 2)


@skip_if_trio
async def test_unattributed_cancel_from_background_is_sample_error(tmp_path: Path):
    reached_after_await: list[int] = []

    @solver
    def background_cancel_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            started = anyio.Event()

            async def worker() -> None:
                await started.wait()
                raise asyncio.CancelledError()

            background(worker)
            started.set()
            await anyio.sleep_forever()
            reached_after_await.append(1)
            return state

        return solve

    (log,) = await eval_async(
        Task(
            dataset=_make_samples(1),
            solver=background_cancel_solver(),
            scorer=includes(),
        ),
        model="mockllm/model",
        log_dir=str(tmp_path),
        fail_on_error=False,
        ctl_server=False,
    )
    _assert_unattributed_sample_errors(log, 1)
    assert reached_after_await == []


async def test_enclosing_cancel_is_still_a_cancellation(tmp_path: Path):
    scopes: list[anyio.CancelScope] = []
    cleanups: list[int] = []

    @solver
    def cancel_enclosing_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            scopes[0].cancel()
            await anyio.sleep_forever()
            return state

        return solve

    async def cleanup(state: TaskState) -> None:
        cleanups.append(1)

    with anyio.CancelScope() as scope:
        scopes.append(scope)
        await eval_async(
            Task(
                dataset=_make_samples(1),
                solver=cancel_enclosing_solver(),
                scorer=includes(),
                cleanup=cleanup,
            ),
            model="mockllm/model",
            log_dir=str(tmp_path),
            fail_on_error=False,
            ctl_server=False,
        )

    (log_info,) = list_eval_logs(str(tmp_path))
    log = await read_eval_log_async(log_info)
    assert log.status == "cancelled"
    assert log.samples is not None
    (sample,) = log.samples
    assert sample.error is not None
    assert is_cancellation_message(sample.error.message)
    assert not sample.error.message.startswith(UNATTRIBUTED_PREFIX)
    assert cleanups == [1]


@skip_if_trio
async def test_context_chained_cancel_is_not_unattributed(tmp_path: Path):
    """A fresh CancelledError chained to anyio's own is anyio's, not foreign.

    Today it becomes `fail_after`'s TimeoutError, which reaches the top of
    the sample stack and is scored with a warning; asserted so that a change
    to that path is deliberate.
    """

    @solver
    def chained_cancel_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            with anyio.fail_after(0.01):
                try:
                    await anyio.sleep(10)
                except anyio.get_cancelled_exc_class():
                    raise asyncio.CancelledError()
            return state

        return solve

    (log,) = await eval_async(
        Task(
            dataset=_make_samples(1),
            solver=chained_cancel_solver(),
            scorer=includes(),
        ),
        model="mockllm/model",
        log_dir=str(tmp_path),
        fail_on_error=False,
        ctl_server=False,
    )
    assert log.status == "success"
    assert log.samples is not None
    (sample,) = log.samples
    assert sample.error is None
    assert sample.scores
