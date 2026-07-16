"""Tests for the control-channel pause/resume directives (design/pause-resume.md).

Covers the gate primitive and sample-dispatch wrapper in
``inspect_ai._control.pause``, the directive functions (task pause/resume:
task-keyed like cancel; process pause/resume: the one process-scoped latch),
the server routes that wrap them (``POST /tasks/<id>/pause|resume``,
``POST /pause`` / ``POST /resume``), and the ``paused`` / ``quiesced``
fields on ``GET /tasks``.
"""

from typing import Any

import anyio
import httpx
import pytest
from test_helpers.live_eval_data import FakeLiveEvalData

from inspect_ai._control.eval_state import (
    clear_all_eval_states,
    mark_eval_retry_pending,
    record_sample_errored,
    register_eval,
)
from inspect_ai._control.pause import (
    PauseGatedSemaphore,
    pause_process,
    pause_task,
    process_paused,
    reset_process_pause,
    reset_task_pause_gates,
    resume_process,
    resume_task,
    task_dispatch_paused,
    task_dispatched_count,
    task_pause_scope,
    wake_pause_waiters,
)
from inspect_ai.hooks import Hooks, TaskEnd, hooks


@pytest.fixture(autouse=True)
def _clear_states():
    def clear() -> None:
        clear_all_eval_states()
        reset_task_pause_gates()
        reset_process_pause()

    clear()
    yield
    clear()


class _FakeActiveSample:
    """The slice of ``ActiveSample`` the summary rows read."""

    def __init__(
        self,
        *,
        eval_id: str = "e1",
        started: float | None = 1.0,
        completed: float | None = None,
    ) -> None:
        self.eval_id = eval_id
        self.started = started
        self.completed = completed
        self.task = "my_task"
        self.model = "mockllm/model"
        self.run_id = "r1"
        self.total_tokens = 0
        self.total_messages = 0


def _patch_active_samples(
    monkeypatch: pytest.MonkeyPatch, samples: list[_FakeActiveSample]
) -> None:
    monkeypatch.setattr("inspect_ai.log._samples.active_samples", lambda: samples)


# ---------------------------------------------------------------------------
# task pause/resume directives
# ---------------------------------------------------------------------------


async def test_pause_task_unknown_is_none() -> None:
    assert await pause_task("nope") is None
    assert await resume_task("nope") is None
    assert await pause_task("") is None


async def test_pause_task_closes_gate() -> None:
    register_eval("e1", 5, task_id="t1", task="my_task")

    result = await pause_task("t1")
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert result["task_id"] == "t1" and result["eval_id"] == "e1"
    assert result["paused"] == "task"
    assert result["dispatched"] == 0
    assert task_dispatch_paused("t1")
    assert task_pause_scope("t1") == "task"


async def test_pause_task_repeat_is_idempotent_noop() -> None:
    register_eval("e1", 5, task_id="t1")

    assert (await pause_task("t1") or {})["changed"] is True
    repeat = await pause_task("t1")
    assert repeat is not None
    assert repeat["changed"] is False and "already paused" in repeat["reason"]
    assert task_dispatch_paused("t1")


async def test_pause_task_dry_run_does_not_flip() -> None:
    register_eval("e1", 5, task_id="t1")

    result = await pause_task("t1", dry_run=True)
    assert result is not None
    assert result["changed"] is True and result["dry_run"] is True
    assert not task_dispatch_paused("t1")


async def test_pause_task_finished_is_noop() -> None:
    # a zero-sample eval registers already finished
    register_eval("e1", 0, task_id="t1")

    result = await pause_task("t1")
    assert result is not None
    assert result["changed"] is False and "already finished" in result["reason"]
    assert not task_dispatch_paused("t1")


async def test_pause_task_between_attempts_parks_the_retry() -> None:
    """Pausing a between-attempts task works (unlike cancel's 409 rejection).

    The gate is task-keyed, so the queued retry attempt holds at dispatch —
    the design's softening of the cancel-between-attempts wart.
    """
    register_eval("e1", 1, task_id="t1")
    record_sample_errored("e1")  # attempt finished (errored)
    mark_eval_retry_pending("e1")

    result = await pause_task("t1")
    assert result is not None and result["changed"] is True
    assert task_dispatch_paused("t1")


