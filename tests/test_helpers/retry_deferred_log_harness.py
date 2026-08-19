"""Harness for the deferred-destination-log crash test.

See ``design/retry-deferred-destination-log.md``. Run as a script::

    python tests/test_helpers/retry_deferred_log_harness.py <log_dir> <probe_dir>

With ``INSPECT_TEST_KILL_AT_SETTLE=1`` the process ``SIGKILL``s itself the
moment a retry attempt's reuse sweep settles — the window in which the attempt
has started but has not yet written its destination log. Running that attempt
in a child process is what lets the test issue a real, unrecoverable kill
without taking down pytest.
"""

from __future__ import annotations

import os
import signal
import sys

import anyio

from inspect_ai import Task, eval_set, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import TaskState, solver

KILL_AT_SETTLE_ENV = "INSPECT_TEST_KILL_AT_SETTLE"


def _kill_at_settle() -> bool:
    return os.environ.get(KILL_AT_SETTLE_ENV) == "1"


def install_settle_kill() -> None:
    """Die at the reuse-sweep settle, before the settle flush writes."""
    from inspect_ai._eval.task.log import TaskLogger

    async def kill_at_settle(self: TaskLogger, even_if_empty: bool = False) -> None:
        os.kill(os.getpid(), signal.SIGKILL)
        await anyio.sleep_forever()  # unreachable; SIGKILL is immediate

    TaskLogger._quiet_settle_flush = kill_at_settle  # type: ignore[method-assign]


async def _s1_logged_clean(log_dir: str) -> bool:
    """Whether some log in `log_dir` already holds a clean copy of s1."""
    from inspect_ai.log import list_eval_logs
    from inspect_ai.log._file import read_eval_log_sample_async

    for info in list_eval_logs(log_dir):
        try:
            sample = await read_eval_log_sample_async(info.name, "s1", 1)
        except Exception:
            continue
        if sample.error is None:
            return True
    return False


@solver
def _crash_probe_solver(log_dir: str, probe_dir: str):
    calls_file = os.path.join(probe_dir, "solver_calls.txt")
    failed_marker = os.path.join(probe_dir, "s2_failed")

    async def solve(state: TaskState, generate):
        with open(calls_file, "a") as f:
            f.write(f"{state.sample_id}\n")
        if state.sample_id == "s2":
            if not os.path.exists(failed_marker):
                # fail only once s1 is durable in the log, so the retry
                # deterministically has a completed sample to reuse (the
                # error otherwise tears down s1's still-running sample)
                with anyio.fail_after(60):
                    while not await _s1_logged_clean(log_dir):
                        await anyio.sleep(0.1)
                open(failed_marker, "w").close()
                raise ValueError("s2 fails on the first attempt")
            if _kill_at_settle():
                # the retry attempt is expected to end by the settle kill,
                # never by finishing this sample. Bounded rather than
                # sleep_forever so a kill that never lands surfaces as the
                # test's own assertion (an extra log) instead of a timeout.
                await anyio.sleep(60)
        return state

    return solve


@task
def crash_probe_task(log_dir: str, probe_dir: str) -> Task:
    return Task(
        dataset=[
            Sample(id="s1", input="Say hello", target="hello"),
            Sample(id="s2", input="Say hello again", target="hello"),
        ],
        solver=[_crash_probe_solver(log_dir, probe_dir)],
        name="crash_probe_task",
    )


def main() -> None:
    log_dir, probe_dir = sys.argv[1], sys.argv[2]
    if _kill_at_settle():
        install_settle_kill()
    eval_set(
        tasks=[crash_probe_task(log_dir, probe_dir)],
        log_dir=log_dir,
        model="mockllm/model",
        retry_attempts=1,
        max_samples=2,
    )


if __name__ == "__main__":
    main()
