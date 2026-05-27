"""Integration tests: control endpoint vs `eval_set` with multiple tasks.

Pins the contract that ``inspect ctl ls`` (and the underlying
``GET /evals`` endpoint) lists each running eval as a distinct entry,
even when several share a parent process (the eval-set lifecycle).
"""

import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import anyio
import httpx
import pytest

from inspect_ai import Task, task
from inspect_ai._control.discovery import list_discovered_servers
from inspect_ai._eval.evalset import eval_set
from inspect_ai.dataset import Sample
from inspect_ai.log._samples import active_samples
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver


@pytest.fixture
def short_data_dir(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Short data dir under /tmp so AF_UNIX paths fit in 104 chars.

    macOS pytest tmp_path lives under ``/private/var/folders/...``
    which blows past the AF_UNIX limit. Patches both control and ACP
    discovery modules so neither subsystem writes outside the test's
    sandbox.
    """
    dirpath = Path(tempfile.mkdtemp(prefix="ctl_es_", dir="/tmp"))

    def _stub(subdir: str | None) -> Path:
        path = (dirpath / (subdir or "")).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr("inspect_ai._control.discovery.inspect_data_dir", _stub)
    monkeypatch.setattr("inspect_ai.agent._acp.discovery.inspect_data_dir", _stub)
    try:
        yield dirpath
    finally:
        # Best-effort cleanup; servers normally remove their own files,
        # but the dir + any stragglers stay for post-mortem on failure.
        for p in dirpath.rglob("*"):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            for sub in sorted(dirpath.rglob("*"), reverse=True):
                if sub.is_dir():
                    sub.rmdir()
            dirpath.rmdir()
        except OSError:
            pass


def _wait_until(predicate: callable, timeout: float = 30.0) -> bool:
    """Poll ``predicate`` until it returns truthy or ``timeout`` elapses.

    Cooperative wait (50ms tick) — used in lieu of a fixed sleep so the
    test only blocks as long as the eval-set needs to come up.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


@pytest.mark.slow
def test_ctl_ls_lists_each_eval_in_an_eval_set(short_data_dir: Path) -> None:
    """An eval-set with N concurrent tasks should produce N entries in ls.

    Today the control endpoint groups by ``run_id`` (one per
    ``eval()`` call — eval-set passes all tasks in one such call) and
    returns a single aggregate summary whose ``tasks`` field lists
    both task names. Consumers (the CLI, TUIs, agents) want one row
    per running eval — keyed by ``eval_id`` — so each row carries its
    own task, sample counts, model usage, started_at.

    Failing test (red): demonstrates the regression. Fix lives in
    ``inspect_ai._control.state.current_eval_summary`` → emit one
    entry per ``eval_id``.
    """
    release = threading.Event()

    @solver
    def hanging_solver() -> Solver:
        async def solve(state: TaskState, generate) -> TaskState:  # type: ignore[no-untyped-def]
            # Cooperative wait — yields the eval's event loop so the
            # sample registers as in-flight, but doesn't complete
            # until the test releases us.
            while not release.is_set():
                await anyio.sleep(0.05)
            return state

        return solve

    @task
    def task_alpha() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")],
            solver=[hanging_solver()],
            name="task_alpha",
        )

    @task
    def task_beta() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")],
            solver=[hanging_solver()],
            name="task_beta",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    result_ref: dict[str, object] = {}

    def run_eval_set() -> None:
        try:
            ok, _logs = eval_set(
                tasks=[task_alpha(), task_beta()],
                log_dir=log_dir,
                model="mockllm/model",
                max_tasks=2,
                retry_attempts=0,
            )
            result_ref["ok"] = ok
        except BaseException as exc:  # noqa: BLE001
            result_ref["error"] = exc

    thread = threading.Thread(target=run_eval_set, name="eval_set_test")
    thread.start()
    try:
        # Wait for both tasks' samples to register in the process's
        # active_samples registry (proves the eval is past the bind /
        # spawn phase) AND the discovery file to be written.
        ready = _wait_until(
            lambda: (
                len([s for s in active_samples() if s.started is not None]) >= 2
                and bool(list_discovered_servers())
            )
        )
        assert ready, (
            f"eval_set didn't bring up two in-flight samples + a control server "
            f"within timeout. active_samples={len(active_samples())}, "
            f"servers={len(list_discovered_servers())}, error={result_ref.get('error')}"
        )

        servers = list_discovered_servers()
        assert len(servers) == 1, (
            f"expected one discovery file (one process), got {len(servers)}"
        )
        socket_path = servers[0].socket_path

        # Query the live endpoint over its AF_UNIX socket.
        transport = httpx.HTTPTransport(uds=str(socket_path))
        with httpx.Client(
            transport=transport,
            base_url="http://localhost",
            timeout=5.0,
        ) as client:
            response = client.get("/evals")
            response.raise_for_status()
            evals = response.json()

        assert len(evals) == 2, (
            f"expected one entry per running eval (2 total), got {len(evals)}: {evals}"
        )
        # Each entry carries a single task name (its own).
        task_names = sorted(entry["task"] for entry in evals)
        assert task_names == ["task_alpha", "task_beta"], (
            f"expected per-eval task names, got: {[e.get('task') for e in evals]}"
        )
        # Each entry's eval_id should be distinct.
        eval_ids = {entry["eval_id"] for entry in evals}
        assert len(eval_ids) == 2, f"expected two distinct eval_ids, got {eval_ids}"
        # They all share the same run_id (one eval-set, one process).
        run_ids = {entry["run_id"] for entry in evals}
        assert len(run_ids) == 1, f"expected single shared run_id, got {run_ids}"
    finally:
        release.set()
        thread.join(timeout=60)
        assert not thread.is_alive(), "eval_set thread didn't finish after release"
        # Re-raise any error captured inside the thread so the test
        # surfaces eval-set failures rather than masking them.
        err = result_ref.get("error")
        if err is not None:
            raise err  # type: ignore[misc]


