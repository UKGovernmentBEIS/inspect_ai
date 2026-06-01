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


@pytest.mark.slow
def test_ctl_ls_aggregates_task_retries(short_data_dir: Path) -> None:
    """A flaky task retried by ``task_retry_attempts`` should appear once in ls.

    Today the control endpoint emits one row per ``eval_id``, and
    each retry attempt has a fresh ``eval_id`` (see
    ``TaskLogger.reinit``). Under keep-alive (which skips
    ``unregister_eval`` so completed evals stay visible) every retry
    therefore leaves a stale row behind — a single flaky task with
    two retries shows up as three rows in ``inspect ctl ls``.

    The desired behaviour: group by ``(run_id, task_id)`` so retries
    fold into one row reflecting the latest attempt's progress.
    ``task_id`` is stable across ``reinit`` so it's the right key.

    Approach: a fail-once-then-succeed solver inside an eval-set
    with ``task_retry_attempts >= 1`` and ``keep_alive=True``.
    After the eval body finishes, ``/evals`` should return ONE
    entry for the flaky task — status ``completed``, an
    ``attempts`` count of 2.
    """
    fail_counter = {"calls": 0}

    @solver
    def fail_once_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            fail_counter["calls"] += 1
            if fail_counter["calls"] == 1:
                raise RuntimeError("synthetic first-attempt failure")
            return state

        return solve

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
                tasks=[task_flaky()],
                log_dir=log_dir,
                model="mockllm/model",
                retry_attempts=2,
                retry_immediate=True,
                keep_alive=True,
            )
            result_ref["ok"] = ok
        except BaseException as exc:  # noqa: BLE001
            result_ref["error"] = exc

    thread = threading.Thread(target=run_eval_set, name="eval_set_retry_agg")
    thread.start()
    try:
        # Wait for both attempts to register and the keep-alive park.
        ready = _wait_until(
            lambda: fail_counter["calls"] >= 2 and bool(list_discovered_servers()),
        )
        assert ready, (
            f"didn't reach 'second attempt registered' state. "
            f"calls={fail_counter['calls']}, "
            f"servers={len(list_discovered_servers())}, "
            f"error={result_ref.get('error')}"
        )

        servers = list_discovered_servers()
        assert len(servers) == 1
        transport = httpx.HTTPTransport(uds=str(servers[0].socket_path))

        # Wait for the eval to reach a settled 'completed' state under
        # keep-alive (the retry has fully finished).
        def _settled() -> bool:
            try:
                with httpx.Client(
                    transport=transport, base_url="http://localhost", timeout=1.0
                ) as client:
                    response = client.get("/evals")
                    response.raise_for_status()
                    entries = response.json()
            except (httpx.HTTPError, OSError):
                return False
            # Whatever the aggregation, we want every visible entry to
            # be in a terminal state before asserting.
            return bool(entries) and all(e["status"] == "completed" for e in entries)

        ready = _wait_until(_settled, timeout=30.0)
        assert ready, "eval didn't settle into completed state under keep-alive"

        with httpx.Client(
            transport=transport, base_url="http://localhost", timeout=5.0
        ) as client:
            response = client.get("/evals")
            response.raise_for_status()
            entries = response.json()

        # The core assertion: retries fold into ONE row, not two.
        assert len(entries) == 1, (
            f"expected retries to aggregate into a single entry; got "
            f"{len(entries)} entries: {entries}"
        )
        entry = entries[0]
        assert entry["task"] == "task_flaky"
        assert entry["status"] == "completed"
        # Two attempts were made (the original + 1 retry).
        assert entry.get("attempts") == 2, (
            f"expected attempts=2 (original + 1 retry); got "
            f"attempts={entry.get('attempts')!r}, full entry={entry}"
        )
    finally:
        # Tear down keep-alive.
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
def test_ctl_ls_counts_reused_samples_on_retry(short_data_dir: Path) -> None:
    """Reused successful samples on a retry must count toward ``completed``.

    Bug: when a task is retried by ``task_retry_attempts``, the new
    attempt's ``run_sample`` short-circuits to reuse successful
    samples from the prior log (see the ``sample_source`` early-return
    inside ``run_sample`` in ``_eval/task/run.py``). That fast path
    skips ``task_run_sample`` entirely — which means the
    :class:`EvalState` counter (``record_sample_completed``, called
    only inside ``task_run_sample``) never sees the reused samples.

    Visible symptom: ``inspect ctl ls`` reports e.g. ``4/40`` for a
    task whose final attempt reused 36 prior successes and freshly
    ran 4 — and ``status`` stays ``running`` because
    ``completed + errored < total`` keeps ``completed_at`` ``None``.

    Approach: a 2-sample task with stable sample IDs; a solver that
    fails the second sample on the first attempt only. With
    ``fail_on_error=True`` and ``max_samples=1`` (so sample 1
    finishes and is written to the log before sample 2 errors and
    aborts the task), the retry's sample_source replays sample 1 as
    reused. After the retry succeeds, the aggregated row should
    report ``2/2`` completed and ``status="completed"``.
    """
    counter = {"sample_2_calls": 0}

    @solver
    def flaky_second_sample_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if state.sample_id == 2:
                counter["sample_2_calls"] += 1
                if counter["sample_2_calls"] == 1:
                    raise RuntimeError("synthetic failure on first call to sample 2")
            return state

        return solve

    @task
    def task_partial_fail() -> Task:
        return Task(
            dataset=[
                Sample(id=1, input="x", target="y"),
                Sample(id=2, input="x", target="y"),
            ],
            solver=[flaky_second_sample_solver()],
            name="task_partial_fail",
            fail_on_error=True,
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    result_ref: dict[str, object] = {}

    def run_eval_set() -> None:
        try:
            ok, _logs = eval_set(
                tasks=[task_partial_fail()],
                log_dir=log_dir,
                model="mockllm/model",
                retry_attempts=2,
                retry_immediate=True,
                keep_alive=True,
                max_samples=1,
            )
            result_ref["ok"] = ok
        except BaseException as exc:  # noqa: BLE001
            result_ref["error"] = exc

    thread = threading.Thread(target=run_eval_set, name="eval_set_reuse_count")
    thread.start()
    try:
        servers_ready = _wait_until(
            lambda: bool(list_discovered_servers()) and counter["sample_2_calls"] >= 2,
            timeout=30.0,
        )
        assert servers_ready, (
            f"didn't reach 'retry completed' state. "
            f"sample_2_calls={counter['sample_2_calls']}, "
            f"servers={len(list_discovered_servers())}, "
            f"error={result_ref.get('error')}"
        )

        servers = list_discovered_servers()
        assert len(servers) == 1
        transport = httpx.HTTPTransport(uds=str(servers[0].socket_path))

        # Wait for keep-alive park: every entry should be terminal.
        def _settled() -> bool:
            try:
                with httpx.Client(
                    transport=transport, base_url="http://localhost", timeout=1.0
                ) as client:
                    response = client.get("/evals")
                    response.raise_for_status()
                    entries = response.json()
            except (httpx.HTTPError, OSError):
                return False
            return bool(entries) and all(e["status"] == "completed" for e in entries)

        ready = _wait_until(_settled, timeout=30.0)
        assert ready, "eval didn't settle into completed state under keep-alive"

        with httpx.Client(
            transport=transport, base_url="http://localhost", timeout=5.0
        ) as client:
            response = client.get("/evals")
            response.raise_for_status()
            entries = response.json()

        assert len(entries) == 1, f"expected single aggregated entry, got {entries}"
        entry = entries[0]
        samples = entry["samples"]
        assert samples["total"] == 2, f"expected total=2, got {samples}"
        # Core regression: counter must include the reused sample 1.
        assert samples["completed"] == 2, (
            f"expected completed=2 (sample 1 reused + sample 2 retried), got "
            f"completed={samples['completed']}, full samples={samples}"
        )
        assert entry["status"] == "completed", (
            f"expected status='completed' when all samples done, got "
            f"status={entry['status']!r}; samples={samples}"
        )
        assert entry["completed_at"] is not None
        # Sanity: two attempts were made.
        assert entry["attempts"] == 2
    finally:
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
def test_keep_alive_works_when_all_logs_reused(short_data_dir: Path) -> None:
    """``keep_alive=True`` must park the process even when every task is reused.

    Bug: ``try_eval`` early-returns at "no tasks to run" when every
    requested task has a successful prior log in the log dir (see
    ``_eval/evalset.py``). The early return skips the inner ``eval()``
    call entirely — which is where the keep-alive park lives. With
    no ``eval()`` invocation the process exits immediately, taking
    the control endpoint with it; an agent that re-invoked
    ``inspect eval-set --keep-alive`` to inspect prior results
    finds nothing to attach to.

    Approach: prime the log_dir with successful logs, then re-run
    eval_set over the same tasks with ``keep_alive=True``. The
    second run should park (thread alive, discovery file present,
    ``/evals`` reports the reused tasks) until ``POST /shutdown``
    releases it.
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

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    # 1. Prime the log_dir.
    ok_first, _ = eval_set(
        tasks=[task_a(), task_b()],
        log_dir=log_dir,
        model="mockllm/model",
        retry_attempts=0,
    )
    assert ok_first

    # 2. Re-run with --keep-alive — every task should be reused.
    result_ref: dict[str, object] = {}

    def run_second_eval_set() -> None:
        try:
            ok, _logs = eval_set(
                tasks=[task_a(), task_b()],
                log_dir=log_dir,
                model="mockllm/model",
                retry_attempts=0,
                keep_alive=True,
            )
            result_ref["ok"] = ok
        except BaseException as exc:  # noqa: BLE001
            result_ref["error"] = exc

    thread = threading.Thread(
        target=run_second_eval_set, name="eval_set_all_reused_keep_alive"
    )
    thread.start()
    try:
        # Wait for the control server to come up AND for /evals to
        # report both reused tasks (proves _register_reused_logs has
        # run and the surface is queryable).
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
                    return len(response.json()) >= 2
            except (httpx.HTTPError, OSError):
                return False

        ready = _wait_until(_ready, timeout=30.0)
        assert ready, (
            f"control server didn't surface the reused logs under --keep-alive; "
            f"error={result_ref.get('error')}"
        )

        servers = list_discovered_servers()
        assert len(servers) == 1
        socket_path = servers[0].socket_path

        # The defining assertion: the process must still be parked.
        # Without the fix, the eval_set thread exits immediately after
        # the second invocation returns (since no eval() ran, no
        # keep-alive wait happened).
        time.sleep(0.5)
        assert thread.is_alive(), (
            "eval_set returned without parking — keep-alive didn't take "
            "effect for the all-reused case"
        )
        assert list_discovered_servers(), (
            "discovery file vanished after eval_set returned"
        )

        # Sanity: both reused tasks visible as completed.
        transport = httpx.HTTPTransport(uds=str(socket_path))
        with httpx.Client(
            transport=transport, base_url="http://localhost", timeout=5.0
        ) as client:
            response = client.get("/evals")
            response.raise_for_status()
            entries = response.json()
        assert sorted(e["task"] for e in entries) == ["task_a", "task_b"]
        for entry in entries:
            assert entry["status"] == "completed"

        # POST /shutdown releases the park.
        with httpx.Client(
            transport=transport, base_url="http://localhost", timeout=5.0
        ) as client:
            response = client.post("/shutdown")
            response.raise_for_status()

        thread.join(timeout=30.0)
        assert not thread.is_alive(), (
            "eval_set thread didn't exit within 30s after POST /shutdown"
        )
        assert not list_discovered_servers(), "discovery file lingered after shutdown"
        assert result_ref.get("ok") is True
    finally:
        if thread.is_alive():
            servers = list_discovered_servers()
            if servers:
                try:
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


@pytest.mark.slow
def test_ctl_samples_lists_in_flight_samples(short_data_dir: Path) -> None:
    """`inspect ctl samples` lists an eval's currently-running samples.

    Exercises the whole stack: the ``GET /evals/<id>/samples`` endpoint
    (per-sample summaries from ``active_samples``) and the CLI command
    on top of it — default single-eval resolution, ``--json``, and
    eval-id prefix matching.
    """
    import json as json_lib

    from click.testing import CliRunner

    from inspect_ai._cli.ctl import ctl_command

    release = threading.Event()

    @solver
    def hanging_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            while not release.is_set():
                await anyio.sleep(0.05)
            return state

        return solve

    @task
    def task_multi() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="y") for i in (1, 2, 3)],
            solver=[hanging_solver()],
            name="task_multi",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    result_ref: dict[str, object] = {}

    def run_eval_set() -> None:
        try:
            ok, _logs = eval_set(
                tasks=[task_multi()],
                log_dir=log_dir,
                model="mockllm/model",
                retry_attempts=0,
                max_samples=3,
            )
            result_ref["ok"] = ok
        except BaseException as exc:  # noqa: BLE001
            result_ref["error"] = exc

    thread = threading.Thread(target=run_eval_set, name="eval_set_samples")
    thread.start()
    try:
        ready = _wait_until(
            lambda: (
                len([s for s in active_samples() if s.started is not None]) >= 3
                and bool(list_discovered_servers())
            )
        )
        assert ready, (
            f"didn't reach 3 in-flight samples + a control server. "
            f"active={len(active_samples())}, "
            f"servers={len(list_discovered_servers())}, "
            f"error={result_ref.get('error')}"
        )

        servers = list_discovered_servers()
        assert len(servers) == 1
        transport = httpx.HTTPTransport(uds=str(servers[0].socket_path))
        with httpx.Client(
            transport=transport, base_url="http://localhost", timeout=5.0
        ) as client:
            evals = client.get("/evals").json()
            assert len(evals) == 1
            eval_id = evals[0]["eval_id"]
            task_id = evals[0]["task_id"]
            samples = client.get(f"/evals/{eval_id}/samples").json()

        # Endpoint shape: one entry per in-flight sample.
        assert len(samples) == 3
        assert sorted(s["sample_id"] for s in samples) == [1, 2, 3]
        for s in samples:
            assert s["status"] == "running"
            assert s["epoch"] == 1
            assert s["started_at"] is not None
            assert s["completed_at"] is None
            assert s["total_time"] >= 0
            assert "total_tokens" in s
            assert "message_count" in s

        runner = CliRunner()

        # Default resolution (exactly one task running → no id needed). The
        # output leads with a task-summary header, then the sample rows.
        result = runner.invoke(ctl_command, ["samples"])
        assert result.exit_code == 0, result.output
        assert "task_multi" in result.output  # header names the task
        assert "sample" in result.output and "status" in result.output
        # 3 running sample rows (the header also mentions "running").
        assert result.output.count("running") >= 3

        # --json returns the bare per-sample array (no header).
        result_json = runner.invoke(ctl_command, ["samples", "--json"])
        assert result_json.exit_code == 0, result_json.output
        data = json_lib.loads(result_json.output)
        assert sorted(s["sample_id"] for s in data) == [1, 2, 3]

        # task_id prefix (as shown truncated by `ls`, stable across retries).
        result_prefix = runner.invoke(ctl_command, ["samples", task_id[:12]])
        assert result_prefix.exit_code == 0, result_prefix.output
        assert result_prefix.output.count("running") >= 3

        # Task name (prefix) resolves too, falling back from the id match.
        result_name = runner.invoke(ctl_command, ["samples", "task_mul"])
        assert result_name.exit_code == 0, result_name.output
        assert result_name.output.count("running") >= 3

        # Unknown id is a clean error.
        result_missing = runner.invoke(ctl_command, ["samples", "nope"])
        assert result_missing.exit_code == 1
        assert "No running task matching" in result_missing.output
    finally:
        release.set()
        thread.join(timeout=60)
        assert not thread.is_alive(), "eval_set thread didn't finish after release"
        err = result_ref.get("error")
        if err is not None:
            raise err  # type: ignore[misc]


@pytest.mark.slow
@pytest.mark.parametrize("log_format", ["eval", "json"])
def test_ctl_samples_includes_completed_samples(
    short_data_dir: Path, log_format: str
) -> None:
    """`inspect ctl samples` lists completed-so-far samples, not just running.

    Pins the "all samples" contract: completed samples come from the
    recorder's in-memory record (gap-free) while running ones come from
    ``active_samples``, merged into one listing. A solver completes the
    even-id samples immediately and hangs the odd-id ones; once two have
    completed and two are still running, the endpoint must report all
    four with the right statuses. Parametrized over the log format so the
    per-recorder ``sample_summaries`` accessor is covered for both.
    """
    release = threading.Event()

    @solver
    def gated_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            # Odd-id samples hang until released; even-id complete now.
            if int(state.sample_id) % 2 == 1:
                while not release.is_set():
                    await anyio.sleep(0.05)
            return state

        return solve

    @task
    def task_gated() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="y") for i in (1, 2, 3, 4)],
            solver=[gated_solver()],
            name="task_gated",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    result_ref: dict[str, object] = {}

    def run_eval_set() -> None:
        try:
            ok, _logs = eval_set(
                tasks=[task_gated()],
                log_dir=log_dir,
                model="mockllm/model",
                retry_attempts=0,
                max_samples=4,
                log_format=log_format,  # type: ignore[arg-type]
            )
            result_ref["ok"] = ok
        except BaseException as exc:  # noqa: BLE001
            result_ref["error"] = exc

    thread = threading.Thread(target=run_eval_set, name="eval_set_samples_mixed")
    thread.start()

    def _samples_via_endpoint() -> list[dict[str, object]]:
        servers = list_discovered_servers()
        if not servers:
            return []
        try:
            transport = httpx.HTTPTransport(uds=str(servers[0].socket_path))
            with httpx.Client(
                transport=transport, base_url="http://localhost", timeout=2.0
            ) as client:
                evals = client.get("/evals").json()
                if not evals:
                    return []
                eval_id = evals[0]["eval_id"]
                return client.get(f"/evals/{eval_id}/samples").json()
        except (httpx.HTTPError, OSError):
            return []

    try:
        # Wait until 2 samples have completed (even ids) AND 2 are still
        # running (odd ids, hanging) — surfaced together by the endpoint.
        def _two_done_two_running() -> bool:
            rows = _samples_via_endpoint()
            done = [r for r in rows if r["status"] == "completed"]
            running = [r for r in rows if r["status"] == "running"]
            return len(done) == 2 and len(running) == 2

        ready = _wait_until(_two_done_two_running, timeout=30.0)
        assert ready, (
            f"didn't reach 2-completed + 2-running. "
            f"rows={_samples_via_endpoint()}, error={result_ref.get('error')}"
        )

        rows = _samples_via_endpoint()
        assert sorted(r["sample_id"] for r in rows) == [1, 2, 3, 4]
        by_id = {r["sample_id"]: r for r in rows}
        # Even ids completed (with a completed_at); odd ids still running.
        for sid in (2, 4):
            assert by_id[sid]["status"] == "completed"
            assert by_id[sid]["completed_at"] is not None
        for sid in (1, 3):
            assert by_id[sid]["status"] == "running"
            assert by_id[sid]["completed_at"] is None
    finally:
        release.set()
        thread.join(timeout=60)
        assert not thread.is_alive(), "eval_set thread didn't finish after release"
        err = result_ref.get("error")
        if err is not None:
            raise err  # type: ignore[misc]


@pytest.mark.slow
def test_ctl_samples_recorder_ahead_of_disk(short_data_dir: Path) -> None:
    """Completed samples show up before they're flushed to the on-disk log.

    Pins the gap-free property of reading completed summaries from the
    recorder's in-memory state rather than the log file. With 9 samples,
    ``.eval`` flush_buffer is 3; completing only 2 (the rest hang) leaves
    those 2 buffered in the recorder (``_samples``) and **not yet written
    to disk**. The endpoint must still list them, while a direct read of
    the on-disk log does not yet see them.
    """
    release = threading.Event()
    completed_ids = (1, 2)

    @solver
    def gated_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if int(state.sample_id) not in completed_ids:
                while not release.is_set():
                    await anyio.sleep(0.05)
            return state

        return solve

    @task
    def task_nine() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="y") for i in range(1, 10)],
            solver=[gated_solver()],
            name="task_nine",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    result_ref: dict[str, object] = {}

    def run_eval_set() -> None:
        try:
            ok, _logs = eval_set(
                tasks=[task_nine()],
                log_dir=log_dir,
                model="mockllm/model",
                retry_attempts=0,
                max_samples=9,  # all start; flush_buffer stays at the default (3)
            )
            result_ref["ok"] = ok
        except BaseException as exc:  # noqa: BLE001
            result_ref["error"] = exc

    thread = threading.Thread(target=run_eval_set, name="eval_set_ahead_of_disk")
    thread.start()

    def _endpoint_samples() -> list[dict[str, object]]:
        servers = list_discovered_servers()
        if not servers:
            return []
        try:
            transport = httpx.HTTPTransport(uds=str(servers[0].socket_path))
            with httpx.Client(
                transport=transport, base_url="http://localhost", timeout=2.0
            ) as client:
                evals = client.get("/evals").json()
                if not evals:
                    return []
                return client.get(f"/evals/{evals[0]['eval_id']}/samples").json()
        except (httpx.HTTPError, OSError):
            return []

    try:
        # Stable state: exactly 2 completed (held below flush_buffer by the
        # 7 hanging samples), so no flush ever fires.
        def _two_done_seven_running() -> bool:
            rows = _endpoint_samples()
            done = sum(1 for r in rows if r["status"] == "completed")
            running = sum(1 for r in rows if r["status"] == "running")
            return done == 2 and running == 7

        ready = _wait_until(_two_done_seven_running, timeout=30.0)
        assert ready, (
            f"didn't reach 2-completed + 7-running. rows={_endpoint_samples()}, "
            f"error={result_ref.get('error')}"
        )

        rows = _endpoint_samples()
        assert sorted(r["sample_id"] for r in rows) == list(range(1, 10))
        endpoint_completed = {
            r["sample_id"] for r in rows if r["status"] == "completed"
        }
        assert endpoint_completed == set(completed_ids)

        # The on-disk log has NOT seen these completed samples yet (no flush
        # has fired) — proving the endpoint served them from the recorder's
        # in-memory state, not the file.
        from inspect_ai._control.eval_state import get_eval_states
        from inspect_ai.log._file import read_eval_log_sample_summaries_async

        location = next(s.log_location for s in get_eval_states() if s.log_location)

        async def _read_disk() -> list:
            try:
                return await read_eval_log_sample_summaries_async(location)
            except Exception:
                return []

        on_disk = anyio.run(_read_disk)
        on_disk_completed = {s.id for s in on_disk if s.completed}
        assert on_disk_completed < endpoint_completed, (
            f"expected the recorder to be ahead of disk; on_disk={on_disk_completed}, "
            f"endpoint={endpoint_completed}"
        )
    finally:
        release.set()
        thread.join(timeout=60)
        assert not thread.is_alive(), "eval_set thread didn't finish after release"
        err = result_ref.get("error")
        if err is not None:
            raise err  # type: ignore[misc]


@pytest.mark.slow
def test_ctl_samples_task_id_stable_across_retry(short_data_dir: Path) -> None:
    """`inspect ctl samples <task_id>` keeps resolving after an error + retry.

    A task's per-attempt ``eval_id`` is regenerated on retry, but its
    ``task_id`` is stable — which is why `ls` shows ``task_id`` and
    `samples` takes it. Here the task fails on its first attempt then
    hangs on the retry (so it stays registered and running). After the
    retry — when the eval_id has changed — `samples <task_id>` still
    resolves and lists the running sample.
    """
    release = threading.Event()
    fail_counter = {"calls": 0}

    @solver
    def fail_then_hang_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            fail_counter["calls"] += 1
            if fail_counter["calls"] == 1:
                raise RuntimeError("synthetic first-attempt failure")
            while not release.is_set():
                await anyio.sleep(0.05)
            return state

        return solve

    @task
    def task_flaky() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")],
            solver=[fail_then_hang_solver()],
            name="task_flaky",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    result_ref: dict[str, object] = {}

    def run_eval_set() -> None:
        try:
            ok, _logs = eval_set(
                tasks=[task_flaky()],
                log_dir=log_dir,
                model="mockllm/model",
                retry_attempts=2,
                retry_immediate=True,
            )
            result_ref["ok"] = ok
        except BaseException as exc:  # noqa: BLE001
            result_ref["error"] = exc

    thread = threading.Thread(target=run_eval_set, name="eval_set_retry_stable")
    thread.start()

    def _flaky_summary() -> dict[str, object] | None:
        servers = list_discovered_servers()
        if not servers:
            return None
        try:
            transport = httpx.HTTPTransport(uds=str(servers[0].socket_path))
            with httpx.Client(
                transport=transport, base_url="http://localhost", timeout=2.0
            ) as client:
                evals = client.get("/evals").json()
        except (httpx.HTTPError, OSError):
            return None
        return next((e for e in evals if e["task"] == "task_flaky"), None)

    try:
        # Wait until the retry (attempt 2) is the registered, running eval.
        def _retry_running() -> bool:
            entry = _flaky_summary()
            return (
                fail_counter["calls"] >= 2
                and entry is not None
                and entry["status"] == "running"
            )

        ready = _wait_until(_retry_running, timeout=30.0)
        assert ready, (
            f"flaky task's retry isn't running. calls={fail_counter['calls']}, "
            f"entry={_flaky_summary()}, error={result_ref.get('error')}"
        )

        entry = _flaky_summary()
        assert entry is not None
        task_id = entry["task_id"]
        assert task_id, "expected a stable task_id on the entry"

        # The stable task_id resolves via the CLI even though the eval_id
        # is now the retry's (different from the failed first attempt).
        import json as json_lib

        from click.testing import CliRunner

        from inspect_ai._cli.ctl import ctl_command

        runner = CliRunner()
        result = runner.invoke(ctl_command, ["samples", "--json", str(task_id)[:12]])
        assert result.exit_code == 0, result.output
        rows = json_lib.loads(result.output)
        assert len(rows) == 1
        assert rows[0]["status"] == "running"
    finally:
        release.set()
        thread.join(timeout=60)
        assert not thread.is_alive(), "eval_set thread didn't finish after release"
        err = result_ref.get("error")
        if err is not None:
            raise err  # type: ignore[misc]


@pytest.mark.slow
def test_ctl_samples_shows_score_for_single_scorer(short_data_dir: Path) -> None:
    """A completed sample's score is surfaced (endpoint field + CLI column).

    A single-scorer task where sample 1 completes (and is scored) while
    sample 2 hangs. The completed sample's summary carries ``scores``, and
    the human table shows a ``score`` column with the value.
    """
    from inspect_ai.scorer import Score, Target, accuracy, scorer

    release = threading.Event()

    @scorer(metrics=[accuracy()])
    def const_scorer():  # type: ignore[no-untyped-def]
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value="C")

        return score

    @solver
    def gated_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if int(state.sample_id) == 2:
                while not release.is_set():
                    await anyio.sleep(0.05)
            return state

        return solve

    @task
    def task_scored() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="C") for i in (1, 2)],
            solver=[gated_solver()],
            scorer=const_scorer(),
            name="task_scored",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    result_ref: dict[str, object] = {}

    def run_eval_set() -> None:
        try:
            ok, _logs = eval_set(
                tasks=[task_scored()],
                log_dir=log_dir,
                model="mockllm/model",
                retry_attempts=0,
                max_samples=2,
            )
            result_ref["ok"] = ok
        except BaseException as exc:  # noqa: BLE001
            result_ref["error"] = exc

    thread = threading.Thread(target=run_eval_set, name="eval_set_scored")
    thread.start()

    def _endpoint_samples() -> list[dict[str, object]]:
        servers = list_discovered_servers()
        if not servers:
            return []
        try:
            transport = httpx.HTTPTransport(uds=str(servers[0].socket_path))
            with httpx.Client(
                transport=transport, base_url="http://localhost", timeout=2.0
            ) as client:
                evals = client.get("/evals").json()
                if not evals:
                    return []
                return client.get(f"/evals/{evals[0]['eval_id']}/samples").json()
        except (httpx.HTTPError, OSError):
            return []

    try:
        # Wait until sample 1 has completed (and been scored) while 2 hangs.
        def _one_scored() -> bool:
            rows = _endpoint_samples()
            done = [r for r in rows if r["status"] == "completed"]
            return len(done) == 1 and bool(done[0].get("scores"))

        ready = _wait_until(_one_scored, timeout=30.0)
        assert ready, (
            f"no scored completed sample. rows={_endpoint_samples()}, "
            f"error={result_ref.get('error')}"
        )

        rows = _endpoint_samples()
        completed = next(r for r in rows if r["status"] == "completed")
        scores = completed["scores"]
        assert len(scores) == 1, f"expected a single scorer, got {scores}"
        assert next(iter(scores.values())) == "C"

        # The CLI renders a score column with the value.
        from click.testing import CliRunner

        from inspect_ai._cli.ctl import ctl_command

        result = CliRunner().invoke(ctl_command, ["samples", "task_scored"])
        assert result.exit_code == 0, result.output
        header = result.output.splitlines()[2]  # task header, blank, table header
        assert "score" in header
        assert "C" in result.output
    finally:
        release.set()
        thread.join(timeout=60)
        assert not thread.is_alive(), "eval_set thread didn't finish after release"
        err = result_ref.get("error")
        if err is not None:
            raise err  # type: ignore[misc]


@pytest.mark.slow
def test_ctl_samples_includes_pending_samples(short_data_dir: Path) -> None:
    """Pending (not-yet-started) samples are listed alongside running ones.

    With ``max_samples=1`` and a hanging solver, sample 1 runs while
    samples 2 and 3 stay queued. They aren't in any live source, so they
    come from the eval's registered planned ids — the endpoint reports
    them as ``pending``.
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
    def task_many() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="y") for i in (1, 2, 3)],
            solver=[hanging_solver()],
            name="task_many",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    result_ref: dict[str, object] = {}

    def run_eval_set() -> None:
        try:
            ok, _logs = eval_set(
                tasks=[task_many()],
                log_dir=log_dir,
                model="mockllm/model",
                retry_attempts=0,
                max_samples=1,  # one runs; the rest stay pending
            )
            result_ref["ok"] = ok
        except BaseException as exc:  # noqa: BLE001
            result_ref["error"] = exc

    thread = threading.Thread(target=run_eval_set, name="eval_set_pending")
    thread.start()

    def _endpoint_samples() -> list[dict[str, object]]:
        servers = list_discovered_servers()
        if not servers:
            return []
        try:
            transport = httpx.HTTPTransport(uds=str(servers[0].socket_path))
            with httpx.Client(
                transport=transport, base_url="http://localhost", timeout=2.0
            ) as client:
                evals = client.get("/evals").json()
                if not evals:
                    return []
                return client.get(f"/evals/{evals[0]['eval_id']}/samples").json()
        except (httpx.HTTPError, OSError):
            return []

    try:

        def _one_running_two_pending() -> bool:
            rows = _endpoint_samples()
            running = sum(1 for r in rows if r["status"] == "running")
            pending = sum(1 for r in rows if r["status"] == "pending")
            return running == 1 and pending == 2

        ready = _wait_until(_one_running_two_pending, timeout=30.0)
        assert ready, (
            f"didn't reach 1-running + 2-pending. rows={_endpoint_samples()}, "
            f"error={result_ref.get('error')}"
        )

        rows = _endpoint_samples()
        assert sorted(r["sample_id"] for r in rows) == [1, 2, 3]
        for r in rows:
            if r["status"] == "pending":
                assert r["started_at"] is None
                assert r["total_time"] is None

        # The CLI lists the pending rows too.
        from click.testing import CliRunner

        from inspect_ai._cli.ctl import ctl_command

        result = CliRunner().invoke(ctl_command, ["samples", "task_many"])
        assert result.exit_code == 0, result.output
        assert result.output.count("pending") == 2
    finally:
        release.set()
        thread.join(timeout=60)
        assert not thread.is_alive(), "eval_set thread didn't finish after release"
        err = result_ref.get("error")
        if err is not None:
            raise err  # type: ignore[misc]
