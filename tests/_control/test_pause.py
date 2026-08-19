"""Tests for the control-channel pause/resume directives (design/ctl/pause-resume.md).

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
    PauseGate,
    PauseGatedSemaphore,
    dispatch_model_name,
    model_paused,
    model_paused_now,
    note_dispatch_models,
    pause_model,
    pause_process,
    pause_task,
    paused_models,
    process_paused,
    process_paused_now,
    reset_process_pause,
    reset_task_pause_gates,
    resume_model,
    resume_process,
    resume_task,
    task_dispatch_paused,
    task_dispatched_count,
    task_held_count,
    task_pause_now_sources,
    task_pause_sources,
    wait_generate_dispatch,
    wake_pause_waiters,
)
from inspect_ai.hooks import Hooks, TaskEnd, hooks
from inspect_ai.model import get_model


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
        self.refusals = 0
        self.http_retries = 0


def _patch_active_samples(
    monkeypatch: pytest.MonkeyPatch, samples: list[_FakeActiveSample]
) -> None:
    monkeypatch.setattr("inspect_ai.log._samples.active_samples", lambda: samples)


class _FakeSample:
    """The slice of ``ActiveSample`` the generate gate reads via ``sample_active``."""

    eval_id = "e1"
    id = "as1"
    interrupt_action: Any = None


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
    assert result["paused"] == ["task"]
    assert result["dispatched"] == 0
    assert task_dispatch_paused("t1")
    assert task_pause_sources("t1") == ["task"]


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
    assert task_pause_sources("t1") == ["process"]
    assert task_dispatch_paused("t1")
    # even one never explicitly paused / registered
    assert task_dispatch_paused("t-other")


async def test_independent_latches_do_not_clear_each_other() -> None:
    register_eval("e1", 5, task_id="t1")
    await pause_task("t1")
    await pause_process()
    assert task_pause_sources("t1") == ["task", "process"]

    # process resume leaves the task-level pause in place
    await resume_process()
    assert task_pause_sources("t1") == ["task"]
    assert task_dispatch_paused("t1")

    # and task resume under the process latch leaves the process pause
    await pause_process()
    result = await resume_task("t1")
    assert result is not None and result["changed"] is True
    assert result["paused"] == ["process"]
    assert task_dispatch_paused("t1")


# ---------------------------------------------------------------------------
# model pause/resume directives
# ---------------------------------------------------------------------------


async def test_pause_model_unknown_is_none() -> None:
    """A typo'd model name fails loudly (404) rather than latching nothing."""
    assert await pause_model("nope/model") is None
    assert await resume_model("nope/model") is None
    register_eval("e1", 5, task_id="t1", model="mockllm/model")
    assert await pause_model("mockllm/mode") is None  # exact match, not prefix


async def test_pause_model_closes_gate() -> None:
    register_eval("e1", 5, task_id="t1", task="my_task", model="mockllm/model")

    result = await pause_model("mockllm/model")
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert result["model"] == "mockllm/model" and result["paused"] is True
    assert result["tasks"] == 1 and result["dispatched"] == 0
    assert model_paused("mockllm/model")
    assert paused_models() == ["mockllm/model"]
    assert task_pause_sources("t1") == ["model"]
    assert task_dispatch_paused("t1")

    repeat = await pause_model("mockllm/model")
    assert repeat is not None
    assert repeat["changed"] is False and "already paused" in repeat["reason"]


async def test_pause_model_dry_run_does_not_flip() -> None:
    register_eval("e1", 5, task_id="t1", model="mockllm/model")

    result = await pause_model("mockllm/model", dry_run=True)
    assert result is not None
    assert result["changed"] is True and result["dry_run"] is True
    assert result["paused"] is False
    assert not model_paused("mockllm/model")


async def test_pause_model_known_via_dispatch_registration() -> None:
    """A model whose tasks haven't started is still addressable.

    A not-yet-started eval-set task has no EvalState — the run dispatcher's
    model registration is what lets the directive validate the name (and is
    the case task-level pause structurally cannot cover).
    """
    note_dispatch_models(["mockllm/pending"])

    result = await pause_model("mockllm/pending")
    assert result is not None and result["changed"] is True
    assert result["tasks"] == 0  # nothing registered yet — held at dispatch
    assert model_paused("mockllm/pending")


