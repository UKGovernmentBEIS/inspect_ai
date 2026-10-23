"""Tests for cancellation error handling and logging.

Verifies that when samples are cancelled (due to another sample's error
with fail_on_error, or due to a KeyboardInterrupt), the cancelled samples
are fully logged with their errors in the eval log.
"""

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

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
def sleep_solver(on_start: Callable[[], None]):
    """All samples call `on_start` then sleep; used with external SIGINT."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        on_start()
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
    started: list[int] = []
    all_started = threading.Event()

    def on_start() -> None:
        started.append(1)
        if len(started) == num_samples:
            all_started.set()

    task = Task(
        dataset=_make_samples(num_samples),
        solver=[sleep_solver(on_start)],
        scorer=includes(),
        sandbox=sandbox_kwarg,
    )

    # send SIGINT from a background thread once every sample is running (a
    # fixed delay can fire before eval starts on a loaded machine)
    def send_sigint() -> None:
        if all_started.wait(timeout=60):
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
    assert all_started.is_set()

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


# Run in a subprocess so trio evals share no process-global state with the
# asyncio test process.
_TRIO_KEYBOARD_INTERRUPT_SCRIPT = """
import contextlib
import signal
import sys
import tempfile

import anyio

import inspect_ai._display.core.active as active_display
import inspect_ai._eval.eval as eval_module
import inspect_ai._eval.task.run as task_run
import inspect_ai.util._display as display_state
from inspect_ai import Task, eval
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.dataset import Sample
from inspect_ai.hooks import Hooks, RunEnd, hooks
from inspect_ai.log import list_eval_logs, read_eval_log
from inspect_ai.scorer import includes
from inspect_ai.solver import solver

NUM_SAMPLES = 3
with_sandbox = sys.argv[1] == "with_sandbox"
run_ends = []
sigint_in_hook = False
sigint_in_cleanup = False
events = []

if with_sandbox:
    # the sandbox_kwarg fixture's fake: teardown awaits
    @contextlib.asynccontextmanager
    async def fake_sandboxenv_context(*args, **kwargs):
        try:
            yield
        finally:
            await anyio.sleep(0.05)

    task_run.sandboxenv_context = fake_sandboxenv_context


@hooks(name="run_end_probe", description="Records run ends.")
class RunEndProbe(Hooks):
    async def on_run_end(self, data: RunEnd) -> None:
        run_ends.append(data)
        events.append("hook")
        if sigint_in_hook:
            signal.raise_signal(signal.SIGINT)
        await anyio.sleep(0)


cleanup_sample_buffers = eval_module.cleanup_sample_buffers


async def recording_cleanup(log_dir):
    events.append("cleanup")
    if sigint_in_cleanup:
        signal.raise_signal(signal.SIGINT)
    await cleanup_sample_buffers(log_dir)


eval_module.cleanup_sample_buffers = recording_cleanup


@solver
def sigint_once_all_started(interrupt: bool):
    started = []

    async def solve(state, generate):
        if not interrupt:
            return state
        started.append(state.sample_id)
        if len(started) == NUM_SAMPLES:
            signal.raise_signal(signal.SIGINT)
        await anyio.sleep(60)
        return state

    return solve


def use_display(display):
    active_display._active_display = None
    display_state._display_type = None


def run_eval(display, log_dir, interrupt):
    use_display(display)
    eval(
        Task(
            dataset=[Sample(input="x", target="x", id=i) for i in range(NUM_SAMPLES)],
            solver=sigint_once_all_started(interrupt),
            scorer=includes(),
            sandbox="local" if with_sandbox else None,
        ),
        model="mockllm/model",
        max_samples=NUM_SAMPLES,
        log_dir=log_dir,
        display=display,
        ctl_server=False,
    )
    (log_info,) = list_eval_logs(log_dir)
    return read_eval_log(log_info.name)


for display in ["rich", "plain", "log"]:
    use_display(display)
    try:
        eval([], model="mockllm/model", ctl_server="invalid", display=display)
    except PrerequisiteError:
        pass
    else:
        raise AssertionError(f"{display}: validation error not raised")

    log_dir = tempfile.mkdtemp()
    hooks_before = len(run_ends)
    events.clear()
    try:
        run_eval(display, log_dir, interrupt=True)
    except KeyboardInterrupt as ex:
        assert type(ex) is KeyboardInterrupt, repr(ex)
    else:
        raise AssertionError(f"{display}: no KeyboardInterrupt")
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler

    (log_info,) = list_eval_logs(log_dir)
    log = read_eval_log(log_info.name)
    assert log.status == "cancelled", (display, log.status)
    assert log.samples is not None and len(log.samples) == NUM_SAMPLES, display
    assert all(sample.error is not None for sample in log.samples), display
    assert events == ["cleanup", "hook"], (display, events)
    assert len(run_ends) == hooks_before + 1, (display, run_ends)
    run_end = run_ends[-1]
    assert run_end.exception is None, (display, repr(run_end.exception))
    assert [run_log.status for run_log in run_end.logs] == ["cancelled"], display
    assert run_end.logs[0].eval.eval_id == log.eval.eval_id, display

