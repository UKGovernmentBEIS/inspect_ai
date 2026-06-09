"""Integration tests: control-channel state vs `eval_set` with real runs.

Each test runs a real ``eval_set`` and observes the control-channel state
(``current_eval_summaries`` / ``current_sample_summaries`` /
``sample_error_detail`` — the same dicts the ``GET /evals*`` endpoints
serialize) from *inside* the eval's own anyio loop via the ``control_probe``
helpers. No background threads, no HTTP round-trip, no hang-forever solvers:

- terminal state is snapshotted at ``on_run_end`` (a task's own run-end fires
  when it finishes — no sibling "hang" task needed to hold the surface open);
- mid-run state ("two samples in flight", "one done one running") is captured
  via a self-releasing :func:`~tests._control.control_probe.gate` the instant a
  synchronous readiness predicate holds, then the gate releases so the eval
  finishes. A never-satisfied predicate times out rather than hanging.

CLI rendering is exercised by feeding captured data straight to the ``ctl``
render functions (which emit via ``click.echo``) and capturing stdout. The
HTTP-specific concerns (query-param sample-id encoding, the keep-alive shutdown
wait) live in ``test_server.py``.

See ``tests/_control/control_probe.py`` for the observation primitives.
"""

import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import click
import pytest

from _control.control_probe import capturing, gate, park_now, probe, render
from inspect_ai import Task, task
from inspect_ai._cli.ctl import (
    _print_errors_table,
    _print_sample_detail,
    _print_samples_table,
    _resolve_target_eval,
)
from inspect_ai._control.discovery import list_discovered_servers
from inspect_ai._control.eval_state import get_eval_states
from inspect_ai._control.events import decode_cursor, sample_events
from inspect_ai._control.state import (
    current_eval_summaries,
    current_sample_summaries,
    sample_error_detail,
)
from inspect_ai._eval.evalset import eval_set
from inspect_ai.dataset import Sample
from inspect_ai.log._samples import active_samples
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver


@pytest.fixture(autouse=True)
def _isolate_active_model() -> Iterator[None]:
    """Keep ``eval_set``'s active-model contextvar from leaking across tests.

    ``eval`` sets the process ``active_model`` contextvar. These tests run
    ``eval_set`` *synchronously* in the test's own context (not a background
    thread), so without isolation that set persists after the call and leaks
    ``mockllm/model`` into later tests — e.g. one resolving a bare ``inspect``
    model, which then resolves to the leaked active model instead of
    ``INSPECT_EVAL_MODEL``. Restore the contextvar after each test.
    """
    from inspect_ai.model._model import active_model_context_var

    token = active_model_context_var.set(active_model_context_var.get(None))
    try:
        yield
    finally:
        active_model_context_var.reset(token)


@pytest.fixture
def short_data_dir(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Short data dir under /tmp so AF_UNIX paths fit in 104 chars.

    macOS pytest tmp_path lives under ``/private/var/folders/...`` which blows
    past the AF_UNIX limit. The control server still binds a socket during the
    run (even though we observe in-loop, not over it), so the discovery dir
    must stay short. Patches both control and ACP discovery modules so neither
    subsystem writes outside the test's sandbox.
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


# --- ls / GET /evals: per-eval listing -------------------------------------


def test_ctl_ls_lists_each_eval_in_an_eval_set(short_data_dir: Path) -> None:
    """An eval-set with N concurrent tasks produces N entries (one per eval_id).

    The control endpoint groups by ``(run_id, task_id)`` but emits one row per
    running eval — keyed by ``eval_id``, each carrying its own task, sample
    counts, model usage, started_at. Pinned here with both tasks held in flight.
    """

    @task
    def task_alpha() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")], solver=[gate()], name="task_alpha"
        )

    @task
    def task_beta() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")], solver=[gate()], name="task_beta"
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    def ready() -> bool:
        evals = current_eval_summaries(0.0)
        return len(evals) == 2 and all(e["samples"]["in_flight"] == 1 for e in evals)

    async def capture() -> list[dict]:
        return current_eval_summaries(0.0)

    with probe(ready, capture) as p:
        eval_set(
            tasks=[task_alpha(), task_beta()],
            log_dir=log_dir,
            model="mockllm/model",
            max_tasks=2,
            retry_attempts=0,
        )

    evals = p.result
    assert evals is not None, "both tasks never reached 'in flight' together"
    assert len(evals) == 2, evals
    assert sorted(e["task"] for e in evals) == ["task_alpha", "task_beta"]
    assert len({e["eval_id"] for e in evals}) == 2, "expected distinct eval_ids"
    assert len({e["run_id"] for e in evals}) == 1, "expected single shared run_id"
    for entry in evals:
        samples = entry["samples"]
        assert samples["total"] == 1
        assert samples["in_flight"] == 1
        assert samples["completed"] == 0
        assert samples["errored"] == 0
        assert samples["queued"] == 0
        assert entry["status"] == "running"
        assert entry["completed_at"] is None
        # log_location points at this eval's log file, so an agent monitoring a
        # run it didn't launch can find where results are written — as a plain
        # local path (no `file://` prefix), directly usable.
        assert not entry["log_location"].startswith("file://")
        assert entry["log_location"].startswith(log_dir)
        assert entry["log_location"].endswith(".eval")


def test_ctl_ls_survives_fast_task_finishing_first(short_data_dir: Path) -> None:
    """A fast-finishing task doesn't tear down the control surface for its sibling.

    The control_server lifecycle is per-``eval()``-call, NOT per-task; the
    discovery files are PID-keyed, so a per-task lifecycle would collide and
    corrupt the surface when one task finishes. After task_fast completes but
    while task_slow runs, the discovery file must still be present and the
    surface still reports the slow eval.
    """

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
            dataset=[Sample(input="x", target="y")], solver=[gate()], name="task_slow"
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    def ready() -> bool:
        evals = current_eval_summaries(0.0)
        fast = next((e for e in evals if e["task"] == "task_fast"), None)
        slow = next((e for e in evals if e["task"] == "task_slow"), None)
        return (
            bool(list_discovered_servers())
            and fast is not None
            and fast["status"] == "completed"
            and slow is not None
            and slow["samples"]["in_flight"] == 1
        )

    async def capture() -> dict:
        return {
            "servers": len(list_discovered_servers()),
            "tasks": {e["task"] for e in current_eval_summaries(0.0)},
        }

    with probe(ready, capture) as p:
        eval_set(
            tasks=[task_fast(), task_slow()],
            log_dir=log_dir,
            model="mockllm/model",
            max_tasks=2,
            retry_attempts=0,
        )

    assert p.result is not None, "never reached 'fast done, slow running'"
    assert p.result["servers"] == 1, "discovery file vanished after task_fast finished"
    assert "task_slow" in p.result["tasks"]