async def test_pause_model_only_holds_matching_tasks() -> None:
    """The point of the latch: one model pauses, the rest of the run continues."""
    register_eval("e1", 5, task_id="t1", model="mockllm/model")
    register_eval("e2", 5, task_id="t2", model="mockllm/other")

    await pause_model("mockllm/model")
    assert task_dispatch_paused("t1")
    assert not task_dispatch_paused("t2")
    assert task_pause_sources("t2") == []


async def test_resume_model_reopens_gate() -> None:
    register_eval("e1", 5, task_id="t1", model="mockllm/model")
    await pause_model("mockllm/model")

    result = await resume_model("mockllm/model")
    assert result is not None and result["changed"] is True
    assert result["paused"] is False
    assert not model_paused("mockllm/model")
    assert not task_dispatch_paused("t1")

    repeat = await resume_model("mockllm/model")
    assert repeat is not None
    assert repeat["changed"] is False and "not paused" in repeat["reason"]


async def test_resume_model_dry_run_does_not_flip() -> None:
    register_eval("e1", 5, task_id="t1", model="mockllm/model")
    await pause_model("mockllm/model")

    result = await resume_model("mockllm/model", dry_run=True)
    assert result is not None
    assert result["changed"] is True and result["dry_run"] is True
    assert model_paused("mockllm/model")


async def test_model_latch_independent_of_task_and_process() -> None:
    """All three latches hold and clear independently, in any combination."""
    register_eval("e1", 5, task_id="t1", model="mockllm/model")
    await pause_task("t1")
    await pause_process()
    await pause_model("mockllm/model")
    assert task_pause_sources("t1") == ["task", "process", "model"]

    await resume_process()
    assert task_pause_sources("t1") == ["task", "model"]

    result = await resume_task("t1")
    assert result is not None and result["changed"] is True
    assert result["paused"] == ["model"]  # still held by its model
    assert task_dispatch_paused("t1")

    await resume_model("mockllm/model")
    assert not task_dispatch_paused("t1")


async def test_pause_model_survives_task_retry_attempts() -> None:
    """The gate is model-name keyed, so a retry attempt (fresh eval_id) stays held."""
    register_eval("e1", 2, task_id="t1", model="mockllm/model")
    await pause_model("mockllm/model")
    register_eval("e2", 2, task_id="t1", model="mockllm/model")
    assert task_dispatch_paused("t1")


async def test_reset_clears_model_gates() -> None:
    note_dispatch_models(["mockllm/model"])
    await pause_model("mockllm/model")

    reset_task_pause_gates()
    assert not model_paused("mockllm/model")
    assert paused_models() == []


async def test_dispatch_model_name_survives_rename() -> None:
    """The latch keys on a name snapshot, not the live str(model).

    A provider may rewrite its model name on first use (vLLM resolves a
    ``base:adapter`` LoRA spec to ``base``); because the latch's name is
    consulted at several different times (enqueue, task start, live at each
    scheduler pick), a live read would fragment the latch across the rename.
    """
    model = get_model("mockllm/model", memoize=False)
    name = dispatch_model_name(model)
    assert name == "mockllm/model"
    note_dispatch_models([name])
    await pause_model(name)

    # provider rewrites its model name on first server resolution
    model.api.model_name = "renamed"
    assert str(model) == "mockllm/renamed"

    # every latch surface still keys on the snapshot name
    assert dispatch_model_name(model) == "mockllm/model"
    assert model_paused(dispatch_model_name(model))
    resumed = await resume_model("mockllm/model")
    assert resumed is not None and resumed["changed"] is True

    # the snapshot resets with the gates: a fresh run re-reads str(model)
    reset_task_pause_gates()
    assert dispatch_model_name(model) == "mockllm/renamed"
    # the dispatch-model registration resets too — the name is a run-scoped
    # key, exactly like the task ids
    assert await pause_model("mockllm/model") is None


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


async def test_gated_semaphore_holds_under_model_latch() -> None:
    register_eval("e1", 2, task_id="t1", model="mockllm/model")
    await pause_model("mockllm/model")
    sem = anyio.Semaphore(1)
    gated = PauseGatedSemaphore(sem, task_id="t1", model="mockllm/model")
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
        await resume_model("mockllm/model")
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
# hard pause (`pause --now`): gate strengths and the generate gate
# ---------------------------------------------------------------------------