# a second Ctrl-C raised in the run-end hook interrupts without rerunning it
sigint_in_hook = True
for display in ["rich", "plain", "log"]:
    hooks_before = len(run_ends)
    try:
        run_eval(display, tempfile.mkdtemp(), interrupt=True)
    except KeyboardInterrupt as ex:
        assert type(ex) is KeyboardInterrupt, repr(ex)
    else:
        raise AssertionError(f"{display}: no KeyboardInterrupt")
    assert len(run_ends) == hooks_before + 1, (display, run_ends)
sigint_in_hook = False

# a second Ctrl-C raised in buffer cleanup interrupts without starting the hooks
sigint_in_cleanup = True
for display in ["rich", "plain", "log"]:
    events.clear()
    try:
        run_eval(display, tempfile.mkdtemp(), interrupt=True)
    except KeyboardInterrupt as ex:
        assert type(ex) is KeyboardInterrupt, repr(ex)
    else:
        raise AssertionError(f"{display}: no KeyboardInterrupt")
    assert events == ["cleanup"], (display, events)
sigint_in_cleanup = False

# a later eval() in the same process still runs
assert run_eval("rich", tempfile.mkdtemp(), interrupt=False).status == "success"
"""


@pytest.mark.parametrize("sandbox", ["with_sandbox", "no_sandbox"])
def test_keyboard_interrupt_under_trio(sandbox: str):
    """Under trio, Ctrl-C during eval() logs the cancelled samples, gives run-end hooks that log and raises KeyboardInterrupt.

    Covers the rich, plain and log displays, that an eval() error without a
    SIGINT is not masked, that a second SIGINT raised in a run-end hook does
    not rerun it, that a second SIGINT raised in buffer cleanup does not start
    the hooks, and that a later eval() still runs.
    """
    result = subprocess.run(
        [sys.executable, "-I", "-c", _TRIO_KEYBOARD_INTERRUPT_SCRIPT, sandbox],
        env={**os.environ, "INSPECT_ASYNC_BACKEND": "trio"},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr


_INTERRUPT_DURING_FINALIZATION_SCRIPT = """
import signal
import tempfile

import anyio
import anyio.lowlevel

import inspect_ai._display.core.active as active_display
import inspect_ai._eval.eval as eval_module
import inspect_ai.util._display as display_state
from inspect_ai import Task, eval, eval_retry, eval_set, task
from inspect_ai.dataset import Sample
from inspect_ai.hooks import Hooks, RunEnd, hooks
from inspect_ai.log import list_eval_logs, read_eval_log
from inspect_ai.scorer import includes
from inspect_ai.solver import solver

events = []
run_ends = []
sigint_in = None
# what the probe task's sample does: None (succeed), "fail" or "sigint"
sample_does = None


async def interrupt_in(where):
    global sigint_in
    if sigint_in == where:
        sigint_in = None
        signal.raise_signal(signal.SIGINT)
        await anyio.sleep(0.1)
        events.append(f"{where} finished")


@hooks(name="run_end_probe", description="Records run ends.")
class RunEndProbe(Hooks):
    async def on_run_end(self, data: RunEnd) -> None:
        run_ends.append(data)
        events.append("hook")
        await interrupt_in("hook")
        await anyio.lowlevel.checkpoint()
        events.append("hook returned")


cleanup_sample_buffers = eval_module.cleanup_sample_buffers


async def recording_cleanup(log_dir):
    events.append("cleanup")
    await interrupt_in("cleanup")
    await cleanup_sample_buffers(log_dir)


eval_module.cleanup_sample_buffers = recording_cleanup


@solver
def probe_solver():
    async def solve(state, generate):
        if sample_does == "fail":
            raise RuntimeError("fail so there is something to retry")
        elif sample_does == "sigint":
            signal.raise_signal(signal.SIGINT)
            await anyio.sleep(60)
        return state

    return solve


@task
def interrupt_probe():
    return Task(
        dataset=[Sample(input="x", target="x")], solver=probe_solver(), scorer=includes()
    )


def use_display(display):
    active_display._active_display = None
    display_state._display_type = None


def run_eval(display, log_dir=None):
    use_display(display)
    return eval(
        interrupt_probe(),
        model="mockllm/model",
        log_dir=log_dir or tempfile.mkdtemp(),
        display=display,
        ctl_server=False,
    )


def assert_interrupted(display, run):
    try:
        run()
    except KeyboardInterrupt as ex:
        assert type(ex) is KeyboardInterrupt, repr(ex)
    else:
        raise AssertionError(f"{display}: no KeyboardInterrupt")
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


def disk_statuses(log_dir):
    return sorted(read_eval_log(info.name).status for info in list_eval_logs(log_dir))


