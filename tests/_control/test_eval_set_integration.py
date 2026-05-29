"""Integration tests: control endpoint vs `eval_set` with multiple tasks.

Pins the contract that ``inspect ctl ls`` (and the underlying
``GET /evals`` endpoint) lists each running eval as a distinct entry,
even when several share a parent process (the eval-set lifecycle).
"""

import tempfile
import threading
import time
from collections.abc import Callable, Iterator
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


def _wait_until(predicate: Callable[[], bool], timeout: float = 30.0) -> bool:
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
        async def solve(state: TaskState, generate: Generate) -> TaskState:
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
        # Each entry exposes a `samples` block with the expected shape.
        for entry in evals:
            samples = entry["samples"]
            assert samples["total"] == 1, (
                f"each task has 1 sample; got total={samples['total']}"
            )
            assert samples["in_flight"] == 1, (
                f"both samples hanging in slow_solver; got in_flight="
                f"{samples['in_flight']}"
            )
            assert samples["completed"] == 0
            assert samples["errored"] == 0
            assert samples["queued"] == 0
            # Status reflects "still running" while samples are in flight.
            assert entry["status"] == "running", (
                f"expected status='running' with samples in flight, got "
                f"{entry['status']!r}"
            )
            assert entry["completed_at"] is None, (
                "completed_at should be None while samples still in flight"
            )
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


@pytest.mark.slow
def test_keep_alive_blocks_after_eval_set_until_shutdown(
    short_data_dir: Path,
) -> None:
    """eval-set(--keep-alive) blocks after completion until /shutdown.

    Pins three things together:

    1. The eval-set body completes (all samples done, ``ls`` shows
       ``samples.completed == total``) — so the agent has consistent
       state to read.
    2. The process does NOT exit immediately — the eval-set thread is
       still blocking on the shutdown event.
    3. Posting ``POST /shutdown`` (or running ``inspect ctl
       shutdown``) releases the block; the eval-set thread returns.

    Verifies the contract that makes the agent workflow safe:
    "agent runs eval-set, inspects results, decides next step,
    explicitly tells the process to exit." Without keep-alive the
    process would race the agent and the discovery file would vanish
    mid-inspection.
    """

    @task
    def task_quick() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")],
            solver=[generate()],
            name="task_quick",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    result_ref: dict[str, object] = {}

    def run_eval_set() -> None:
        try:
            ok, _logs = eval_set(
                tasks=[task_quick()],
                log_dir=log_dir,
                model="mockllm/model",
                retry_attempts=0,
                keep_alive=True,
            )
            result_ref["ok"] = ok
        except BaseException as exc:  # noqa: BLE001
            result_ref["error"] = exc

    thread = threading.Thread(target=run_eval_set, name="eval_set_keep_alive")
    thread.start()
    try:
        # 1. Eval completes: samples.completed reaches 1.
        ready = _wait_until(
            lambda: _eval_completed(),
            timeout=30.0,
        )
        assert ready, (
            f"eval didn't reach completed state. servers={list_discovered_servers()}, "
            f"error={result_ref.get('error')}"
        )

        # 2. Process still alive, thread still running (blocking on shutdown).
        assert thread.is_alive(), "process exited before shutdown was requested"
        servers = list_discovered_servers()
        assert len(servers) == 1, "discovery file vanished while keep-alive active"

        # Status / completed_at should reflect "this eval is done" so
        # an agent can tell when it's safe to stop polling.
        transport = httpx.HTTPTransport(uds=str(servers[0].socket_path))
        with httpx.Client(
            transport=transport, base_url="http://localhost", timeout=5.0
        ) as client:
            response = client.get("/evals")
            response.raise_for_status()
            entries = response.json()
        assert len(entries) == 1
        entry = entries[0]
        assert entry["status"] == "completed", (
            f"expected status='completed' under keep-alive after the eval "
            f"finished, got {entry['status']!r}"
        )
        assert entry["completed_at"] is not None, (
            "expected completed_at to be set; got None"
        )
        assert entry["completed_at"] >= entry["started_at"], (
            "completed_at must be >= started_at"
        )

        # Give the eval-set wait a moment to settle, then re-confirm
        # the thread really is parked (it hasn't just been slow to
        # return). 0.5s is well under any timeout that would cause a
        # flaky failure here.
        time.sleep(0.5)
        assert thread.is_alive(), (
            "eval-set thread exited without an explicit shutdown — "
            "keep-alive didn't actually block"
        )

        # 3. POST /shutdown should release the block.
        with httpx.Client(
            transport=transport, base_url="http://localhost", timeout=5.0
        ) as client:
            response = client.post("/shutdown")
            response.raise_for_status()

        thread.join(timeout=30.0)
        assert not thread.is_alive(), (
            "eval-set thread didn't exit within 30s after POST /shutdown"
        )

        # After shutdown the discovery file should be gone (server stopped).
        assert not list_discovered_servers(), "discovery file lingered after shutdown"

        err = result_ref.get("error")
        if err is not None:
            raise err  # type: ignore[misc]
        assert result_ref.get("ok") is True, "eval_set didn't report success"
    finally:
        # Belt-and-suspenders: if anything went wrong, make sure we
        # tear down the eval-set thread so the test process can exit.
        if thread.is_alive():
            try:
                servers = list_discovered_servers()
                if servers:
                    transport = httpx.HTTPTransport(uds=str(servers[0].socket_path))
                    with httpx.Client(
                        transport=transport,
                        base_url="http://localhost",
                        timeout=2.0,
                    ) as client:
                        client.post("/shutdown")
            except Exception:
                pass
            thread.join(timeout=30.0)