def test_pause_gate_strength_transitions() -> None:
    """Strength is last-write-wins: --now escalates, plain pause downgrades."""
    gate = PauseGate()
    assert gate.pause() is True
    assert gate.paused and not gate.hard
    assert gate.pause(now=True) is True  # escalate
    assert gate.paused and gate.hard
    assert gate.pause(now=True) is False  # idempotent at strength
    assert gate.pause() is True  # downgrade to soft
    assert gate.paused and not gate.hard
    assert gate.resume() is True
    assert not gate.paused and not gate.hard

    # resume clears both strengths at once
    gate.pause(now=True)
    assert gate.resume() is True
    assert not gate.paused and not gate.hard


async def test_pause_task_now_strength_transitions() -> None:
    register_eval("e1", 5, task_id="t1")

    result = await pause_task("t1", now=True)
    assert result is not None and result["changed"] is True
    assert result["paused"] == ["task"] and result["paused_now"] == ["task"]
    assert task_pause_now_sources("t1") == ["task"]

    repeat = await pause_task("t1", now=True)
    assert repeat is not None
    assert repeat["changed"] is False and "--now" in repeat["reason"]

    downgrade = await pause_task("t1")
    assert downgrade is not None and downgrade["changed"] is True
    assert downgrade["paused"] == ["task"] and downgrade["paused_now"] is None
    assert task_dispatch_paused("t1")

    escalate = await pause_task("t1", now=True)
    assert escalate is not None and escalate["changed"] is True
    assert task_pause_now_sources("t1") == ["task"]

    resumed = await resume_task("t1")
    assert resumed is not None and resumed["changed"] is True
    assert not task_dispatch_paused("t1")
    assert task_pause_now_sources("t1") == []


async def test_pause_process_now_strength_transitions() -> None:
    result = await pause_process(now=True)
    assert result["changed"] is True and result["now"] is True
    assert process_paused() and process_paused_now()

    repeat = await pause_process(now=True)
    assert repeat["changed"] is False and "--now" in repeat["reason"]

    downgrade = await pause_process()
    assert downgrade["changed"] is True and downgrade["now"] is False
    assert process_paused() and not process_paused_now()

    resumed = await resume_process()
    assert resumed["changed"] is True
    assert not process_paused() and not process_paused_now()


async def test_pause_model_now_strength_transitions() -> None:
    register_eval("e1", 5, task_id="t1", model="mockllm/model")

    result = await pause_model("mockllm/model", now=True)
    assert result is not None and result["changed"] is True and result["now"] is True
    assert model_paused_now("mockllm/model")

    repeat = await pause_model("mockllm/model", now=True)
    assert repeat is not None
    assert repeat["changed"] is False and "--now" in repeat["reason"]

    downgrade = await pause_model("mockllm/model")
    assert downgrade is not None and downgrade["changed"] is True
    assert downgrade["now"] is False
    assert model_paused("mockllm/model") and not model_paused_now("mockllm/model")

    resumed = await resume_model("mockllm/model")
    assert resumed is not None and resumed["changed"] is True
    assert not model_paused_now("mockllm/model")


async def test_generate_gate_open_under_soft_pause() -> None:
    """A soft pause never holds generate calls — quiesce semantics only."""
    register_eval("e1", 5, task_id="t1", model="mockllm/model")
    await pause_task("t1")
    await pause_process()
    await pause_model("mockllm/model")
    model = get_model("mockllm/model", memoize=False)
    credits: list[float] = []
    with anyio.fail_after(5):
        await wait_generate_dispatch(model, credits.append)
    assert credits == []


async def test_generate_gate_holds_under_process_hard_pause() -> None:
    """Process `pause --now` parks generate attempts until resume, crediting the hold."""
    await pause_process(now=True)
    model = get_model("mockllm/model", memoize=False)
    credits: list[float] = []
    passed = anyio.Event()

    async def attempt() -> None:
        await wait_generate_dispatch(model, credits.append)
        passed.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(attempt)
        await anyio.sleep(0.1)
        assert not passed.is_set()
        await resume_process()
        with anyio.fail_after(5):
            await passed.wait()
    # the whole hold is credited as waiting time (tail credited on release)
    assert sum(credits) >= 0.05