async def test_resume_task_reopens_gate() -> None:
    register_eval("e1", 5, task_id="t1")
    await pause_task("t1")

    result = await resume_task("t1")
    assert result is not None and result["changed"] is True
    assert result["paused"] is None
    assert not task_dispatch_paused("t1")

    repeat = await resume_task("t1")
    assert repeat is not None
    assert repeat["changed"] is False and "not paused" in repeat["reason"]


async def test_resume_task_dry_run_does_not_flip() -> None:
    register_eval("e1", 5, task_id="t1")
    await pause_task("t1")

    result = await resume_task("t1", dry_run=True)
    assert result is not None
    assert result["changed"] is True and result["dry_run"] is True
    assert task_dispatch_paused("t1")


async def test_last_write_wins_pause_resume_pause() -> None:
    register_eval("e1", 5, task_id="t1")
    await pause_task("t1")
    await resume_task("t1")
    await pause_task("t1")
    assert task_dispatch_paused("t1")


async def test_pause_survives_task_retry_attempts() -> None:
    """The gate is task-id keyed, so a retry attempt (fresh eval_id) stays held."""
    register_eval("e1", 2, task_id="t1")
    await pause_task("t1")
    # retry attempt registers a fresh eval under the same task_id
    register_eval("e2", 2, task_id="t1")
    assert task_dispatch_paused("t1")
    result = await resume_task("t1")
    assert result is not None and result["eval_id"] == "e2"


# ---------------------------------------------------------------------------
# process pause/resume directives
# ---------------------------------------------------------------------------


async def test_process_pause_resume_roundtrip() -> None:
    result = await pause_process()
    assert result["ok"] is True and result["changed"] is True
    assert process_paused()

    repeat = await pause_process()
    assert repeat["changed"] is False and "already paused" in repeat["reason"]

    resumed = await resume_process()
    assert resumed["changed"] is True
    assert not process_paused()

    again = await resume_process()
    assert again["changed"] is False and "not paused" in again["reason"]


async def test_process_pause_dry_run_does_not_flip() -> None:
    result = await pause_process(dry_run=True)
    assert result["changed"] is True and result["dry_run"] is True
    # `paused` reports the actual latch state (like the task envelope), not
    # the would-be state
    assert result["paused"] is False
    assert not process_paused()

    await pause_process()
    result = await resume_process(dry_run=True)
    assert result["changed"] is True and result["paused"] is True
    assert process_paused()


async def test_process_latch_holds_every_task() -> None:
    register_eval("e1", 5, task_id="t1")
    await pause_process()
    assert task_pause_scope("t1") == "process"
    assert task_dispatch_paused("t1")
    # even one never explicitly paused / registered
    assert task_dispatch_paused("t-other")


async def test_independent_latches_do_not_clear_each_other() -> None:
    register_eval("e1", 5, task_id="t1")
    await pause_task("t1")
    await pause_process()
    assert task_pause_scope("t1") == "both"

    # process resume leaves the task-level pause in place
    await resume_process()
    assert task_pause_scope("t1") == "task"
    assert task_dispatch_paused("t1")

    # and task resume under the process latch leaves the process pause
    await pause_process()
    result = await resume_task("t1")
    assert result is not None and result["changed"] is True
    assert result["paused"] == "process"
    assert task_dispatch_paused("t1")


# ---------------------------------------------------------------------------
# sample dispatch gate (PauseGatedSemaphore)
# ---------------------------------------------------------------------------


async def test_gated_semaphore_open_gate_passes_through() -> None:
    register_eval("e1", 2, task_id="t1")
    sem = anyio.Semaphore(1)
    gated = PauseGatedSemaphore(sem, task_id="t1")
    async with gated:
        assert sem.value == 0
    assert sem.value == 1