def _eval_completed() -> bool:
    """Predicate: is there a discovered server whose eval is complete?

    Used by the keep-alive test to wait until the eval body has
    finished (samples.completed == samples.total) before checking
    that the process is parked.
    """
    servers = list_discovered_servers()
    if not servers:
        return False
    try:
        transport = httpx.HTTPTransport(uds=str(servers[0].socket_path))
        with httpx.Client(
            transport=transport, base_url="http://localhost", timeout=1.0
        ) as client:
            response = client.get("/evals")
            response.raise_for_status()
            entries = response.json()
    except (httpx.HTTPError, OSError):
        return False
    if not entries:
        return False
    samples = entries[0].get("samples", {})
    total = samples.get("total", 0)
    completed = samples.get("completed", 0)
    return bool(total > 0 and completed >= total)


@pytest.mark.slow
def test_ctl_ls_shows_reused_logs_as_completed(short_data_dir: Path) -> None:
    """Pre-existing successful eval logs should appear in ``ctl ls``.

    When ``eval_set()`` is re-invoked over a log_dir that already
    contains successful logs for some of the requested tasks, those
    tasks are NOT re-run — their logs are reused as-is. The remaining
    fresh tasks run through ``eval()`` normally, bringing up the
    control server.

    Without ``_register_reused_logs`` (the synthetic ``EvalState``
    publication path), the agent has no way to see "yes, these reused
    tasks are present and complete" via the control surface during
    the keep-alive park — only by reading the log files separately.

    This test:

    1. Runs eval_set once with two tasks. Both succeed; logs persist.
    2. Runs eval_set again over the same log_dir with three tasks —
       the original two plus a fresh ``task_c`` — under
       ``keep_alive=True``. ``task_c`` triggers a real ``eval()``
       call (which brings up the control server); ``task_a`` and
       ``task_b`` are reused.
    3. Asserts ``inspect ctl ls`` shows all three evals as
       ``status="completed"`` with matching task names during the
       keep-alive park.

    Aligns with the per-``eval()`` control-server lifecycle: the
    all-reused-only case is out of scope (no ``eval()`` call → no
    server to host the surface).
    """

    @task
    def task_a() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")],
            solver=[generate()],
            name="task_a",
        )

    @task
    def task_b() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")],
            solver=[generate()],
            name="task_b",
        )

    @task
    def task_c() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")],
            solver=[generate()],
            name="task_c",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    # 1. Prime the log_dir with successful logs for task_a + task_b.
    ok_first, logs_first = eval_set(
        tasks=[task_a(), task_b()],
        log_dir=log_dir,
        model="mockllm/model",
        retry_attempts=0,
    )
    assert ok_first, f"first eval_set didn't succeed: logs={logs_first}"
    assert len(logs_first) == 2

    # 2. Re-run with keep-alive — task_a + task_b reused, task_c fresh.
    result_ref: dict[str, object] = {}

    def run_second_eval_set() -> None:
        try:
            ok, _logs = eval_set(
                tasks=[task_a(), task_b(), task_c()],
                log_dir=log_dir,
                model="mockllm/model",
                retry_attempts=0,
                keep_alive=True,
            )
            result_ref["ok"] = ok
        except BaseException as exc:  # noqa: BLE001
            result_ref["error"] = exc

    thread = threading.Thread(target=run_second_eval_set, name="eval_set_reuse")
    thread.start()
    try:
        # Wait until the control server is up AND the eval-set body
        # has registered its reused logs (which happens inside
        # try_eval, AFTER the server binds but BEFORE task_c finishes
        # and the keep-alive park begins). Without this composite
        # predicate we'd race the body and query an empty registry.
        def _ready() -> bool:
            servers = list_discovered_servers()
            if not servers:
                return False
            try:
                transport = httpx.HTTPTransport(uds=str(servers[0].socket_path))
                with httpx.Client(
                    transport=transport,
                    base_url="http://localhost",
                    timeout=1.0,
                ) as client:
                    response = client.get("/evals")
                    response.raise_for_status()
                    return len(response.json()) >= 3
            except (httpx.HTTPError, OSError):
                return False

        ready = _wait_until(_ready)
        assert ready, (
            "control server didn't surface all 3 evals (2 reused + 1 fresh); "
            f"error={result_ref.get('error')}"
        )

        servers = list_discovered_servers()
        assert len(servers) == 1

        # 3. ls should show all three evals as completed.
        transport = httpx.HTTPTransport(uds=str(servers[0].socket_path))
        with httpx.Client(
            transport=transport, base_url="http://localhost", timeout=5.0
        ) as client:
            response = client.get("/evals")
            response.raise_for_status()
            entries = response.json()

        task_names = sorted(e["task"] for e in entries)
        assert task_names == ["task_a", "task_b", "task_c"], (
            f"expected reused + fresh tasks in ls; got tasks={task_names}, "
            f"full response={entries}"
        )
        for entry in entries:
            assert entry["status"] == "completed", (
                f"task {entry['task']!r} should be 'completed' during "
                f"keep-alive park; got status={entry['status']!r}"
            )
            assert entry["completed_at"] is not None
    finally:
        # Tear down the keep-alive process.
        servers = list_discovered_servers()
        if servers:
            try:
                transport = httpx.HTTPTransport(uds=str(servers[0].socket_path))
                with httpx.Client(
                    transport=transport, base_url="http://localhost", timeout=2.0
                ) as client:
                    client.post("/shutdown")
            except Exception:
                pass
        thread.join(timeout=30.0)
        assert not thread.is_alive(), "eval_set thread didn't exit"
        err = result_ref.get("error")
        if err is not None:
            raise err  # type: ignore[misc]