async def test_generate_gate_downgrade_to_soft_releases() -> None:
    """A plain pause after `pause --now` releases parked generate attempts."""
    await pause_process(now=True)
    model = get_model("mockllm/model", memoize=False)
    passed = anyio.Event()

    async def attempt() -> None:
        await wait_generate_dispatch(model, lambda _: None)
        passed.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(attempt)
        await anyio.sleep(0.05)
        assert not passed.is_set()
        await pause_process()  # downgrade: still paused, no longer hard
        with anyio.fail_after(5):
            await passed.wait()
    assert process_paused()


async def test_generate_gate_task_scope_counts_held_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A task `pause --now` holds the active sample's generates and counts it held."""
    register_eval("e1", 5, task_id="t1", model="mockllm/model")
    await pause_task("t1", now=True)

    monkeypatch.setattr("inspect_ai.log._samples.sample_active", lambda: _FakeSample())
    model = get_model("mockllm/model", memoize=False)
    passed = anyio.Event()

    async def attempt() -> None:
        await wait_generate_dispatch(model, lambda _: None)
        passed.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(attempt)
        await anyio.sleep(0.05)
        assert not passed.is_set()
        assert task_held_count("t1") == 1
        await resume_task("t1")
        with anyio.fail_after(5):
            await passed.wait()
    assert task_held_count("t1") == 0


async def test_generate_gate_model_scope_keys_on_called_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hard model pause holds calls *to that model* — the grader/role case.

    The active sample's task has a different primary model (its task gate is
    open), but its generate call to the hard-paused model parks — deliberately
    unlike the soft model latch's primary-model-only keying.
    """
    register_eval("e1", 5, task_id="t1", model="mockllm/other")
    note_dispatch_models(["mockllm/model"])
    await pause_model("mockllm/model", now=True)

    monkeypatch.setattr("inspect_ai.log._samples.sample_active", lambda: _FakeSample())
    model = get_model("mockllm/model", memoize=False)
    other = get_model("mockllm/other", memoize=False)
    passed = anyio.Event()

    # calls to an un-latched model pass straight through
    with anyio.fail_after(5):
        await wait_generate_dispatch(other, lambda _: None)

    async def attempt() -> None:
        await wait_generate_dispatch(model, lambda _: None)
        passed.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(attempt)
        await anyio.sleep(0.05)
        assert not passed.is_set()
        # held against the *sample's* task even though the latch is model-keyed
        assert task_held_count("t1") == 1
        await resume_model("mockllm/model")
        with anyio.fail_after(5):
            await passed.wait()
    assert task_held_count("t1") == 0


async def test_generate_gate_credits_incrementally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Held time is credited while parked, not only at hold end.

    monitor_working_limit polls every second, so a hold credited only at its
    end would let a working_limit expire mid-hold — the credit loop must
    report progress at the credit interval.
    """
    import inspect_ai._control.pause as pause_module
    from inspect_ai.util._limit import working_limit

    monkeypatch.setattr(pause_module, "_HELD_CREDIT_INTERVAL", 0.02)
    await pause_process(now=True)
    model = get_model("mockllm/model", memoize=False)
    credits: list[float] = []
    passed = anyio.Event()

    async def attempt() -> None:
        with working_limit(60):
            await wait_generate_dispatch(model, credits.append)
        passed.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(attempt)
        await anyio.sleep(0.2)
        # several interval credits landed while still parked
        assert not passed.is_set()
        assert len(credits) >= 2
        assert sum(credits) >= 0.05
        await resume_process()
        with anyio.fail_after(5):
            await passed.wait()