@pytest.mark.slow
def test_ctl_ls_survives_fast_task_finishing_first(short_data_dir: Path) -> None:
    """A fast-finishing task doesn't tear down the control surface for its sibling.

    Pins the architectural invariant: the control_server lifecycle is
    per-``eval()``-call (wrapping the whole task batch + scoring),
    NOT per-task. ``<pid>.json`` / ``<pid>.sock`` are PID-keyed —
    pushing the lifecycle down to per-task would collide on those
    paths and corrupt the surface when one task finishes.

    Scenario: task_fast runs ``generate()`` (mockllm returns
    immediately, sample completes quickly). task_slow hangs until the
    test releases it. After task_fast has finished but before
    task_slow has, ``ls`` must still work and report the slow eval.
    """
    release = threading.Event()

    @solver
    def hanging_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            while not release.is_set():
                await anyio.sleep(0.05)
            return state

        return solve

    @task
    def task_fast() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")],
            solver=[generate()],
            name="task_fast",
        )

    @task
    def task_slow() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")],
            solver=[hanging_solver()],
            name="task_slow",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    result_ref: dict[str, object] = {}

    def run_eval_set() -> None:
        try:
            ok, _logs = eval_set(
                tasks=[task_fast(), task_slow()],
                log_dir=log_dir,
                model="mockllm/model",
                max_tasks=2,
                retry_attempts=0,
            )
            result_ref["ok"] = ok
        except BaseException as exc:  # noqa: BLE001
            result_ref["error"] = exc

    thread = threading.Thread(target=run_eval_set, name="eval_set_fast_slow")
    thread.start()
    try:
        # Wait for the control server to bind AND task_fast to have
        # completed (only task_slow's sample left in active_samples).
        # The second condition proves we're past task_fast's completion
        # — if the control_server lifecycle were per-task, this is the
        # window where its context would have unlinked the shared files.
        ready = _wait_until(
            lambda: (
                bool(list_discovered_servers())
                and len(active_samples()) == 1
                and any(s.task == "task_slow" for s in active_samples())
            )
        )
        assert ready, (
            f"didn't reach 'task_fast done, task_slow still running' state. "
            f"active_samples={[s.task for s in active_samples()]}, "
            f"servers={len(list_discovered_servers())}, "
            f"error={result_ref.get('error')}"
        )

        # The control surface must still be alive and queryable.
        servers = list_discovered_servers()
        assert len(servers) == 1, (
            f"discovery file vanished (or duplicated) after task_fast finished; "
            f"got {len(servers)} servers"
        )

        # And the endpoint should return something — at minimum, the
        # slow eval. Whether the count is 1 (only running evals) or 2
        # (running + just-completed) is the per-eval-id grouping
        # question pinned by the previous test; this test pins only
        # that the surface still works.
        transport = httpx.HTTPTransport(uds=str(servers[0].socket_path))
        with httpx.Client(
            transport=transport,
            base_url="http://localhost",
            timeout=5.0,
        ) as client:
            response = client.get("/evals")
            response.raise_for_status()
            evals = response.json()

        assert len(evals) >= 1, "control endpoint returned no entries"
        # task_slow must be present somewhere in the response.
        all_tasks = {entry["task"] for entry in evals}
        assert "task_slow" in all_tasks, (
            f"task_slow missing from response; got tasks={all_tasks}"
        )
    finally:
        release.set()
        thread.join(timeout=60)
        assert not thread.is_alive(), "eval_set thread didn't finish after release"
        err = result_ref.get("error")
        if err is not None:
            raise err  # type: ignore[misc]