async def test_gated_semaphore_holds_until_resume() -> None:
    register_eval("e1", 2, task_id="t1")
    await pause_task("t1")
    sem = anyio.Semaphore(1)
    gated = PauseGatedSemaphore(sem, task_id="t1")
    entered = anyio.Event()

    async def enter() -> None:
        async with gated:
            entered.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(enter)
        await anyio.sleep(0.05)
        # held at the gate, before the semaphore: no slot pinned
        assert not entered.is_set()
        assert sem.value == 1
        await resume_task("t1")
        with anyio.fail_after(5):
            await entered.wait()


async def test_gated_semaphore_holds_under_process_latch() -> None:
    register_eval("e1", 2, task_id="t1")
    await pause_process()
    sem = anyio.Semaphore(1)
    gated = PauseGatedSemaphore(sem, task_id="t1")
    entered = anyio.Event()

    async def enter() -> None:
        async with gated:
            entered.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(enter)
        await anyio.sleep(0.05)
        assert not entered.is_set()
        await resume_process()
        with anyio.fail_after(5):
            await entered.wait()


async def test_gated_semaphore_recheck_releases_slot() -> None:
    """A pause landing while a coroutine is blocked on the semaphore doesn't leak a start."""
    register_eval("e1", 2, task_id="t1")
    sem = anyio.Semaphore(1)
    gated = PauseGatedSemaphore(sem, task_id="t1")
    entered = anyio.Event()
    release_holder = anyio.Event()

    async def holder() -> None:
        async with sem:
            await release_holder.wait()

    counts_inside: list[int] = []

    async def entrant() -> None:
        async with gated:
            counts_inside.append(task_dispatched_count("t1"))
            entered.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(holder)
        await anyio.sleep(0.01)
        tg.start_soon(entrant)  # gate open — blocks on the inner semaphore
        await anyio.sleep(0.05)
        await pause_task("t1")  # pause lands while blocked on the acquire
        release_holder.set()  # slot frees: entrant re-checks and releases it
        await anyio.sleep(0.05)
        assert not entered.is_set()
        assert sem.value == 1  # the paused entrant pins no slot
        assert task_dispatched_count("t1") == 0  # nor counts as dispatched
        await resume_task("t1")
        with anyio.fail_after(5):
            await entered.wait()
    assert counts_inside == [1]  # dispatched exactly while inside the gate
    assert task_dispatched_count("t1") == 0  # and released on exit


async def test_gated_semaphore_stamped_cancel_escapes() -> None:
    """A graceful cancel passes the gate so held samples reach the abandon check."""
    register_eval("e1", 2, task_id="t1")
    await pause_task("t1")
    cancel: dict[str, Any] = {"type": None}
    sem = anyio.Semaphore(1)
    gated = PauseGatedSemaphore(
        sem, task_id="t1", escape=lambda: cancel["type"] is not None
    )
    entered = anyio.Event()

    async def enter() -> None:
        async with gated:
            entered.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(enter)
        await anyio.sleep(0.05)
        assert not entered.is_set()
        # the cancel-stamp choke point: stamp, then wake gate waiters
        cancel["type"] = "score"
        wake_pause_waiters()
        with anyio.fail_after(5):
            await entered.wait()
    assert task_dispatch_paused("t1")  # the gate itself stays closed


# ---------------------------------------------------------------------------
# quiesce auto-flush
# ---------------------------------------------------------------------------


async def test_pause_of_idle_task_flushes_immediately() -> None:
    flushes: list[int] = []

    async def flush() -> int:
        flushes.append(1)
        return 1

    register_eval("e1", 5, task_id="t1", live=FakeLiveEvalData(flush=flush))

    await pause_task("t1")
    assert flushes  # nothing dispatched → quiesced at the pause itself