async def test_generate_gate_stamped_interrupt_escapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stamped graceful cancel passes (and releases) the generate gate.

    Cancel escalates over pause: a generate issued after the sample's task
    group exited (a model-graded scorer under a `score` resolution) can't be
    reaped by scope cancellation, so the gate must honor the stamped
    interrupt itself — at entry, and within a tick for an already-parked
    attempt.
    """
    register_eval("e1", 5, task_id="t1", model="mockllm/model")
    await pause_task("t1", now=True)

    sample = _FakeSample()
    monkeypatch.setattr("inspect_ai.log._samples.sample_active", lambda: sample)
    import inspect_ai._control.pause as pause_module

    monkeypatch.setattr(pause_module, "_HELD_CREDIT_INTERVAL", 0.02)
    model = get_model("mockllm/model", memoize=False)

    # already stamped: passes at entry without ever counting as held
    sample.interrupt_action = "score"
    with anyio.fail_after(5):
        await wait_generate_dispatch(model, lambda _: None)
    assert task_held_count("t1") == 0

    # stamped while parked: the tick re-checks the escape and releases
    sample.interrupt_action = None
    passed = anyio.Event()

    async def attempt() -> None:
        await wait_generate_dispatch(model, lambda _: None)
        passed.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(attempt)
        await anyio.sleep(0.05)
        assert not passed.is_set()
        sample.interrupt_action = "score"
        with anyio.fail_after(5):
            await passed.wait()
    assert task_held_count("t1") == 0
    assert task_dispatch_paused("t1")  # the gate itself stays closed


async def test_generate_gate_cancellation_credits_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancel escalating over a hard pause exits the gate cleanly.

    The partial hold is credited and the held count released on the way out.
    """
    register_eval("e1", 5, task_id="t1", model="mockllm/model")
    await pause_task("t1", now=True)

    monkeypatch.setattr("inspect_ai.log._samples.sample_active", lambda: _FakeSample())
    model = get_model("mockllm/model", memoize=False)
    credits: list[float] = []

    async def attempt() -> None:
        await wait_generate_dispatch(model, credits.append)

    async with anyio.create_task_group() as tg:
        tg.start_soon(attempt)
        await anyio.sleep(0.1)
        assert task_held_count("t1") == 1
        tg.cancel_scope.cancel()
    assert task_held_count("t1") == 0
    assert sum(credits) >= 0.05