def test_ctl_ls_shows_reused_logs_as_completed(short_data_dir: Path) -> None:
    """Pre-existing successful eval logs appear in ``ls`` as completed.

    Re-invoking ``eval_set`` over a log_dir with successful logs for some tasks
    reuses those logs (they don't re-run); ``_register_reused_logs`` publishes
    synthetic ``EvalState``s so the reused tasks are still visible on the
    control surface alongside the fresh one.
    """

    @task
    def task_a() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")], solver=[generate()], name="task_a"
        )

    @task
    def task_b() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")], solver=[generate()], name="task_b"
        )

    @task
    def task_c() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")], solver=[generate()], name="task_c"
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    # Prime the log_dir with successful logs for task_a + task_b.
    ok_first, logs_first = eval_set(
        tasks=[task_a(), task_b()],
        log_dir=log_dir,
        model="mockllm/model",
        retry_attempts=0,
    )
    assert ok_first, f"first eval_set didn't succeed: {logs_first}"

    # Re-run: task_a + task_b reused, task_c fresh (its run brings up the
    # server and fires on_run_end, at which point all three are registered).
    with capturing() as cap:
        ok, _ = eval_set(
            tasks=[task_a(), task_b(), task_c()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
        )
    assert ok

    assert sorted(e["task"] for e in cap.evals) == ["task_a", "task_b", "task_c"], (
        f"expected reused + fresh tasks; got {[e['task'] for e in cap.evals]}"
    )
    for name in ("task_a", "task_b", "task_c"):
        entry = cap.eval(name)
        assert entry is not None
        assert entry["status"] == "completed", f"{name}: {entry['status']}"
        assert entry["completed_at"] is not None


def test_ctl_ls_server_survives_eval_set_retries(short_data_dir: Path) -> None:
    """The control server stays bound (same socket) across an eval-set retry.

    With the eval-set-scoped server, ``retry_immediate`` retries happen within
    one ``eval()`` call, so the discovery socket present on the first attempt
    is the SAME one visible after a retry boundary — never torn down and
    rebuilt. A fail-once task forces the boundary; a held task keeps the
    eval-set alive while we re-read the socket path.
    """
    fail = {"calls": 0}
    first: dict[str, object] = {}

    @solver
    def fail_once_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            fail["calls"] += 1
            if fail["calls"] == 1:
                raise RuntimeError("synthetic first-attempt failure")
            return state

        return solve

    @task
    def task_holder() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")], solver=[gate()], name="task_holder"
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

    def ready() -> bool:
        servers = list_discovered_servers()
        # Record the socket the first time one is seen (before the retry).
        if servers and "path" not in first:
            first["path"] = servers[0].socket_path
        evals = current_eval_summaries(0.0)
        holder = next((e for e in evals if e["task"] == "task_holder"), None)
        return (
            fail["calls"] >= 2
            and bool(servers)
            and holder is not None
            and holder["samples"]["in_flight"] == 1
        )

    async def capture() -> dict:
        return {
            "first": first.get("path"),
            "now": list_discovered_servers()[0].socket_path,
        }

    with probe(ready, capture) as p:
        eval_set(
            tasks=[task_holder(), task_flaky()],
            log_dir=log_dir,
            model="mockllm/model",
            max_tasks=2,
            retry_attempts=2,
            retry_wait=0.05,
            retry_immediate=True,
        )

    assert p.result is not None, "flaky task never retried while holder ran"
    assert p.result["first"] is not None, "no discovery socket seen at run start"
    assert p.result["now"] == p.result["first"], (
        "socket path changed across retry — server was torn down + rebuilt"
    )


def test_ctl_ls_aggregates_task_retries(short_data_dir: Path) -> None:
    """A flaky task retried by ``retry_attempts`` appears once in ls (folded).

    Each retry attempt mints a fresh ``eval_id`` but ``task_id`` is stable, so
    the endpoint folds by ``(run_id, task_id)`` into one row reporting the
    latest attempt and an ``attempts`` count.
    """
    fail = {"calls": 0}

    @solver
    def fail_once_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            fail["calls"] += 1
            if fail["calls"] == 1:
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

    with capturing() as cap:
        eval_set(
            tasks=[task_flaky()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=2,
            retry_immediate=True,
        )

    flaky_entries = [e for e in cap.evals if e["task"] == "task_flaky"]
    assert len(flaky_entries) == 1, f"retries should fold into one row: {cap.evals}"
    entry = flaky_entries[0]
    assert entry["status"] == "completed"
    assert entry["attempts"] == 2, f"expected attempts=2; got {entry}"


def test_ctl_ls_counts_reused_samples_on_retry(short_data_dir: Path) -> None:
    """Reused successful samples on a retry count toward ``completed``.

    On a task retry the new attempt's ``run_sample`` short-circuits reused
    successes from the prior log without entering ``task_run_sample`` — the
    fast path that used to skip the ``EvalState`` counter. After the retry, the
    folded row must report all samples completed, not just the freshly-run one.
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

    with capturing() as cap:
        eval_set(
            tasks=[task_partial_fail()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=2,
            retry_immediate=True,
            max_samples=1,
        )

    entry = cap.eval("task_partial_fail")
    assert entry is not None
    samples = entry["samples"]
    assert samples["total"] == 2
    assert samples["completed"] == 2, (
        f"reused sample 1 must count toward completed; got {samples}"
    )
    assert entry["status"] == "completed"
    assert entry["completed_at"] is not None
    assert entry["attempts"] == 2


def test_ctl_reused_log_eval_reports_usage(short_data_dir: Path) -> None:
    """A task reused from a prior log reports its logged usage, not zeros.

    Run 1 produces a successful log with token + message usage. Run 2 reuses
    it (the task isn't re-run) while a fresh sibling brings up the server. The
    reused task's synthetic ``EvalState`` must carry the usage pulled from the
    prior log's stats / summaries.
    """
    calls = {"gen": 0}

    @solver
    def gen() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            calls["gen"] += 1
            return await generate(state)

        return solve

    @task
    def reused_work() -> Task:
        return Task(
            dataset=[Sample(id=1, input="hi", target="ok")],
            solver=[gen()],
            name="reused_work",
        )

    @task
    def fresh() -> Task:
        return Task(
            dataset=[Sample(id=1, input="hi", target="ok")],
            solver=[generate()],
            name="fresh",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    ok1, _ = eval_set(
        tasks=[reused_work()], log_dir=log_dir, model="mockllm/model", retry_attempts=0
    )
    assert ok1
    assert calls["gen"] == 1

    with capturing() as cap:
        eval_set(
            tasks=[reused_work(), fresh()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            max_tasks=2,
        )

    assert calls["gen"] == 1, "reused_work should not have re-run"
    entry = cap.eval("reused_work")
    assert entry is not None
    assert entry["total_tokens"] > 0, entry
    assert entry["total_messages"] > 0, entry


# --- keep-alive park -------------------------------------------------------


def test_keep_alive_park_entered_with_completed_state(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ctl_server="keep-alive"`` enters the park, eval reported completed.

    The park itself (block until ``POST /release``) is unit-tested in
    ``test_server.py`` via ``wait_for_shutdown_async``; here we pin the
    eval_set integration point — the park is reached, and at that moment the
    control surface shows the eval ``completed`` with a ``completed_at`` so an
    agent can tell it's safe to stop polling. A spy stands in for the (blocking)
    park so the test doesn't have to release it.
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

    captured: dict[str, list[dict]] = {}

    async def spy(eval_set_id: str) -> None:
        captured["evals"] = current_eval_summaries(0.0)

    monkeypatch.setattr("inspect_ai._eval.evalset._keep_alive_park", spy)

    ok, _ = eval_set(
        tasks=[task_quick()],
        log_dir=log_dir,
        model="mockllm/model",
        retry_attempts=0,
        ctl_server="keep-alive",
    )
    assert ok

    assert "evals" in captured, "keep-alive park was never entered"
    entries = captured["evals"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["status"] == "completed"
    assert entry["completed_at"] is not None
    assert entry["completed_at"] >= entry["started_at"]


def test_keep_alive_works_when_all_logs_reused(
    short_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ctl_server="keep-alive"`` parks even when every task is reused.

    ``try_eval`` used to early-return at "no tasks to run" when every requested
    task had a prior success — skipping the inner ``eval()`` call where the
    keep-alive park lives, so the process exited immediately. The fix keeps the
    park reachable; we assert the park is entered and the reused tasks are
    visible there.
    """

    @task
    def task_a() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")], solver=[generate()], name="task_a"
        )

    @task
    def task_b() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")], solver=[generate()], name="task_b"
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    ok_first, _ = eval_set(
        tasks=[task_a(), task_b()],
        log_dir=log_dir,
        model="mockllm/model",
        retry_attempts=0,
    )
    assert ok_first

    captured: dict[str, list[dict]] = {}

    async def spy(eval_set_id: str) -> None:
        captured["evals"] = current_eval_summaries(0.0)

    monkeypatch.setattr("inspect_ai._eval.evalset._keep_alive_park", spy)

    ok, _ = eval_set(
        tasks=[task_a(), task_b()],
        log_dir=log_dir,
        model="mockllm/model",
        retry_attempts=0,
        ctl_server="keep-alive",
    )
    assert ok

    assert "evals" in captured, "all-reused keep-alive never entered the park"
    entries = captured["evals"]
    assert sorted(e["task"] for e in entries) == ["task_a", "task_b"]
    for entry in entries:
        assert entry["status"] == "completed"


def test_keep_alive_with_retry_immediate_false_is_rejected(
    short_data_dir: Path,
) -> None:
    """``ctl_server="keep-alive"`` + ``retry_immediate=False`` raises PrerequisiteError.

    The control server lives for one ``eval()`` call; ``retry_immediate=False``
    makes multiple short-lived ``eval()`` calls via tenacity, so there's no
    single place to host the keep-alive park — refused at startup.
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

    with pytest.raises(
        PrerequisiteError, match="--ctl-server=keep-alive is incompatible"
    ):
        eval_set(
            tasks=[task_quick()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            retry_immediate=False,
            ctl_server="keep-alive",
        )


# --- samples / GET /evals/<id>/samples -------------------------------------


def test_ctl_samples_lists_in_flight_samples(short_data_dir: Path) -> None:
    """The per-sample listing reports an eval's running samples.

    Also covers the CLI target resolution (id-prefix / task-name / error).
    """

    @task
    def task_multi() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="y") for i in (1, 2, 3)],
            solver=[gate()],
            name="task_multi",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    def ready() -> bool:
        evals = current_eval_summaries(0.0)
        return bool(evals) and evals[0]["samples"]["in_flight"] == 3

    async def capture() -> dict:
        entry = current_eval_summaries(0.0)[0]
        return {
            "eval": entry,
            "samples": await current_sample_summaries(entry["eval_id"]),
        }

    with probe(ready, capture) as p:
        eval_set(
            tasks=[task_multi()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            max_samples=3,
        )

    assert p.result is not None, "three samples never reached 'in flight'"
    entry = p.result["eval"]
    samples = p.result["samples"]
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
        # liveness signals for stall detection
        assert isinstance(s["last_activity_at"], float)
        assert s["last_activity_at"] >= s["started_at"]
        assert isinstance(s["events"], int)

    # CLI target resolution (pure over the summaries the endpoint returns).
    summaries = [entry]
    assert _resolve_target_eval(summaries, None) is entry  # sole task
    assert _resolve_target_eval(summaries, entry["task_id"][:12]) is entry  # id prefix
    assert _resolve_target_eval(summaries, "task_mul") is entry  # task-name prefix
    with pytest.raises(click.exceptions.Exit):
        _resolve_target_eval(summaries, "nope")  # unknown -> clean error

    out = render(_print_samples_table, samples)
    assert out.count("running") >= 3
    assert "idle" in out.splitlines()[0]  # idle column shown for running samples


@pytest.mark.parametrize("log_format", ["eval", "json"])
def test_ctl_samples_includes_completed_samples(
    short_data_dir: Path, log_format: str
) -> None:
    """The listing merges completed-so-far samples with running ones.

    Completed samples come from the recorder's in-memory record; running ones
    from ``active_samples``. Even-id samples complete immediately; odd-id ones
    are held. Parametrized over the log format so both recorder
    ``sample_summaries`` accessors are covered.
    """

    @task
    def task_gated() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="y") for i in (1, 2, 3, 4)],
            solver=[gate()],
            name="task_gated",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    def ready() -> bool:
        evals = current_eval_summaries(0.0)
        return (
            bool(evals)
            and evals[0]["samples"]["completed"] == 2
            and evals[0]["samples"]["in_flight"] == 2
        )

    async def capture() -> list[dict]:
        entry = current_eval_summaries(0.0)[0]
        return await current_sample_summaries(entry["eval_id"])

    with probe(ready, capture, park=lambda sid: int(sid) % 2 == 1) as p:
        eval_set(
            tasks=[task_gated()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            max_samples=4,
            log_format=log_format,  # type: ignore[arg-type]
        )

    rows = p.result
    assert rows is not None, "never reached 2-completed + 2-running"
    assert sorted(r["sample_id"] for r in rows) == [1, 2, 3, 4]
    by_id = {r["sample_id"]: r for r in rows}
    for sid in (2, 4):
        assert by_id[sid]["status"] == "completed"
        assert by_id[sid]["completed_at"] is not None
    for sid in (1, 3):
        assert by_id[sid]["status"] == "running"
        assert by_id[sid]["completed_at"] is None


def test_ctl_samples_recorder_ahead_of_disk(short_data_dir: Path) -> None:
    """Completed samples show up before they're flushed to the on-disk log.

    With 9 samples and the default ``.eval`` flush_buffer of 3, completing only
    2 (the rest held) leaves those 2 buffered in the recorder and not yet
    written to disk. The listing must still report them, while a direct read of
    the on-disk log does not yet see them.
    """

    @task
    def task_nine() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="y") for i in range(1, 10)],
            solver=[gate()],
            name="task_nine",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    def ready() -> bool:
        evals = current_eval_summaries(0.0)
        return (
            bool(evals)
            and evals[0]["samples"]["completed"] == 2
            and evals[0]["samples"]["in_flight"] == 7
        )

    async def capture() -> dict:
        from inspect_ai.log._file import read_eval_log_sample_summaries_async

        entry = current_eval_summaries(0.0)[0]
        rows = await current_sample_summaries(entry["eval_id"])
        location = next(s.log_location for s in get_eval_states() if s.log_location)
        try:
            on_disk = await read_eval_log_sample_summaries_async(location)
        except (OSError, ValueError):
            on_disk = []
        return {
            "rows": rows,
            "on_disk_completed": {s.id for s in on_disk if s.completed},
        }

    with probe(ready, capture, park=lambda sid: int(sid) not in (1, 2)) as p:
        eval_set(
            tasks=[task_nine()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            max_samples=9,
        )

    assert p.result is not None, "never reached 2-completed + 7-running"
    rows = p.result["rows"]
    assert sorted(r["sample_id"] for r in rows) == list(range(1, 10))
    endpoint_completed = {r["sample_id"] for r in rows if r["status"] == "completed"}
    assert endpoint_completed == {1, 2}
    assert p.result["on_disk_completed"] < endpoint_completed, (
        f"expected recorder ahead of disk; on_disk={p.result['on_disk_completed']}, "
        f"endpoint={endpoint_completed}"
    )


def test_ctl_samples_shows_score_for_single_scorer(short_data_dir: Path) -> None:
    """A completed sample's score is surfaced (summary field + CLI column)."""
    from inspect_ai.scorer import Score, Target, accuracy, scorer

    @scorer(metrics=[accuracy()])
    def const_scorer():
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value="C")

        return score

    @task
    def task_scored() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="C") for i in (1, 2)],
            solver=[gate()],
            scorer=const_scorer(),
            name="task_scored",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    def ready() -> bool:
        evals = current_eval_summaries(0.0)
        return (
            bool(evals)
            and evals[0]["samples"]["completed"] == 1
            and evals[0]["samples"]["in_flight"] == 1
        )

    async def capture() -> list[dict]:
        entry = current_eval_summaries(0.0)[0]
        return await current_sample_summaries(entry["eval_id"])

    with probe(ready, capture, park=lambda sid: int(sid) == 2) as p:
        eval_set(
            tasks=[task_scored()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            max_samples=2,
        )

    rows = p.result
    assert rows is not None, "sample 1 never completed while 2 held"
    completed = next(r for r in rows if r["status"] == "completed")
    scores = completed["scores"]
    assert len(scores) == 1, f"expected a single scorer, got {scores}"
    assert next(iter(scores.values())) == "C"

    out = render(_print_samples_table, rows)
    assert "score" in out.splitlines()[0]  # header row
    assert "C" in out


def test_ctl_samples_includes_pending_samples(short_data_dir: Path) -> None:
    """Pending (not-yet-started) samples are listed alongside running ones.

    With ``max_samples=1`` and a held sample, sample 1 runs while 2 and 3 stay
    queued. They aren't in any live source, so they're synthesized from the
    eval's registered planned ids and reported as ``pending``.
    """

    @task
    def task_many() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="y") for i in (1, 2, 3)],
            solver=[gate()],
            name="task_many",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    def ready() -> bool:
        evals = current_eval_summaries(0.0)
        return (
            bool(evals)
            and evals[0]["samples"]["in_flight"] == 1
            and evals[0]["samples"]["queued"] == 2
        )

    async def capture() -> list[dict]:
        entry = current_eval_summaries(0.0)[0]
        return await current_sample_summaries(entry["eval_id"])

    with probe(ready, capture) as p:
        eval_set(
            tasks=[task_many()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            max_samples=1,
        )

    rows = p.result
    assert rows is not None, "never reached 1-running + 2-pending"
    assert sorted(r["sample_id"] for r in rows) == [1, 2, 3]
    for r in rows:
        if r["status"] == "pending":
            assert r["started_at"] is None
            assert r["total_time"] is None

    out = render(_print_samples_table, rows)
    assert out.count("pending") == 2


def test_ctl_samples_shows_sample_retries(short_data_dir: Path) -> None:
    """A sample retried on error surfaces its retry count.

    Sample 1 errors on its first attempt then succeeds (``retry_on_error`` →
    ``retries == 1``); sample 2 is held. The listing reports the retry count
    and the CLI shows the ``retries`` column.
    """
    calls = {"sample_1": 0}

    @solver
    def flaky_first_sample() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if int(state.sample_id) == 1:
                calls["sample_1"] += 1
                if calls["sample_1"] == 1:
                    raise RuntimeError("transient first-attempt failure")
            else:
                await park_now()
            return state

        return solve

    @task
    def task_retry() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="y") for i in (1, 2)],
            solver=[flaky_first_sample()],
            name="task_retry",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    def ready() -> bool:
        evals = current_eval_summaries(0.0)
        return (
            bool(evals)
            and evals[0]["samples"]["completed"] == 1
            and evals[0]["samples"]["in_flight"] == 1
        )

    async def capture() -> list[dict]:
        entry = current_eval_summaries(0.0)[0]
        return await current_sample_summaries(entry["eval_id"])

    with probe(ready, capture) as p:
        eval_set(
            tasks=[task_retry()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            retry_on_error=1,
            max_samples=2,
        )

    rows = p.result
    assert rows is not None, "sample 1 never completed after retry while 2 held"
    done = [r for r in rows if r["status"] == "completed"]
    assert len(done) == 1
    assert done[0]["sample_id"] == 1
    assert done[0]["retries"] == 1, done[0]

    out = render(_print_samples_table, rows)
    assert "retries" in out


def test_ctl_samples_task_id_stable_across_retry(short_data_dir: Path) -> None:
    """``samples <task_id>`` keeps resolving after an error + task retry.

    A task's per-attempt ``eval_id`` is regenerated on retry but its
    ``task_id`` is stable. The task fails on attempt 1 then is held on the
    retry; after the eval_id has changed, the stable ``task_id`` still resolves
    the running eval.
    """
    fail = {"calls": 0}

    @solver
    def fail_then_park_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            fail["calls"] += 1
            if fail["calls"] == 1:
                raise RuntimeError("synthetic first-attempt failure")
            await park_now()
            return state

        return solve

    @task
    def task_flaky() -> Task:
        return Task(
            dataset=[Sample(input="x", target="y")],
            solver=[fail_then_park_solver()],
            name="task_flaky",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    def ready() -> bool:
        evals = current_eval_summaries(0.0)
        flaky = next((e for e in evals if e["task"] == "task_flaky"), None)
        return (
            fail["calls"] >= 2
            and flaky is not None
            and flaky["status"] == "running"
            and flaky["samples"]["in_flight"] == 1
        )

    async def capture() -> dict:
        flaky = next(
            e for e in current_eval_summaries(0.0) if e["task"] == "task_flaky"
        )
        return {"eval": flaky, "rows": await current_sample_summaries(flaky["eval_id"])}

    with probe(ready, capture) as p:
        eval_set(
            tasks=[task_flaky()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=2,
            retry_immediate=True,
        )

    assert p.result is not None, "flaky task's retry never ran"
    task_id = p.result["eval"]["task_id"]
    assert task_id, "expected a stable task_id"
    # The stable task_id resolves even though the eval_id is now the retry's.
    assert _resolve_target_eval([p.result["eval"]], task_id[:12]) is p.result["eval"]
    running = [r for r in p.result["rows"] if r["status"] == "running"]
    assert len(running) == 1


def test_ctl_samples_shows_task_level_retries(short_data_dir: Path) -> None:
    """A sample re-run by a task-level retry surfaces a retry count.

    ``retry_task`` errors on its first task attempt; with ``retry_on_error=0``
    the task fails and eval-set retries the whole task, re-running the sample
    (now succeeding). The re-run seeds ``error_retries`` from the prior
    attempt, so the surviving sample reports ``retries == 1``. A held task
    keeps the eval-set alive while we read it.
    """
    calls = {"retry": 0}

    @solver
    def fail_first_attempt() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            calls["retry"] += 1
            if calls["retry"] == 1:
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

    @task
    def hang_task() -> Task:
        return Task(
            dataset=[Sample(id=1, input="x", target="y")],
            solver=[gate()],
            name="hang_task",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    async def ready() -> bool:
        # retry_task finishes mid-eval (hang_task holds the eval open), so its
        # recorder is torn down — confirm the completed sample is actually
        # readable (recorder or flushed log), not in the teardown gap, before
        # capturing.
        evals = current_eval_summaries(0.0)
        rt = next((e for e in evals if e["task"] == "retry_task"), None)
        hg = next((e for e in evals if e["task"] == "hang_task"), None)
        if not (
            rt is not None
            and rt["status"] == "completed"
            and hg is not None
            and hg["samples"]["in_flight"] == 1
        ):
            return False
        rows = await current_sample_summaries(rt["eval_id"])
        return any(r["status"] == "completed" for r in rows)

    async def capture() -> list[dict]:
        rt = next(e for e in current_eval_summaries(0.0) if e["task"] == "retry_task")
        return await current_sample_summaries(rt["eval_id"])

    with probe(ready, capture) as p:
        eval_set(
            tasks=[retry_task(), hang_task()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=1,
            retry_on_error=0,
            max_tasks=2,
            max_samples=2,
        )

    rows = p.result
    assert rows is not None, "retry_task never completed while hang_task ran"
    done = [r for r in rows if r["status"] == "completed"]
    assert len(done) == 1
    assert done[0]["sample_id"] == 1
    assert done[0]["retries"] == 1, done[0]

    out = render(_print_samples_table, rows)
    assert "retries" in out


def test_ctl_samples_shows_retries_on_running_reattempt(short_data_dir: Path) -> None:
    """A sample re-running after a task-level failure reports its retry count.

    The sample errors on attempt 1 (task fails → task-level retry), then is
    held on attempt 2. While running on the retry it must report ``retries ==
    1`` and ``ctl sample`` must surface the prior-attempt error from
    ``active_samples`` (it isn't in the log yet).
    """
    calls = {"n": 0}

    @solver
    def fail_then_park_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient failure")
            await park_now()
            return state

        return solve

    @task
    def retry_then_hang_task() -> Task:
        return Task(
            dataset=[Sample(id=1, input="x", target="y")],
            solver=[fail_then_park_solver()],
            name="retry_then_hang_task",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    def ready() -> bool:
        return any(
            s.started is not None and s.completed is None and (s.retries or 0) == 1
            for s in active_samples()
        )

    async def capture() -> dict:
        entry = current_eval_summaries(0.0)[0]
        rows = await current_sample_summaries(entry["eval_id"])
        detail = await sample_error_detail(entry["eval_id"], "1", 1)
        return {"rows": rows, "detail": detail}

    with probe(ready, capture) as p:
        eval_set(
            tasks=[retry_then_hang_task()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=2,
            retry_on_error=0,
            max_samples=1,
        )

    assert p.result is not None, "sample never ran on its retry with retries==1"
    out = render(_print_samples_table, p.result["rows"])
    assert "retries" in out

    detail = p.result["detail"]
    assert detail is not None
    assert detail["status"] == "running"
    out2 = render(_print_sample_detail, detail, False)
    assert "running" in out2
    assert "prior attempts" in out2
    assert "transient failure" in out2


# --- errors / sample detail ------------------------------------------------


def test_ctl_errors_and_sample_surface_prior_attempt_errors(
    short_data_dir: Path,
) -> None:
    """``ctl errors`` lists retried samples; ``ctl sample`` shows prior errors.

    A sample errors on attempt 1, the task is retried, and the sample
    succeeds. The errors listing includes it (retries == 1) and the
    sample-detail render surfaces the attempt-1 error message (message-only by
    default, traceback with ``-t``).
    """
    calls = {"n": 0}

    @solver
    def fail_once() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient boom on attempt 1")
            return state

        return solve

    @task
    def retry_task() -> Task:
        return Task(
            dataset=[Sample(id="recABC", input="x", target="y")],
            solver=[fail_once()],
            name="retry_task",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    with capturing() as cap:
        eval_set(
            tasks=[retry_task()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=1,
            retry_on_error=0,
        )

    assert cap.eval("retry_task") is not None
    rows = cap.eval_samples("retry_task")
    # `ctl errors` filters to samples with an error or any retries.
    errored = [r for r in rows if r.get("error") or (r.get("retries") or 0) > 0]
    errors_out = render(_print_errors_table, errored)
    assert "recABC" in errors_out
    assert "retries" in errors_out

    detail = cap.error_detail("retry_task", "recABC", 1)
    assert detail is not None
    out = render(_print_sample_detail, detail, False)
    assert "prior attempts" in out
    assert "transient boom on attempt 1" in out
    assert "Traceback" not in out  # message-only by default

    out_tb = render(_print_sample_detail, detail, True)
    assert "Traceback" in out_tb


def test_ctl_sample_addresses_ids_with_reserved_chars(short_data_dir: Path) -> None:
    """Sample ids with URL-reserved chars round-trip through the data layer.

    Sample ids may be arbitrary strings — ``case/001`` (path separator),
    ``q?x#y`` (query / fragment delimiters). They must be addressable by
    ``sample_error_detail``. (The HTTP query-param encoding that lets the CLI
    reach them is covered in ``test_server.py``.)
    """
    tricky_ids = ["case/001", "q?x#y"]

    @solver
    def passthrough() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            return state

        return solve

    @task
    def slashy() -> Task:
        return Task(
            dataset=[Sample(id=sid, input="x", target="y") for sid in tricky_ids],
            solver=[passthrough()],
            name="slashy",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    with capturing() as cap:
        eval_set(
            tasks=[slashy()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            max_samples=2,
        )

    entry = cap.eval("slashy")
    assert entry is not None
    assert entry["samples"]["completed"] == 2
    for sid in tricky_ids:
        detail = cap.error_detail("slashy", sid, 1)
        assert detail is not None, f"id={sid!r} not addressable"
        assert str(detail["sample_id"]) == sid


# --- terminal-disposition counters -----------------------------------------


def test_ctl_eval_finishes_when_samples_early_stopped(short_data_dir: Path) -> None:
    """Early-stopped samples count toward the eval's terminal total.

    An early-stopping manager halts the even-id samples before they run. Those
    never hit the normal completed/errored path, so without counting them the
    eval's ``completed + errored`` never reaches ``total`` and it reads
    ``running`` forever. With the fix it settles ``completed``.
    """
    from inspect_ai.util._early_stopping import EarlyStop

    class StopEvenIds:
        async def start_task(self, task, samples, epochs):
            return "stop-even-ids"

        async def schedule_sample(self, id, epoch):
            if int(id) % 2 == 0:
                return EarlyStop(id=id, epoch=epoch, reason="test")
            return None

        async def complete_sample(self, id, epoch, scores):
            return None

        async def complete_task(self):
            return {}

    @solver
    def passthrough() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            return state

        return solve

    @task
    def early() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="y") for i in (1, 2, 3, 4)],
            solver=[passthrough()],
            early_stopping=StopEvenIds(),
            name="early",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    with capturing() as cap:
        eval_set(
            tasks=[early()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            max_samples=5,
        )

    entry = cap.eval("early")
    assert entry is not None
    assert entry["status"] == "completed", entry
    samples = entry["samples"]
    # 2 ran to completion + 2 early-stopped, all terminal -> total reached.
    assert samples["completed"] == 4
    assert samples["in_flight"] == 0
    assert samples["queued"] == 0


def test_ctl_eval_usage_persists_after_samples_complete(short_data_dir: Path) -> None:
    """Eval-level usage totals survive samples leaving ``active_samples``.

    ``total_tokens`` / ``total_messages`` were once summed only over the live
    ``ActiveSample`` list, so once samples completed the reported usage fell
    back toward zero. Accumulated at each sample's terminal outcome, it must
    persist — observed here at run end, after every sample has left
    ``active_samples``.
    """

    @solver
    def gen() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            return await generate(state)

        return solve

    @task
    def work() -> Task:
        return Task(
            dataset=[Sample(id=i, input="hi", target="ok") for i in (1, 2, 3)],
            solver=[gen()],
            name="work",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    with capturing() as cap:
        eval_set(
            tasks=[work()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            max_samples=5,
        )

    entry = cap.eval("work")
    assert entry is not None
    assert entry["samples"]["completed"] == 3
    assert entry["samples"]["in_flight"] == 0
    assert entry["total_messages"] > 0, entry
    assert entry["total_tokens"] > 0, entry


def test_ctl_eval_finishes_when_final_attempt_cancels_sibling(
    short_data_dir: Path,
) -> None:
    """A terminal cancellation counts toward the eval's total.

    Sample 1 errors and tears the task down (no retry), cancelling in-flight
    sample 2. The cancelled sample is logged but re-raised before any terminal
    counter runs — so without a ``cancelled`` counter ``completed + errored``
    never reaches ``total`` and the failed eval reads ``running`` forever.
    """

    @solver
    def fail_and_hold() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if int(state.sample_id) == 1:
                raise RuntimeError("boom")
            # Stay in flight until sample 1's failure tears the task down,
            # cancelling this sample (recorded as cancelled). No timed sleep.
            await park_now()
            return state

        return solve

    @task
    def failing() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="y") for i in (1, 2)],
            solver=[fail_and_hold()],
            name="failing",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    with capturing() as cap:
        eval_set(
            tasks=[failing()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            max_samples=4,
        )

    entry = cap.eval("failing")
    assert entry is not None
    assert entry["status"] == "completed", entry
    samples = entry["samples"]
    assert samples["errored"] == 1
    assert samples["cancelled"] == 1
    assert samples["queued"] == 0
    assert samples["in_flight"] == 0


def test_ctl_eval_finishes_when_limit_selects_zero_samples(
    short_data_dir: Path,
) -> None:
    """A zero-sample eval (limit slices past the dataset) settles 'completed'.

    ``limit=(10, 11)`` against a 2-sample dataset selects nothing — a valid,
    successful eval-set outcome. The eval registers ``total=0``; with no sample
    to ever fire a terminal counter, it must still reach a terminal
    ``completed_at`` rather than read ``running`` forever.
    """

    @task
    def tiny() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="y") for i in (1, 2)],
            solver=[generate()],
            name="tiny",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    with capturing() as cap:
        ok, _ = eval_set(
            tasks=[tiny()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            limit=(10, 11),  # past the 2-sample dataset -> 0 samples selected
        )
    assert ok

    entry = cap.eval("tiny")
    assert entry is not None
    assert entry["samples"]["total"] == 0
    assert entry["status"] == "completed", entry
    assert entry["completed_at"] is not None


# --- events / GET /evals/<id>/sample/events --------------------------------


def test_ctl_events_streams_running_sample_transcript(short_data_dir: Path) -> None:
    """A running sample's transcript events are readable, filterable, cursored.

    A solver runs ``generate()`` (producing a ``model`` event) then is held in
    flight; the events page must surface it, the cursor must be exclusive
    (resuming with ``next`` re-delivers nothing), the ``--type`` filter must
    narrow, and the ``samples?active_since`` recency filter must be wired.
    """

    @solver
    def gen_then_park() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            state = await generate(state)
            await park_now()  # hold the sample in flight after a model call
            return state

        return solve

    @task
    def task_one() -> Task:
        return Task(
            dataset=[Sample(id=1, input="hi", target="ok")],
            solver=[gen_then_park()],
            name="task_one",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    def ready() -> bool:
        evals = current_eval_summaries(0.0)
        return bool(evals) and evals[0]["samples"]["in_flight"] == 1

    async def capture() -> dict:
        import time as _time

        eid = current_eval_summaries(0.0)[0]["eval_id"]
        page = await sample_events(eid, "1", 1)
        assert page is not None
        return {
            "page": page,
            "model_only": await sample_events(eid, "1", 1, types=frozenset({"model"})),
            "resumed": await sample_events(eid, "1", 1, since=page["next"]),
            "active_future": await current_sample_summaries(
                eid, active_since=_time.time() + 1000
            ),
            "active_all": await current_sample_summaries(eid, active_since=0.0),
        }

    with probe(ready, capture) as p:
        eval_set(
            tasks=[task_one()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
        )

    res = p.result
    assert res is not None, "sample never reached in-flight after generate()"

    page = res["page"]
    assert set(page) >= {"events", "next", "done", "missed"}
    assert page["done"] is False  # still running (parked)
    assert page["missed"] == 0  # non-bounded transcript
    assert len(page["events"]) >= 1

    # type filter: model-only page is non-empty and exclusively model events
    model_only = res["model_only"]
    assert len(model_only["events"]) >= 1
    assert all(e["event"] == "model" for e in model_only["events"])

    # cursor is exclusive: resuming from `next` never re-delivers seen events
    seen = {e["uuid"] for e in page["events"]}
    assert seen.isdisjoint(e["uuid"] for e in res["resumed"]["events"])

    # samples recency filter wiring: nothing is active in the future; the
    # running sample shows up for active_since=0
    assert res["active_future"] == []
    assert any(r["sample_id"] == 1 for r in res["active_all"])


# Cross-sample channel for the transition test below: the subject sample (id 1)
# stashes the cursor it was handed while running; the observer (id 2) resumes it
# once the subject is terminal. Module-level because the two run as separate
# sample tasks in one eval.
_transition_cursor: dict[str, Any] = {}


def test_event_cursor_survives_running_to_terminal_transition(
    short_data_dir: Path,
) -> None:
    """A cursor issued while running resumes cleanly after the sample is logged.

    The running source keyed its cursor on the throwaway ``ActiveSample.id``
    while the terminal source keys on ``EvalSample.uuid``; those are generated
    independently, so a cursor handed out mid-run looked *stale* once the sample
    completed and the resume silently restarted from offset 0 — re-delivering
    every already-seen event. Both sources must key on the same durable id (the
    sample uuid), so the cursor stays valid across the transition.

    End-to-end: sample 1 records the ``next`` cursor it gets while running, then
    completes; the parked observer (sample 2) resumes from that cursor once
    sample 1 is terminal and asserts continuity (matched nonce, no duplicates).
    """
    _transition_cursor.clear()

    @solver
    def subject_or_observer() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if int(state.sample_id) == 1:
                # subject: produce some events, then snapshot the running cursor
                state = await generate(state)
                eid = current_eval_summaries(0.0)[0]["eval_id"]
                page = await sample_events(eid, "1", state.epoch)
                assert page is not None and page["done"] is False
                _transition_cursor.update(
                    eid=eid,
                    cursor=page["next"],
                    seen=[e["uuid"] for e in page["events"]],
                )
                return state
            await park_now()  # observer: hold in flight until the probe fires
            return state

        return solve

    @task
    def task_two() -> Task:
        return Task(
            dataset=[Sample(id=i, input="hi", target="ok") for i in (1, 2)],
            solver=[subject_or_observer()],
            name="task_two",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    async def ready() -> bool:
        evals = current_eval_summaries(0.0)
        if not evals or "cursor" not in _transition_cursor:
            return False
        eid = evals[0]["eval_id"]
        # subject terminal (and readable as such), observer still in flight
        if evals[0]["samples"]["completed"] < 1:
            return False
        return await sample_error_detail(eid, "1", 1) is not None

    async def capture() -> dict:
        eid = _transition_cursor["eid"]
        return {
            "resumed": await sample_events(
                eid, "1", 1, since=_transition_cursor["cursor"]
            ),
            "full": await sample_events(eid, "1", 1),
        }

    with probe(ready, capture, park=lambda sid: int(sid) == 2) as p:
        eval_set(
            tasks=[task_two()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
        )

    res = p.result
    assert res is not None, "subject never went terminal while observer was held"

    running_cursor = _transition_cursor["cursor"]
    seen = set(_transition_cursor["seen"])
    assert seen, "subject produced no events to resume past"

    resumed, full = res["resumed"], res["full"]
    assert resumed is not None and full is not None

    # the running cursor's nonce matches the terminal page's nonce — the resume
    # recognizes it instead of treating it as stale and restarting from 0
    assert decode_cursor(running_cursor)[0] == decode_cursor(full["next"])[0]

    # the sample is fully drained, and resuming the mid-run cursor delivers only
    # events past it — never the already-seen ones (the duplicate-on-resume bug)
    assert resumed["done"] is True
    assert seen.isdisjoint(e["uuid"] for e in resumed["events"])
    # and it genuinely resumed mid-stream rather than replaying the whole log
    assert len(resumed["events"]) < len(full["events"])


def test_ctl_events_reads_completed_sample_from_log(short_data_dir: Path) -> None:
    """Once a sample is terminal, its events come from the log with done=True."""

    @task
    def task_done() -> Task:
        return Task(
            dataset=[Sample(id=1, input="hi", target="ok")],
            solver=[generate()],
            name="task_done",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    with capturing() as cap:
        eval_set(
            tasks=[task_done()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
        )

    page = cap.events_page("task_done", 1)
    assert page is not None, "no events page captured for the completed sample"
    assert page["done"] is True
    assert len(page["events"]) >= 1
    assert any(e["event"] == "model" for e in page["events"])


@pytest.mark.parametrize("log_format", ["eval", "json"])
def test_ctl_addresses_terminal_sample_by_digit_string_id(
    short_data_dir: Path, log_format: str
) -> None:
    """A digit-looking string id (e.g. "001") stays addressable once terminal.

    The endpoints take arbitrary string ids, and a sample defined with id
    "001" is stored — and keyed on disk — as the string "001". Coercing it to
    the int ``1`` before the terminal read addressed the wrong sample, so
    `ctl samples` listed "001" while `ctl sample 001` / `ctl events 001`
    returned not-found. The read must match the id verbatim first.
    """

    @task
    def task_zero_padded() -> Task:
        return Task(
            dataset=[Sample(id="001", input="hi", target="ok")],
            solver=[generate()],
            name="zero_padded",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    with capturing() as cap:
        eval_set(
            tasks=[task_zero_padded()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            log_format=log_format,  # type: ignore[arg-type]
        )

    # the listing surfaces the sample under its string id ...
    assert any(str(r["sample_id"]) == "001" for r in cap.eval_samples("zero_padded"))

    # ... and addressing it by that same string finds detail + events (it would
    # be None if "001" had been coerced to the int 1 for the lookup).
    assert cap.error_detail("zero_padded", "001", 1) is not None
    page = cap.events_page("zero_padded", "001", 1)
    assert page is not None and len(page["events"]) >= 1


@pytest.mark.parametrize("log_format", ["eval", "json"])
def test_ctl_sample_detail_and_events_find_recorder_completed_sample(
    short_data_dir: Path, log_format: str
) -> None:
    """`sample` / `events` must find a sample the recorder reports completed.

    Reproduces the demo bug where, during a retried eval, `ctl sample` /
    `ctl events` reported a sample "not found" while `ctl samples` showed it
    completed (flapping found → not-found → found across attempts).

    Root cause: `current_sample_summaries` (→ `ctl samples`) sources completed
    samples from the recorder via `summaries_provider` (gap-free / ahead of
    disk), but `sample_error_detail` (→ `ctl sample`) and `sample_events`
    (→ `ctl events`) read only the on-disk `log_location`. A completed sample
    not yet flushed to disk is therefore visible to `samples` but missing from
    `sample` / `events`. A retry makes this acute: reused samples are re-logged
    into the new attempt with `complete_sample(..., flush=False)`, so they sit
    unflushed in the recorder for an extended window.

    Parametrized over both log formats: the fix routes per-sample reads through
    the recorder's gap-free buffer (`buffered_sample`), which each recorder
    implements over its own in-memory store (`.eval`'s `_samples` /
    `_streaming_samples`, JSON's `log.data.samples`).

    Setup mirrors `test_ctl_samples_recorder_ahead_of_disk`: 9 samples, ids 1–2
    complete (and leave `active_samples`) while 3–9 are held, with too few
    completions to trigger a flush — so sample 1 is in the recorder but not on
    disk and not in `active_samples`. It must still be reachable by `sample`
    and `events`, not just `samples`.
    """

    @task
    def task_nine() -> Task:
        return Task(
            dataset=[Sample(id=i, input="x", target="y") for i in range(1, 10)],
            solver=[gate()],
            name="task_nine",
        )

    log_dir = str(short_data_dir / "logs")
    Path(log_dir).mkdir()

    def ready() -> bool:
        evals = current_eval_summaries(0.0)
        if not evals:
            return False
        eid = evals[0]["eval_id"]
        in_active = {str(s.sample.id) for s in active_samples() if s.eval_id == eid}
        samples = evals[0]["samples"]
        # samples 1 & 2 completed (and gone from active_samples); 7 still held
        return (
            samples["completed"] == 2
            and samples["in_flight"] == 7
            and "1" not in in_active
        )

    async def capture() -> dict:
        from inspect_ai.log._file import read_eval_log_sample_summaries_async

        eid = current_eval_summaries(0.0)[0]["eval_id"]
        location = next(s.log_location for s in get_eval_states() if s.log_location)
        try:
            on_disk = await read_eval_log_sample_summaries_async(location)
        except (OSError, ValueError):
            on_disk = []
        return {
            "rows": await current_sample_summaries(eid),
            "on_disk_completed": {s.id for s in on_disk if s.completed},
            "detail": await sample_error_detail(eid, "1", 1),
            "events": await sample_events(eid, "1", 1),
        }

    with probe(ready, capture, park=lambda sid: int(sid) not in (1, 2)) as p:
        eval_set(
            tasks=[task_nine()],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            max_samples=9,
            log_format=log_format,  # type: ignore[arg-type]
        )

    res = p.result
    assert res is not None, "never reached 2-completed + 7-running"

    # Precondition: sample 1 is recorder-completed but NOT yet on disk.
    done_row = next((r for r in res["rows"] if r["sample_id"] == 1), None)
    assert done_row is not None and done_row["status"] == "completed", res["rows"]
    assert 1 not in res["on_disk_completed"], (
        "test premise broken: sample 1 was flushed to disk, so the recorder/"
        "disk gap isn't exercised"
    )

    # The bug: `sample` / `events` read only the on-disk log and miss it.
    assert res["detail"] is not None, (
        "sample_error_detail lost a recorder-completed sample (reads the on-disk "
        "log only, not the recorder)"
    )
    assert res["events"] is not None, (
        "sample_events lost a recorder-completed sample (reads the on-disk log "
        "only, not the recorder)"
    )