async def test_pause_with_dispatched_sample_defers_flush_to_quiesce() -> None:
    """A dispatched sample blocks the auto-flush until it finishes.

    Dispatch is counted at the gate itself (``PauseGatedSemaphore``), so a
    sample holds quiesce for its whole life past the gate — including the
    windows where ``active_samples`` hasn't registered it yet (real await
    points sit between the gate and registration) and where it is still
    materializing its sandbox with ``started=None`` (minutes, potentially).
    A pause landing anywhere in that span must not flush — the "safe to
    kill" signal must not flip true→false. The last dispatched sample
    completing is the quiesce transition: the gate's exit path runs the
    flush.
    """
    flushes: list[int] = []

    async def flush() -> int:
        flushes.append(1)
        return 1

    register_eval("e1", 5, task_id="t1", live=FakeLiveEvalData(flush=flush))
    gated = PauseGatedSemaphore(anyio.Semaphore(1), task_id="t1")
    await gated.__aenter__()  # past the gate; not yet in active_samples

    await pause_task("t1")
    assert not flushes  # still draining — not safe to kill

    await gated.__aexit__(None, None, None)
    assert flushes


async def test_process_pause_flushes_idle_tasks() -> None:
    flushes: list[int] = []

    async def flush() -> int:
        flushes.append(1)
        return 1

    register_eval("e1", 5, task_id="t1", live=FakeLiveEvalData(flush=flush))

    await pause_process()
    assert flushes


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


def _app() -> Any:
    from inspect_ai._control.server import ControlServer

    return ControlServer(run_id="test")._build_app()


async def test_route_task_pause_resume() -> None:
    register_eval("e1", 3, task_id="t1", task="my_task")
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/tasks/t1/pause")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True and body["changed"] is True
        assert body["paused"] == "task"
        assert task_dispatch_paused("t1")

        repeat = await client.post("/tasks/t1/pause")
        assert repeat.json()["changed"] is False

        resumed = await client.post("/tasks/t1/resume")
        assert resumed.json()["changed"] is True
        assert not task_dispatch_paused("t1")


async def test_route_task_pause_unknown_task_404s_with_error_body() -> None:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/tasks/nope/pause")
        assert response.status_code == 404
        # handler 404s must carry {"error": ...} (the version-skew convention)
        assert "error" in response.json()
        response = await client.post("/tasks/nope/resume")
        assert response.status_code == 404
        assert "error" in response.json()


async def test_route_task_pause_dry_run() -> None:
    register_eval("e1", 3, task_id="t1")
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/tasks/t1/pause", params={"dry_run": "true"})
        body = response.json()
        assert body["changed"] is True and body["dry_run"] is True
        assert not task_dispatch_paused("t1")


async def test_route_process_pause_resume() -> None:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/pause")
        body = response.json()
        assert body["ok"] is True and body["changed"] is True and body["paused"] is True
        assert process_paused()

        repeat = await client.post("/pause")
        assert repeat.json()["changed"] is False

        resumed = await client.post("/resume")
        body = resumed.json()
        assert body["changed"] is True and body["paused"] is False
        assert not process_paused()


async def test_route_process_pause_rejects_unknown_params() -> None:
    """Mutations fail closed on unknown query params (the strict convention)."""
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/pause", params={"bogus": "1"})
        assert response.status_code == 400
        assert not process_paused()


async def test_tasks_listing_reports_paused_and_quiesced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_eval("e1", 3, task_id="t1", task="my_task")
    _patch_active_samples(monkeypatch, [])
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        rows = (await client.get("/tasks")).json()
        assert rows[0]["paused"] is None
        assert rows[0]["quiesced"] is False
        assert rows[0]["process_paused"] is False

        await pause_task("t1")
        rows = (await client.get("/tasks")).json()
        assert rows[0]["paused"] == "task"
        assert rows[0]["quiesced"] is True  # paused and nothing in flight

        await pause_process()
        rows = (await client.get("/tasks")).json()
        assert rows[0]["paused"] == "both"
        assert rows[0]["process_paused"] is True


async def test_tasks_listing_paused_with_in_flight_not_quiesced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_eval("e1", 3, task_id="t1")
    _patch_active_samples(monkeypatch, [_FakeActiveSample(eval_id="e1")])
    gated = PauseGatedSemaphore(anyio.Semaphore(1), task_id="t1")
    await gated.__aenter__()  # the running sample's gate entry
    try:
        await pause_task("t1")
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            rows = (await client.get("/tasks")).json()
            assert rows[0]["paused"] == "task"
            assert rows[0]["quiesced"] is False
    finally:
        await gated.__aexit__(None, None, None)