async def test_compact_gate_holds_under_hard_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`Model.compact()` parks at the hard-pause gate; `count_tokens()` does not.

    Provider-native compaction rewrites conversation state (progress a hold
    must freeze) and can be a long-context sample's most expensive single
    call, so it gates alongside generate rather than slipping past through
    its own entry point. Token counting is non-generative and deliberately
    stays ungated.
    """
    from inspect_ai.model import (
        ChatMessage,
        ChatMessageUser,
        GenerateConfig,
        ModelUsage,
    )
    from inspect_ai.tool import ToolInfo

    await pause_process(now=True)
    model = get_model("mockllm/model", memoize=False)

    async def fake_compact(
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        config: GenerateConfig,
        instructions: str | None,
    ) -> tuple[list[ChatMessage], ModelUsage | None]:
        return messages, None

    async def fake_count_tokens(
        input: str | list[ChatMessage], config: GenerateConfig | None
    ) -> int:
        return 42

    monkeypatch.setattr(model.api, "compact", fake_compact)
    monkeypatch.setattr(model.api, "count_tokens", fake_count_tokens)
    passed = anyio.Event()

    async def attempt() -> None:
        await model.compact([ChatMessageUser(content="hi")], [])
        passed.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(attempt)
        await anyio.sleep(0.1)
        assert not passed.is_set()
        # count_tokens completes while the compact attempt stays parked
        with anyio.fail_after(5):
            assert await model.count_tokens("hi") == 42
        assert not passed.is_set()
        await resume_process()
        with anyio.fail_after(5):
            await passed.wait()


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


async def test_pause_model_flushes_idle_matching_tasks_only() -> None:
    flushes: list[str] = []

    def live(name: str) -> FakeLiveEvalData:
        async def flush() -> int:
            flushes.append(name)
            return 1

        return FakeLiveEvalData(flush=flush)

    register_eval("e1", 5, task_id="t1", model="mockllm/model", live=live("t1"))
    register_eval("e2", 5, task_id="t2", model="mockllm/other", live=live("t2"))

    await pause_model("mockllm/model")
    assert flushes == ["t1"]  # only the latched model's task quiesced


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
        assert body["paused"] == ["task"]
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


async def test_route_task_pause_now() -> None:
    register_eval("e1", 3, task_id="t1", task="my_task")
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/tasks/t1/pause", params={"now": "true"})
        body = response.json()
        assert body["changed"] is True
        assert body["paused"] == ["task"] and body["paused_now"] == ["task"]
        assert body["held"] == 0

        repeat = await client.post("/tasks/t1/pause", params={"now": "true"})
        assert repeat.json()["changed"] is False

        # a plain pause downgrades the hard pause to soft (last-write-wins)
        downgraded = await client.post("/tasks/t1/pause")
        body = downgraded.json()
        assert body["changed"] is True
        assert body["paused"] == ["task"] and body["paused_now"] is None
        assert task_dispatch_paused("t1")

        resumed = await client.post("/tasks/t1/resume")
        assert resumed.json()["changed"] is True
        assert not task_dispatch_paused("t1")


async def test_route_process_pause_now() -> None:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/pause", params={"now": "true"})
        body = response.json()
        assert body["changed"] is True and body["paused"] is True
        assert body["now"] is True
        assert process_paused_now()

        resumed = await client.post("/resume")
        body = resumed.json()
        assert body["changed"] is True and body["now"] is False
        assert not process_paused_now()


async def test_route_model_pause_now() -> None:
    register_eval("e1", 3, task_id="t1", model="mockllm/model")
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/models/pause", params={"model": "mockllm/model", "now": "true"}
        )
        body = response.json()
        assert body["changed"] is True and body["paused"] is True
        assert body["now"] is True
        assert model_paused_now("mockllm/model")

        resumed = await client.post("/models/resume", params={"model": "mockllm/model"})
        assert resumed.json()["changed"] is True
        assert not model_paused_now("mockllm/model")


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


async def test_route_model_pause_resume() -> None:
    register_eval("e1", 3, task_id="t1", task="my_task", model="mockllm/model")
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/models/pause", params={"model": "mockllm/model"})
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True and body["changed"] is True
        assert body["model"] == "mockllm/model" and body["paused"] is True
        assert model_paused("mockllm/model")

        repeat = await client.post("/models/pause", params={"model": "mockllm/model"})
        assert repeat.json()["changed"] is False

        resumed = await client.post("/models/resume", params={"model": "mockllm/model"})
        assert resumed.json()["changed"] is True
        assert not model_paused("mockllm/model")


async def test_route_model_pause_unknown_model_404s_with_error_body() -> None:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/models/pause", params={"model": "nope/model"})
        assert response.status_code == 404
        # handler 404s must carry {"error": ...} (the version-skew convention)
        assert "error" in response.json()
        response = await client.post("/models/resume", params={"model": "nope/model"})
        assert response.status_code == 404
        assert "error" in response.json()


async def test_route_model_pause_requires_model_param() -> None:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ("/models/pause", "/models/resume"):
            response = await client.post(path)
            assert response.status_code == 400
            assert "error" in response.json()


async def test_route_model_pause_dry_run() -> None:
    register_eval("e1", 3, task_id="t1", model="mockllm/model")
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/models/pause", params={"model": "mockllm/model", "dry_run": "true"}
        )
        body = response.json()
        assert body["changed"] is True and body["dry_run"] is True
        assert not model_paused("mockllm/model")


async def test_tasks_listing_reports_model_paused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_eval("e1", 3, task_id="t1", task="my_task", model="mockllm/model")
    _patch_active_samples(monkeypatch, [])
    await pause_model("mockllm/model")
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        rows = (await client.get("/tasks")).json()
        assert rows[0]["paused"] == ["model"]
        assert rows[0]["quiesced"] is True  # paused and nothing in flight
        # the process-level stamp reports the latch even for rows of other
        # models (and, in a real run, before a latched model's tasks register)
        assert rows[0]["paused_models"] == ["mockllm/model"]


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
        assert rows[0]["paused"] == ["task"]
        assert rows[0]["quiesced"] is True  # paused and nothing in flight

        await pause_process()
        rows = (await client.get("/tasks")).json()
        assert rows[0]["paused"] == ["task", "process"]
        assert rows[0]["process_paused"] is True


async def test_tasks_listing_reports_paused_now_and_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_eval("e1", 3, task_id="t1", task="my_task", model="mockllm/model")
    _patch_active_samples(monkeypatch, [])
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        rows = (await client.get("/tasks")).json()
        assert rows[0]["paused_now"] is None
        assert rows[0]["held"] == 0
        assert rows[0]["process_paused_now"] is False

        await pause_task("t1", now=True)
        rows = (await client.get("/tasks")).json()
        assert rows[0]["paused"] == ["task"]
        assert rows[0]["paused_now"] == ["task"]

        await pause_process()  # soft — only the task latch is hard
        rows = (await client.get("/tasks")).json()
        assert rows[0]["paused"] == ["task", "process"]
        assert rows[0]["paused_now"] == ["task"]
        assert rows[0]["process_paused_now"] is False


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
            assert rows[0]["paused"] == ["task"]
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
            assert rows[0]["paused"] == ["task"]
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
        assert rows[0]["paused"] == ["task"]
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
        register_eval("e1", 1, task_id="t1", model="mockllm/model")
        await pause_task("t1")
        await resume_task("t1")
        assert fired

        fired.clear()
        await pause_process()
        await resume_process()
        assert fired

        fired.clear()
        await pause_model("mockllm/model")
        await resume_model("mockllm/model")
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
    assert flags["row"] == {"paused": ["task"], "quiesced": False}
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


# State for the module-registered model-resumer hook below: `on` gates it to
# the model-pause end-to-end test; `observed` records what the hook saw
# before resuming.
_model_resumer_state: dict[str, Any] = {"on": False, "observed": None}


@hooks(
    name="pause_test_model_resumer",
    description="Test-only resumer for the model-pause end-to-end test.",
)
class _ModelResumerHook(Hooks):
    """Resumes paused models at the first task's end (on the eval loop)."""

    def enabled(self) -> bool:
        return bool(_model_resumer_state["on"])

    async def on_task_end(self, data: TaskEnd) -> None:
        from inspect_ai._control.eval_state import get_eval_states
        from inspect_ai._control.pause import paused_models

        if _model_resumer_state["observed"] is None:
            _model_resumer_state["observed"] = {
                "models_paused": paused_models(),
                "registered": len(get_eval_states()),
            }
            for model in paused_models():
                await resume_model(model)


