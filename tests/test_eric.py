"""Tests for cancellation error handling and logging.

Verifies that when samples are cancelled (due to another sample's error
with fail_on_error, or due to a KeyboardInterrupt), the cancelled samples
are fully logged with their errors in the eval log.
"""

import contextlib

import anyio
import pytest

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import Generate, TaskState, solver


def _make_samples(n: int) -> list[Sample]:
    """Create n samples with explicit integer IDs (1-indexed)."""
    return [Sample(input=f"Sample {i}", target="target", id=i) for i in range(1, n + 1)]


def test_in_flight_sample_with_awaiting_sandbox_teardown_is_logged(
    monkeypatch: pytest.MonkeyPatch,
):
    """An in-flight sample whose sandbox teardown *awaits* must still be logged when the eval is cancelled.

    Same scenario as test_all_concurrent_samples_accounted_for, with one added
    variable: a sandbox whose teardown awaits (like a real container teardown).
    On cancel, the unshielded sandbox-context __aexit__ is re-cancelled under the
    still-active eval cancel scope, which drops the in-flight sample from the log.
    """

    # fake sandbox context whose teardown awaits (mimics a container teardown)
    @contextlib.asynccontextmanager
    async def awaiting_teardown_sandbox(*args, **kwargs):
        try:
            yield
        finally:
            print("tearing down sandbox", flush=True)
            # [ROOT C: FATAL-AWAIT] stands in for sandbox.py's real teardown await;
            # under the still-cancelled scope this raises a fresh CancelledError, so
            # "sandbox down" never prints (mirrors sandbox.py [ROOT C]).
            await anyio.sleep(0.2)
            print("sandbox down", flush=True)

    monkeypatch.setattr(
        "inspect_ai._eval.task.run.sandboxenv_context", awaiting_teardown_sandbox
    )

    started: set[int] = set()

    @solver
    def trigger_or_sleep_solver():
        """Sample 1 errors once the in-flight sample has entered; sample 2 sleeps."""

        async def solve(state: TaskState, generate: Generate) -> TaskState:
            sid = int(state.sample_id)
            print(f"[sid={sid}] solve called", flush=True)
            started.add(sid)
            if sid == 1:
                # gate: don't trigger cancellation until the in-flight sample is
                # actually mid-solver, so a missing sample proves a true drop
                while 2 not in started:
                    await anyio.sleep(0.01)
                print("raising ValueError in 1")
                raise ValueError("Intentional test error")
            await anyio.sleep(30)
            return state

        return solve

    task = Task(
        dataset=_make_samples(2),
        solver=[trigger_or_sleep_solver()],
        scorer=includes(),
        sandbox="local",
        fail_on_error=True,
    )

    log = eval(task, model="mockllm/model", max_samples=2)[0]

    assert log.status == "error"
    assert log.samples is not None

    # the in-flight sample actually started (rules out "never started")
    assert started == {1, 2}

    # both samples must be present -- the in-flight sample (id=2) is dropped today
    logged_ids = {s.id for s in log.samples}
    assert logged_ids == {1, 2}