async def test_tasks_listing_initializing_sample_blocks_quiesced() -> None:
    """The quiesced signal counts samples from the gate itself.

    A sample past the gate but mid-initialization — not yet registered in
    active_samples at all, or registered but mid-sandbox-creation with
    started=None — will run once its sandbox is up. Reporting quiesced then
    would let the "safe to kill" signal flip true→false while an operator
    acts on it.
    """
    register_eval("e1", 3, task_id="t1")
    gated = PauseGatedSemaphore(anyio.Semaphore(1), task_id="t1")
    await gated.__aenter__()  # past the gate; nothing in active_samples yet
    try:
        await pause_task("t1")
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            rows = (await client.get("/tasks")).json()
            assert rows[0]["paused"] == "task"
            assert rows[0]["quiesced"] is False
    finally:
        await gated.__aexit__(None, None, None)


async def test_tasks_listing_reports_paused_between_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A paused between-attempts task stays visibly paused in the listing.

    Its latest attempt has completed_at set (the attempt errored) with the
    retry queued behind the gate — for as long as the pause holds, which is
    indefinite — so the row must keep reporting the holding latch. Nothing
    is dispatched and the errored attempt is fully logged, so it is also
    quiesced (safe to kill).
    """
    register_eval("e1", 1, task_id="t1")
    record_sample_errored("e1")
    mark_eval_retry_pending("e1")
    _patch_active_samples(monkeypatch, [])
    await pause_task("t1")
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        rows = (await client.get("/tasks")).json()
        assert rows[0]["paused"] == "task"
        assert rows[0]["quiesced"] is True


async def test_tasks_listing_finished_task_reports_unpaused() -> None:
    register_eval("e1", 0, task_id="t1")  # finished at registration
    await pause_process()
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        rows = (await client.get("/tasks")).json()
        assert rows[0]["paused"] is None
        assert rows[0]["quiesced"] is False


# ---------------------------------------------------------------------------
# dispatcher wake
# ---------------------------------------------------------------------------


async def test_resume_fires_dispatch_wakers() -> None:
    """The task dispatchers' wake callbacks fire on every resume."""
    from inspect_ai._control.pause import add_dispatch_waker, remove_dispatch_waker

    fired: list[int] = []

    def waker() -> None:
        fired.append(1)

    add_dispatch_waker(waker)
    try:
        register_eval("e1", 1, task_id="t1")
        await pause_task("t1")
        await resume_task("t1")
        assert fired

        fired.clear()
        await pause_process()
        await resume_process()
        assert fired
    finally:
        remove_dispatch_waker(waker)

    fired.clear()
    await pause_process()
    await resume_process()
    assert not fired  # removed wakers stay removed


# ---------------------------------------------------------------------------
# end-to-end: real evals
# ---------------------------------------------------------------------------