def test_eval_model_pause_holds_undispatched_tasks_of_that_model(
    tmp_path: Any,
) -> None:
    """End-to-end model latch: a latched model's unstarted task doesn't dispatch.

    One task definition fanned across two models, one unit at a time (both
    units share a sequence group, so a single dispatcher call schedules
    them): whichever unit runs first pauses the *other* unit's model; at the
    first unit's end that model is still latched and its unit has not
    registered — the scheduler's pause filter held it, the case task-level
    pause structurally cannot reach (the unstarted unit isn't addressable).
    Without a resume the dispatcher would park forever; the task-end hook
    resumes the model — on the eval's own loop, like a control-server route
    would — and the held unit then dispatches and completes.
    """
    from inspect_ai import Task
    from inspect_ai._control.eval_state import get_eval_states
    from inspect_ai._eval.evalset import eval_set
    from inspect_ai.dataset import Sample
    from inspect_ai.solver import Generate, TaskState, solver

    models = ["mockllm/model_a", "mockllm/model_b"]
    _model_resumer_state["on"] = True
    _model_resumer_state["observed"] = None
    try:

        @solver(name=f"model_pauser_{id(_model_resumer_state)}")
        def pauser():
            async def solve(state: TaskState, generate: Generate) -> TaskState:
                states = get_eval_states()
                if len(states) == 1:  # first unit only (dispatch order varies)
                    other = next(m for m in models if m != states[0].model)
                    result = await pause_model(other)
                    assert result is not None and result["changed"] is True
                return state

            return solve

        log_dir = str(tmp_path / "logs")
        success, logs = eval_set(
            tasks=[
                Task(
                    dataset=[Sample(input="x", target="y")],
                    solver=[pauser()],
                    name="model_pause_e2e",
                )
            ],
            log_dir=log_dir,
            model=models,
            retry_attempts=0,
            max_tasks=1,
        )
    finally:
        _model_resumer_state["on"] = False

    assert success and all(log.status == "success" for log in logs)
    # at the first unit's end the other unit's model was still latched and
    # that unit unregistered (the dispatcher's model-pause filter held it)
    observed = _model_resumer_state["observed"]
    assert observed is not None
    assert observed["registered"] == 1
    assert len(observed["models_paused"]) == 1
    assert observed["models_paused"][0] in models