# a Ctrl-C during buffer cleanup or the run-end hook of a finished run ends it:
# the hook then runs (again) with the cancellation, and finishes
expected = {
    "cleanup": ["cleanup", "hook", "hook returned"],
    "hook": ["cleanup", "hook", "hook", "hook returned"],
}
for where in ["cleanup", "hook"]:
    for display in ["rich", "plain", "log"]:
        sigint_in = where
        events.clear()
        run_ends.clear()
        assert_interrupted(display, lambda: run_eval(display))
        assert events == expected[where], (where, display, events)
        assert run_ends[-1].exception is not None, (where, display)

# a Ctrl-C while samples run with an awaiting run-end hook raises
# KeyboardInterrupt from eval(), eval_retry() and eval_set()
for display in ["rich", "plain", "log"]:
    log_dir = tempfile.mkdtemp()
    sample_does = "fail"
    (failed,) = run_eval(display, log_dir)
    assert failed.status == "error", display

    sample_does = "sigint"
    assert_interrupted(display, lambda: run_eval(display, log_dir))
    use_display(display)
    assert_interrupted(
        display,
        lambda: eval_retry(failed, log_dir=log_dir, display=display, ctl_server=False),
    )
    assert disk_statuses(log_dir) == ["cancelled", "cancelled", "error"], display

    set_dir = tempfile.mkdtemp()
    use_display(display)
    assert_interrupted(
        display,
        lambda: eval_set(
            interrupt_probe(),
            log_dir=set_dir,
            model="mockllm/model",
            display=display,
            ctl_server=False,
        ),
    )
    assert disk_statuses(set_dir) == ["cancelled"], display


# a later eval() in the same process still runs
sample_does = None
assert run_eval("rich")[0].status == "success"
"""


@pytest.mark.parametrize("backend", ["asyncio", "trio"], ids=["on_asyncio", "on_trio"])
def test_keyboard_interrupt_during_run_finalization(backend: str):
    """Ctrl-C with an awaiting run-end hook raises KeyboardInterrupt.

    A Ctrl-C during buffer cleanup or the hook of a finished run, and one
    while samples run, raises from eval(), eval_retry() and eval_set(), and a
    later eval() still runs.
    """
    result = subprocess.run(
        [sys.executable, "-I", "-c", _INTERRUPT_DURING_FINALIZATION_SCRIPT],
        env={**os.environ, "INSPECT_ASYNC_BACKEND": backend},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr


_TRIO_EVAL_RETRY_INTERRUPT_SCRIPT = """
import signal
import tempfile

import anyio

import inspect_ai._display.core.active as active_display
import inspect_ai.util._display as display_state
from inspect_ai import Task, eval, eval_retry, task
from inspect_ai.dataset import Sample
from inspect_ai.hooks import Hooks, RunStart, hooks
from inspect_ai.solver import solver

retrying = False
run_starts = []
retried_samples = []


@hooks(name="run_start_probe", description="Records run starts.")
class RunStartProbe(Hooks):
    async def on_run_start(self, data: RunStart) -> None:
        run_starts.append(data.run_id)


@solver
def fail_then_interrupt():
    async def solve(state, generate):
        if not retrying:
            raise RuntimeError("fail so there is something to retry")
        retried_samples.append(state.sample_id)
        signal.raise_signal(signal.SIGINT)
        await anyio.sleep(60)
        return state

    return solve


@task
def retry_probe():
    return Task(dataset=[Sample(input="x", target="x")], solver=fail_then_interrupt())


def use_display(display):
    active_display._active_display = None
    display_state._display_type = None


for display in ["rich", "plain", "log"]:
    log_dir = tempfile.mkdtemp()
    retrying = False
    failed = []
    for _ in range(2):
        use_display(display)
        failed.extend(
            eval(
                retry_probe(),
                model="mockllm/model",
                log_dir=log_dir,
                display=display,
                ctl_server=False,
            )
        )
    assert [log.status for log in failed] == ["error", "error"], display

    retrying = True
    run_starts.clear()
    retried_samples.clear()
    use_display(display)
    try:
        eval_retry(failed, log_dir=log_dir, display=display, ctl_server=False)
    except KeyboardInterrupt as ex:
        assert type(ex) is KeyboardInterrupt, repr(ex)
    else:
        raise AssertionError(f"{display}: no KeyboardInterrupt")
    assert len(run_starts) == 1, (display, run_starts)
    assert len(retried_samples) == 1, (display, retried_samples)
"""


def test_keyboard_interrupt_under_trio_stops_eval_retry():
    """Under trio, Ctrl-C during the first of two retries does not start the second."""
    result = subprocess.run(
        [sys.executable, "-I", "-c", _TRIO_EVAL_RETRY_INTERRUPT_SCRIPT],
        env={**os.environ, "INSPECT_ASYNC_BACKEND": "trio"},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr


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