def test_eval_task_pause_holds_queued_samples_until_resume(
    tmp_path: Any,
) -> None:
    """End-to-end quiesce semantics through a real eval.

    Three samples, two slots: sample 1 (the orchestrator) pauses the task
    while sample 2 is still running; sample 3 — blocked on the sample
    semaphore when the pause lands — must NOT start when sample 2's slot
    frees (the post-acquire re-check parks it without pinning the slot).
    The orchestrator observes the drain (`paused` on the read surface, not
    quiesced while it still runs), resumes, and sample 3 then dispatches.
    """
    from inspect_ai import Task
    from inspect_ai._control.eval_state import get_eval_states
    from inspect_ai._control.state import current_eval_summaries
    from inspect_ai._eval.evalset import eval_set
    from inspect_ai.dataset import Sample
    from inspect_ai.log._samples import active_samples
    from inspect_ai.solver import Generate, TaskState, solver

    started: list[Any] = []
    flags: dict[str, Any] = {"resumed": False, "row": None, "errors": []}
    events: dict[str, anyio.Event] = {}

    def in_flight() -> int:
        return sum(
            1 for s in active_samples() if s.started is not None and s.completed is None
        )

    @solver(name=f"pause_orchestrator_{id(flags)}")
    def orchestrator():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            sid = state.sample_id
            started.append(sid)
            if sid == 1:
                task_id = get_eval_states()[0].task_id
                try:
                    await pause_task(task_id)
                    events.setdefault("paused", anyio.Event()).set()
                    with anyio.fail_after(20):
                        # sample 2 completes; its freed slot must not start 3
                        while in_flight() > 1:
                            await anyio.sleep(0.02)
                        await anyio.sleep(0.25)
                    if sorted(started) != [1, 2]:
                        flags["errors"].append(f"starts while paused: {started}")
                    rows = await current_eval_summaries(0.0)
                    flags["row"] = {k: rows[0][k] for k in ("paused", "quiesced")}
                finally:
                    # always resume so a failed assertion can't wedge sample 3
                    flags["resumed"] = True
                    await resume_task(task_id)
            elif sid == 2:
                # hold until the pause has landed, so sample 3's slot can't
                # free before the gate closes
                with anyio.fail_after(20):
                    await events.setdefault("paused", anyio.Event()).wait()
            elif not flags["resumed"]:
                flags["errors"].append("sample 3 dispatched while paused")
            return state

        return solve

    log_dir = str(tmp_path / "logs")
    success, logs = eval_set(
        tasks=[
            Task(
                dataset=[Sample(input=str(i), target="y") for i in range(3)],
                solver=[orchestrator()],
                name="pause_e2e",
            )
        ],
        log_dir=log_dir,
        model="mockllm/model",
        retry_attempts=0,
        max_samples=2,
    )

    assert flags["errors"] == []
    assert success and logs[0].status == "success"
    assert flags["row"] == {"paused": "task", "quiesced": False}
    assert sorted(started) == [1, 2, 3]


# State for the module-registered resumer hook below: `on` gates it to the
# process-pause end-to-end test; `observed` records what the hook saw before
# resuming.
_resumer_state: dict[str, Any] = {"on": False, "observed": None}


@hooks(
    name="pause_test_resumer",
    description="Test-only resumer for the process-pause end-to-end test.",
)
class _ResumerHook(Hooks):
    """Resumes a paused process at the first task's end (on the eval loop)."""

    def enabled(self) -> bool:
        return bool(_resumer_state["on"])

    async def on_task_end(self, data: TaskEnd) -> None:
        from inspect_ai._control.eval_state import get_eval_states

        if _resumer_state["observed"] is None:
            _resumer_state["observed"] = {
                "paused": process_paused(),
                "registered": len(get_eval_states()),
            }
            await resume_process()


def test_eval_process_pause_holds_task_dispatch(tmp_path: Any) -> None:
    """End-to-end process latch: a paused run dispatches no further tasks.

    Two tasks, one at a time: task_alpha's sample pauses the process; at
    alpha's task end the process is still paused and task_beta has not
    registered (the dispatcher's pause filter held it). The task-end hook
    resumes — on the eval's own loop, like a control-server route would —
    and beta then dispatches and completes.
    """
    from inspect_ai import Task
    from inspect_ai._control.eval_state import get_eval_states
    from inspect_ai._eval.evalset import eval_set
    from inspect_ai.dataset import Sample
    from inspect_ai.solver import Generate, TaskState, solver

    _resumer_state["on"] = True
    _resumer_state["observed"] = None
    try:

        @solver(name=f"process_pauser_{id(_resumer_state)}")
        def pauser():
            async def solve(state: TaskState, generate: Generate) -> TaskState:
                if len(get_eval_states()) == 1:  # first task only
                    await pause_process()
                return state

            return solve

        log_dir = str(tmp_path / "logs")
        success, logs = eval_set(
            tasks=[
                Task(
                    dataset=[Sample(input="x", target="y")],
                    solver=[pauser()],
                    name="pause_alpha",
                ),
                Task(
                    dataset=[Sample(input="x", target="y")],
                    solver=[pauser()],
                    name="pause_beta",
                ),
            ],
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            max_tasks=1,
        )
    finally:
        _resumer_state["on"] = False

    assert success and all(log.status == "success" for log in logs)
    # at the first task's end the latch was still closed and beta unregistered
    assert _resumer_state["observed"] == {"paused": True, "registered": 1}