def test_eval_hard_pause_holds_generate_until_resume(tmp_path: Any) -> None:
    """End-to-end hard pause through a real eval and a real generate call.

    The sample hard-pauses its own task, then calls generate: the call must
    park at the generate gate (observed via the held count) rather than
    reaching the model, and proceed once a concurrent resumer — standing in
    for a control-server route on the eval's loop — resumes the task. The
    held span must be credited to the sample's waiting time so working_limit
    enforcement (and the reported working time) exclude it.
    """
    from inspect_ai import Task
    from inspect_ai._control.eval_state import get_eval_states
    from inspect_ai._eval.evalset import eval_set
    from inspect_ai._util.working import sample_waiting_time
    from inspect_ai.dataset import Sample
    from inspect_ai.solver import Generate, TaskState, solver

    observed: dict[str, Any] = {"held": 0, "waiting": 0.0}

    @solver(name=f"hard_pauser_{id(observed)}")
    def hard_pauser():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            task_id = get_eval_states()[0].task_id
            await pause_task(task_id, now=True)

            async def resume_when_held() -> None:
                with anyio.fail_after(20):
                    while task_held_count(task_id) == 0:
                        await anyio.sleep(0.01)
                    observed["held"] = task_held_count(task_id)
                    await anyio.sleep(0.2)  # keep it held long enough to credit
                    await resume_task(task_id)

            waiting_before = sample_waiting_time()
            async with anyio.create_task_group() as tg:
                tg.start_soon(resume_when_held)
                state = await generate(state)
            observed["waiting"] = sample_waiting_time() - waiting_before
            return state

        return solve

    log_dir = str(tmp_path / "logs")
    success, logs = eval_set(
        tasks=[
            Task(
                dataset=[Sample(input="x", target="y")],
                solver=[hard_pauser()],
                name="hard_pause_e2e",
            )
        ],
        log_dir=log_dir,
        model="mockllm/model",
        retry_attempts=0,
    )

    assert success and logs[0].status == "success"
    # the generate call was genuinely held (and counted) at the gate
    assert observed["held"] == 1
    # the held span was credited as waiting time (~0.2s hold, loose bound)
    assert observed["waiting"] >= 0.1


def test_eval_hard_pause_time_limit_reap_reparks_grader(tmp_path: Any) -> None:
    """`time_limit` keeps running while held — and the grader re-parks after the reap.

    Pins the documented wall-clock interaction (design/ctl/pause-resume.md):
    a sample held at the generate gate past its `time_limit` is reaped as an
    ordinary time-limit outcome, and a model-graded scorer's grader call then
    re-parks at the still-closed gate, so the sample fully completes only on
    resume.
    """
    from inspect_ai import Task
    from inspect_ai._control.eval_state import get_eval_states
    from inspect_ai._eval.evalset import eval_set
    from inspect_ai.dataset import Sample
    from inspect_ai.log import read_eval_log
    from inspect_ai.scorer import Score, Target, mean, scorer
    from inspect_ai.solver import Generate, TaskState, solver

    observed: dict[str, Any] = {"solver_completed": False, "held_at_grade": 0}

    @solver(name=f"held_past_limit_{id(observed)}")
    def held_past_limit():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            task_id = get_eval_states()[0].task_id
            await pause_task(task_id, now=True)
            # parks at the generate gate; the time limit reaps it there
            state = await generate(state)
            observed["solver_completed"] = True
            return state

        return solve

    @scorer(metrics=[mean()], name=f"parking_grader_{id(observed)}")
    def parking_grader():
        async def score(state: TaskState, target: Target) -> Score:
            task_id = get_eval_states()[0].task_id

            async def resume_when_held() -> None:
                with anyio.fail_after(20):
                    while task_held_count(task_id) == 0:
                        await anyio.sleep(0.01)
                    observed["held_at_grade"] = task_held_count(task_id)
                    await resume_task(task_id)

            async with anyio.create_task_group() as tg:
                tg.start_soon(resume_when_held)
                await get_model().generate("grade this")
            return Score(value=1.0)

        return score

    log_dir = str(tmp_path / "logs")
    success, logs = eval_set(
        tasks=[
            Task(
                dataset=[Sample(input="x", target="y")],
                solver=[held_past_limit()],
                scorer=parking_grader(),
                # scoring runs under time_limit / 2, so the grader's
                # park-detect-resume-generate must fit in that window — 4s
                # gives it 2s of headroom against slow CI
                time_limit=4,
                name="hard_pause_time_limit_e2e",
            )
        ],
        log_dir=log_dir,
        model="mockllm/model",
        retry_attempts=0,
    )

    assert success and logs[0].status == "success"
    # the solver's generate never completed: the time limit reaped it mid-hold
    assert not observed["solver_completed"]
    # the grader call re-parked at the still-closed gate until resumed
    assert observed["held_at_grade"] == 1
    # the sample resolved as an ordinary time-limit outcome
    log = read_eval_log(logs[0].location)
    assert log.samples is not None
    assert log.samples[0].limit is not None
    assert log.samples[0].limit.type == "time"