@pytest.mark.slow
def test_ctl_ls_server_survives_eval_set_retries(short_data_dir: Path) -> None:
    """The control server stays bound across an eval-set's retry attempts.

    With the eval-set-scoped (threaded) control server, the discovery
    file present at the start of the first attempt is the SAME file
    visible during a later retry attempt — there's no gap where the
    surface disappears between ``eval()`` calls. Pin that.

    Approach: an eval-set with one fail-once-then-succeed task plus
    one hanging task. The fail-once task forces a retry boundary;
    the hanging task keeps the eval-set alive while we observe the
    discovery file's PATH stays identical across the boundary.
    """
    release = threading.Event()
    fail_counter = {"calls": 0}

    @solver
    def hanging_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            while not release.is_set():
                await anyio.sleep(0.05)
            return state

        return solve

    @solver
    def fail_once_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            fail_counter["calls"] += 1
            if fail_counter["calls"] == 1:
                raise RuntimeError("synthetic first-attempt failure")
            return state

        return solve

    @task
    def task_holder() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")],
            solver=[hanging_solver()],
            name="task_holder",
        )

    @task
    def task_flaky() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")],
            solver=[fail_once_solver()],
            name="task_flaky",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    result_ref: dict[str, object] = {}

    def run_eval_set() -> None:
        try:
            ok, _logs = eval_set(
                tasks=[task_holder(), task_flaky()],
                log_dir=log_dir,
                model="mockllm/model",
                max_tasks=2,
                retry_attempts=2,
                retry_wait=0.05,
                retry_immediate=True,
            )
            result_ref["ok"] = ok
        except BaseException as exc:  # noqa: BLE001
            result_ref["error"] = exc

    thread = threading.Thread(target=run_eval_set, name="eval_set_retry_test")
    thread.start()
    try:
        # Capture the socket path from the first attempt.
        ready = _wait_until(lambda: bool(list_discovered_servers()))
        assert ready, "no control server appeared during first attempt"
        first_socket = list_discovered_servers()[0].socket_path

        # Wait for the flaky task to fail at least once (triggers retry).
        flaky_retried = _wait_until(lambda: fail_counter["calls"] >= 2)
        assert flaky_retried, (
            f"flaky task never retried; calls={fail_counter['calls']}, "
            f"error={result_ref.get('error')}"
        )

        # The control server should STILL be bound at the same socket.
        servers_after = list_discovered_servers()
        assert len(servers_after) == 1, (
            f"control surface vanished during retry; got {len(servers_after)} servers"
        )
        assert servers_after[0].socket_path == first_socket, (
            f"socket path changed across retry "
            f"({first_socket} → {servers_after[0].socket_path}); the "
            f"server was torn down + rebuilt instead of staying bound"
        )

        # And the endpoint still answers — pin the live read path too.
        transport = httpx.HTTPTransport(uds=str(first_socket))
        with httpx.Client(
            transport=transport,
            base_url="http://localhost",
            timeout=5.0,
        ) as client:
            response = client.get("/evals")
            response.raise_for_status()
    finally:
        release.set()
        thread.join(timeout=60)
        assert not thread.is_alive(), "eval_set thread didn't finish after release"
        err = result_ref.get("error")
        if err is not None:
            raise err  # type: ignore[misc]


def test_keep_alive_with_retry_immediate_false_is_rejected(
    short_data_dir: Path,
) -> None:
    """``keep_alive=True`` + ``retry_immediate=False`` should raise PrerequisiteError.

    Pins the architectural decision documented in
    ``design/control-channel.md`` ("Server lifecycle aligned with
    eval()"): the control server lives for one ``eval()`` call.
    ``retry_immediate=False`` (legacy batch-retry mode) makes
    multiple ``eval()`` calls via tenacity, each with its own
    short-lived server — there's no single place to host the
    keep-alive park, so the combination is refused at startup.
    """
    from inspect_ai._util.error import PrerequisiteError

    @task
    def task_quick() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")],
            solver=[generate()],
            name="task_quick",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    with pytest.raises(PrerequisiteError, match="--keep-alive is incompatible"):
        eval_set(
            tasks=[task_quick()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            retry_immediate=False,
            keep_alive=True,
        )
