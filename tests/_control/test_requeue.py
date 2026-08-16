"""Tests for the control-channel sample-requeue directive (phase 3).

Covers the resolver (``inspect_ai._control.requeue.requeue_sample`` — the
decision table in ``design/ctl/sample-requeue.md``), the ``SampleScheduler`` /
``SampleRequeue`` runner machinery (``inspect_ai._eval.task.scheduler``),
the server route (``POST /evals/<id>/sample/requeue``), the samples-listing
rendering of a pending requeue, and an end-to-end requeue through a live
eval.
"""

from typing import Any, cast

import anyio
import httpx
import pytest
from test_helpers.live_eval_data import FakeLiveEvalData

from inspect_ai import SampleSource, Task, enqueue_sample, eval_async
from inspect_ai._control.cancel import cancel_sample
from inspect_ai._control.eval_state import (
    clear_all_eval_states,
    detach_eval_live,
    get_eval_state,
    get_eval_states,
    mark_eval_retry_pending,
    record_sample_errored,
    record_sample_requeued,
    register_eval,
    set_sample_requeue,
)
from inspect_ai._control.requeue import requeue_sample
from inspect_ai._control.state import (
    _full_sample,
    current_sample_listing,
    find_active_sample,
    sample_error_detail,
)
from inspect_ai._display.core.display import TaskCancel
from inspect_ai._eval.task.error import SampleErrorHandler
from inspect_ai._eval.task.scheduler import (
    SampleRequeue,
    SampleScheduler,
    _ScheduledRun,
)
from inspect_ai._util._async import Wake
from inspect_ai._util.error import EvalError, is_cancellation_message
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog, read_eval_log_async
from inspect_ai.log._log import EvalSample, EvalSampleSummary
from inspect_ai.scorer import CORRECT, Score, Target, accuracy, scorer
from inspect_ai.solver import Generate, TaskState, solver
from inspect_ai.util._display import init_display_type


@pytest.fixture(autouse=True)
def _clear_states():
    clear_all_eval_states()
    yield
    clear_all_eval_states()


def _error(message: str = "boom") -> EvalError:
    return EvalError(message=message, traceback="", traceback_ansi="")


def _errored_sample(
    sample_id: str = "s1", epoch: int = 1, message: str = "boom"
) -> EvalSample:
    return EvalSample(
        id=sample_id, epoch=epoch, input="q", target="a", error=_error(message)
    )


def _cancelled_sample(sample_id: str = "s1", epoch: int = 1) -> EvalSample:
    return EvalSample(
        id=sample_id,
        epoch=epoch,
        input="q",
        target="a",
        error=_error("CancelledError('cancelled via cancel scope')"),
    )


def _live_reading(sample: EvalSample | None) -> FakeLiveEvalData:
    async def _read(
        id: str | int, epoch: int, *, exclude_fields: set[str] | None = None
    ) -> EvalSample | None:
        if sample is not None and str(sample.id) == str(id) and sample.epoch == epoch:
            return sample
        return None

    return FakeLiveEvalData(sample=_read)


class _FakeRequeueHandle:
    """The slice of ``SampleRequeue`` the resolver touches."""

    def __init__(
        self,
        *,
        open: bool = True,
        pending: set[tuple[str, int]] | None = None,
        accept_outcome: str = "accepted",
        checkpoint: bool = False,
    ) -> None:
        self.open = open
        self._pending = pending or set()
        self.accept_outcome = accept_outcome
        self.accepts: list[tuple[EvalSample, str]] = []
        self._checkpoint = checkpoint

    def is_pending(self, sample_id: str, epoch: int) -> bool:
        return (sample_id, epoch) in self._pending

    def pending_keys(self) -> frozenset[tuple[str, int]]:
        return frozenset(self._pending)

    async def checkpoint_available(self, sample_id: str | int, epoch: int) -> bool:
        return self._checkpoint

    def accept(self, prior: EvalSample, prior_status: str) -> str:
        self.accepts.append((prior, prior_status))
        return self.accept_outcome


def _register_requeueable(
    *,
    eval_id: str = "e1",
    total: int = 2,
    prior: EvalSample | None = None,
    handle: _FakeRequeueHandle | None = None,
    sample_ids: list[str | int] | None = None,
    epochs: int = 1,
    task_cancel: TaskCancel | None = None,
) -> _FakeRequeueHandle:
    handle = handle if handle is not None else _FakeRequeueHandle()
    register_eval(
        eval_id,
        total,
        task_id="t1",
        task="my_task",
        live=_live_reading(prior),
        sample_ids=sample_ids if sample_ids is not None else ["s1", "s2"],
        epochs=epochs,
        task_cancel=task_cancel,
    )
    set_sample_requeue(eval_id, cast(SampleRequeue, handle))
    return handle


def _patch_active_samples(monkeypatch: pytest.MonkeyPatch, samples: list[Any]) -> None:
    monkeypatch.setattr("inspect_ai.log._samples.active_samples", lambda: samples)


class _FakeActiveSample:
    """The slice of ``ActiveSample`` the requeue resolver touches."""

    class _Sample:
        def __init__(self, id: str | int) -> None:
            self.id = id

    def __init__(
        self,
        *,
        eval_id: str = "e1",
        sample_id: str | int = "s1",
        epoch: int = 1,
        started: float | None = 1.0,
        completed: float | None = None,
    ) -> None:
        self.eval_id = eval_id
        self.sample = self._Sample(sample_id)
        self.epoch = epoch
        self.started = started
        self.completed = completed


# ---------------------------------------------------------------------------
# requeue_sample directive (the decision table)
# ---------------------------------------------------------------------------


async def test_requeue_unknown_eval_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_active_samples(monkeypatch, [])
    assert await requeue_sample("nope", "s1", 1) is None


async def test_requeue_errored_sample_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_samples(monkeypatch, [])
    prior = _errored_sample()
    handle = _register_requeueable(prior=prior)

    result = await requeue_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert result["status"] == "error"
    assert result["prior_error"] == "boom"
    assert result["attempt"] == 2
    assert handle.accepts == [(prior, "error")]


async def test_requeue_cancelled_sample_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_samples(monkeypatch, [])
    prior = _cancelled_sample()
    handle = _register_requeueable(prior=prior)

    result = await requeue_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is True
    assert result["changed"] is True and result["status"] == "cancelled"
    # a cancellation is not a genuine error, so it doesn't grow the attempt
    # count (the seeding skips it) — the re-run is still attempt 1's redo
    assert result["attempt"] == 1
    assert handle.accepts == [(prior, "cancelled")]


async def test_requeue_completed_sample_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_samples(monkeypatch, [])
    prior = EvalSample(id="s1", epoch=1, input="q", target="a")
    handle = _register_requeueable(prior=prior)

    result = await requeue_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is False and "completed successfully" in result["error"]
    assert handle.accepts == []

    # the rejection reports under dry_run too, so an agent can probe safely
    dry = await requeue_sample("e1", "s1", 1, dry_run=True)
    assert dry is not None and dry["ok"] is False


async def test_requeue_running_sample_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_samples(monkeypatch, [_FakeActiveSample()])
    handle = _register_requeueable()

    result = await requeue_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is True
    assert result["changed"] is False and result["status"] == "running"
    assert handle.accepts == []


async def test_requeue_queued_sample_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_active_samples(monkeypatch, [_FakeActiveSample(started=None)])
    handle = _register_requeueable()

    result = await requeue_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is True
    assert result["changed"] is False and result["status"] == "queued"
    assert handle.accepts == []


async def test_requeue_never_started_sample_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_samples(monkeypatch, [])
    handle = _register_requeueable()  # no readable record for s2

    result = await requeue_sample("e1", "s2", 1)
    assert result is not None
    assert result["ok"] is True
    assert result["changed"] is False and result["status"] == "pending"
    assert handle.accepts == []


async def test_requeue_unknown_sample_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_samples(monkeypatch, [])
    _register_requeueable()

    # unknown id, and a known id at an out-of-range epoch, are both 404s
    assert await requeue_sample("e1", "nope", 1) is None
    assert await requeue_sample("e1", "s1", 3) is None


async def test_requeue_pending_requeue_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_samples(monkeypatch, [])
    handle = _register_requeueable(
        prior=_errored_sample(), handle=_FakeRequeueHandle(pending={("s1", 1)})
    )

    result = await requeue_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is True
    assert result["changed"] is False and result["status"] == "queued"
    assert "already pending" in result["reason"]
    assert handle.accepts == []


async def test_requeue_running_rerun_reports_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A repeat requeue while the re-run is live reports its true status.

    The pending key stays set until the re-run goes terminal, so the
    active-sample row must win over it — otherwise a running re-run would
    read `queued`.
    """
    _patch_active_samples(monkeypatch, [_FakeActiveSample()])
    handle = _register_requeueable(handle=_FakeRequeueHandle(pending={("s1", 1)}))

    result = await requeue_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is True
    assert result["changed"] is False and result["status"] == "running"
    assert handle.accepts == []


async def test_requeue_finished_task_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_samples(monkeypatch, [])
    _register_requeueable(total=1, prior=_errored_sample())
    record_sample_errored("e1")  # terminal == total → finished

    result = await requeue_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is False and "eval-retry" in result["error"]


async def test_requeue_between_attempts_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_samples(monkeypatch, [])
    _register_requeueable(total=1, prior=_errored_sample())
    record_sample_errored("e1")
    mark_eval_retry_pending("e1")

    result = await requeue_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is False and "between attempts" in result["error"]


async def test_requeue_task_cancel_in_flight_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_samples(monkeypatch, [])
    cancel = TaskCancel(can_retry=False, cancel_task=lambda _: None)
    cancel.cancel_type = "abort"
    _register_requeueable(prior=_errored_sample(), task_cancel=cancel)

    result = await requeue_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is False and "cancel is in flight" in result["error"]


async def test_requeue_drained_fanout_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_samples(monkeypatch, [])
    _register_requeueable(
        prior=_errored_sample(), handle=_FakeRequeueHandle(open=False)
    )

    result = await requeue_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is False and "no longer accepting" in result["error"]


async def test_requeue_without_handle_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_samples(monkeypatch, [])
    register_eval("e1", 2, task_id="t1", live=_live_reading(_errored_sample()))

    result = await requeue_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is False and "no longer accepting" in result["error"]


async def test_requeue_dry_run_does_not_accept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_samples(monkeypatch, [])
    handle = _register_requeueable(
        prior=_errored_sample(), handle=_FakeRequeueHandle(checkpoint=True)
    )

    result = await requeue_sample("e1", "s1", 1, dry_run=True)
    assert result is not None
    assert result["ok"] is True
    assert result["changed"] is True and result["dry_run"] is True
    assert result["resume_from_checkpoint"] is True
    assert handle.accepts == []


async def test_requeue_accept_race_lands_on_pending_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two directives racing past the resolver's reads can't double-queue.

    The pending set is re-checked synchronously inside ``accept`` — the
    resolver maps its ``already_pending`` outcome to the same clean no-op.
    """
    _patch_active_samples(monkeypatch, [])
    _register_requeueable(
        prior=_errored_sample(),
        handle=_FakeRequeueHandle(accept_outcome="already_pending"),
    )

    result = await requeue_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is True
    assert result["changed"] is False and "already pending" in result["reason"]


async def test_requeue_stale_prior_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``accept``'s stale outcome maps to a rejection, not an accept.

    A directive whose reads straddled a full accept → re-run → terminal
    cycle holds a prior record that was already requeued — re-running it
    would target a possibly-completed sample.
    """
    _patch_active_samples(monkeypatch, [])
    _register_requeueable(
        prior=_errored_sample(),
        handle=_FakeRequeueHandle(accept_outcome="stale"),
    )

    result = await requeue_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is False and "re-issue the requeue" in result["error"]


async def test_requeue_finished_during_resolver_reads_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The task-level gates are re-checked synchronously before accept.

    The resolver awaits between its first task-level pass and the accept;
    if the last sibling's terminal recording stamps ``completed_at`` during
    those awaits, the requeue must reject rather than start a re-run inside
    an eval that already reads finished.
    """
    import inspect_ai._control.state as control_state

    _patch_active_samples(monkeypatch, [])
    handle = _register_requeueable(total=1, prior=_errored_sample())

    orig_full_sample = control_state._full_sample

    async def finish_then_read(*args: Any, **kwargs: Any) -> Any:
        record_sample_errored("e1")  # terminal == total → completed_at stamped
        return await orig_full_sample(*args, **kwargs)

    monkeypatch.setattr(control_state, "_full_sample", finish_then_read)

    result = await requeue_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is False and "eval-retry" in result["error"]
    assert handle.accepts == []


async def test_requeue_detached_on_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """A retry detaches the attempt-scoped handle alongside ``live``."""
    _patch_active_samples(monkeypatch, [])
    _register_requeueable(prior=_errored_sample())
    detach_eval_live("e1")
    state = get_eval_state("e1")
    assert state is not None and state.sample_requeue is None


def test_record_sample_requeued_decrements_buckets() -> None:
    register_eval("e1", 3, task_id="t1")
    record_sample_errored("e1")
    record_sample_requeued("e1", "error")
    state = get_eval_state("e1")
    assert state is not None and state.errored == 0

    state.cancelled = 1
    record_sample_requeued("e1", "cancelled")
    assert state.cancelled == 0

    record_sample_requeued("nope", "error")  # must not raise


def test_record_sample_requeued_never_goes_negative() -> None:
    """A classification/bucket divergence warns instead of corrupting counters."""
    register_eval("e1", 3, task_id="t1")
    record_sample_errored("e1")
    # prior counted as errored but (wrongly) classified cancelled: the
    # cancelled bucket is 0 and must stay 0
    record_sample_requeued("e1", "cancelled")
    state = get_eval_state("e1")
    assert state is not None
    assert state.cancelled == 0
    assert state.errored == 1


# ---------------------------------------------------------------------------
# SampleScheduler / SampleRequeue (runner machinery)
# ---------------------------------------------------------------------------


async def test_scheduler_runs_plan_keyed() -> None:
    scheduler = SampleScheduler()

    async def run_sample(
        sample_index: int, epoch: int, prior: EvalSample | None
    ) -> str:
        return f"{sample_index}:{epoch}"

    results = await scheduler.run([(0, 1), (1, 1), (0, 2)], run_sample)
    assert results == {(0, 1): "0:1", (1, 1): "1:1", (0, 2): "0:2"}
    assert not scheduler.open


async def test_scheduler_returns_results_in_plan_order() -> None:
    """Results come back in plan order, not completion order.

    Epoch reducers (`mode` tie-breaks by first occurrence) and the logged
    reductions depend on the deterministic order `tg_collect` returned.
    """
    scheduler = SampleScheduler()
    second_done = anyio.Event()

    async def run_sample(
        sample_index: int, epoch: int, prior: EvalSample | None
    ) -> str:
        if epoch == 1:
            with anyio.fail_after(30):
                await second_done.wait()
        else:
            second_done.set()
        return f"{sample_index}:{epoch}"

    plan = [(0, 1), (0, 2)]
    results = await scheduler.run(plan, run_sample)
    assert list(results.keys()) == plan


async def test_scheduler_rejects_requeue_after_drain() -> None:
    scheduler = SampleScheduler()

    async def run_sample(
        sample_index: int, epoch: int, prior: EvalSample | None
    ) -> str:
        return "done"

    await scheduler.run([(0, 1)], run_sample)
    accepted = scheduler.requeue(
        _ScheduledRun(
            sample_index=0, epoch=1, prior=_errored_sample(), on_terminal=lambda: None
        )
    )
    assert accepted is False


async def test_scheduler_rerun_replaces_result_and_closes() -> None:
    scheduler = SampleScheduler()
    flaky_done = anyio.Event()
    release_waiter = anyio.Event()
    rerun_priors: list[EvalSample | None] = []

    async def run_sample(
        sample_index: int, epoch: int, prior: EvalSample | None
    ) -> str:
        if sample_index == 0:
            if prior is not None:
                rerun_priors.append(prior)
                return "fresh"
            flaky_done.set()
            return "failed"
        with anyio.fail_after(30):
            await release_waiter.wait()
        return "waited"

    prior = _errored_sample()
    results: dict[tuple[int, int], str] = {}

    async with anyio.create_task_group() as tg:

        async def go() -> None:
            results.update(await scheduler.run([(0, 1), (1, 1)], run_sample))

        tg.start_soon(go)
        with anyio.fail_after(30):
            await flaky_done.wait()
        assert scheduler.open  # the waiter keeps the fanout open
        terminal: list[bool] = []
        accepted = scheduler.requeue(
            _ScheduledRun(
                sample_index=0,
                epoch=1,
                prior=prior,
                on_terminal=lambda: terminal.append(True),
            )
        )
        assert accepted is True
        # wait for the re-run to land, then release the waiter
        with anyio.fail_after(30):
            while not terminal:
                await anyio.sleep(0.01)
        release_waiter.set()

    assert results == {(0, 1): "fresh", (1, 1): "waited"}
    assert rerun_priors == [prior]
    assert not scheduler.open


async def test_scheduler_teardown_drains_undispatched_reruns() -> None:
    """A teardown with an undispatched re-run still fires its terminal callback.

    Otherwise the pending-requeue key would outlive the task, rendering the
    sample `queued` on a finished eval.
    """
    scheduler = SampleScheduler()
    terminal: list[bool] = []

    async def run_sample(
        sample_index: int, epoch: int, prior: EvalSample | None
    ) -> str:
        if prior is not None:
            return "fresh"
        # accept a re-run, then fail the task: the group tears down before
        # the dispatcher (parked at its wake, cancelled with it) can start
        # the re-run
        accepted = scheduler.requeue(
            _ScheduledRun(
                sample_index=0,
                epoch=1,
                prior=_errored_sample(),
                on_terminal=lambda: terminal.append(True),
            )
        )
        assert accepted is True
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await scheduler.run([(0, 1)], run_sample)

    assert terminal == [True]
    assert not scheduler.open


async def test_scheduler_feeder_adds_entries_in_plan_order() -> None:
    """Entries a feeder adds run and extend the plan-ordered results."""
    scheduler = SampleScheduler()

    async def run_sample(
        sample_index: int, epoch: int, prior: EvalSample | None
    ) -> str:
        return f"{sample_index}:{epoch}"

    async def feeder() -> None:
        scheduler.add([(1, 1), (2, 1)])

    results = await scheduler.run([(0, 1)], run_sample, feeder=feeder)
    assert list(results.items()) == [
        ((0, 1), "0:1"),
        ((1, 1), "1:1"),
        ((2, 1), "2:1"),
    ]
    assert not scheduler.open


async def test_scheduler_feeder_holds_fanout_open_for_requeue() -> None:
    """An idle fanout held open by a live feeder still accepts a requeue.

    The dynamic path's feeder blocks in ``next_samples()`` with nothing
    outstanding; a requeue arriving then must be accepted and start
    immediately (the dispatcher isn't blocked on the source).
    """
    scheduler = SampleScheduler()
    feeder_wake = Wake()
    feeder_idle = anyio.Event()
    feeder_release = anyio.Event()
    terminal: list[bool] = []

    async def run_sample(
        sample_index: int, epoch: int, prior: EvalSample | None
    ) -> str:
        return "fresh" if prior is not None else "seed"

    async def feeder() -> None:
        while scheduler.outstanding > 0:
            await feeder_wake.wait()
        # idle but held open, like a blocking next_samples()
        feeder_idle.set()
        with anyio.fail_after(30):
            await feeder_release.wait()

    results: dict[tuple[int, int], str] = {}

    async with anyio.create_task_group() as tg:

        async def go() -> None:
            results.update(
                await scheduler.run(
                    [(0, 1)], run_sample, feeder=feeder, on_settle=feeder_wake.set
                )
            )

        tg.start_soon(go)
        with anyio.fail_after(30):
            await feeder_idle.wait()
        assert scheduler.outstanding == 0
        assert scheduler.open  # the feeder hold alone keeps it open
        accepted = scheduler.requeue(
            _ScheduledRun(
                sample_index=0,
                epoch=1,
                prior=_errored_sample(),
                on_terminal=lambda: terminal.append(True),
            )
        )
        assert accepted is True
        # the re-run starts and finishes while the feeder is still parked
        with anyio.fail_after(30):
            while not terminal:
                await anyio.sleep(0.01)
        feeder_release.set()

    assert results == {(0, 1): "fresh"}
    assert not scheduler.open


async def test_scheduler_feeder_exception_fails_run() -> None:
    """A feeder failure (duplicate id, sandbox startup) tears the run down."""
    scheduler = SampleScheduler()

    async def run_sample(
        sample_index: int, epoch: int, prior: EvalSample | None
    ) -> str:
        return "ok"

    async def feeder() -> None:
        raise RuntimeError("source boom")

    with pytest.raises(RuntimeError, match="source boom"):
        await scheduler.run([(0, 1)], run_sample, feeder=feeder)
    assert not scheduler.open


async def test_sample_requeue_accept_reconciles_counters() -> None:
    register_eval("e1", 2, task_id="t1")
    record_sample_errored("e1")
    handler = SampleErrorHandler(False, 2)
    handler.error_count = 1

    scheduler = SampleScheduler()
    accepted_keys: list[tuple[str | int, int]] = []
    handle = SampleRequeue(
        eval_id="e1",
        scheduler=scheduler,
        sample_error=handler,
        sample_indexes={"s1": 0, "s2": 1},
        checkpoints_dir=None,
        on_accept=lambda sample_id, epoch: accepted_keys.append((sample_id, epoch)),
    )
    prior = _errored_sample()

    flaky_done = anyio.Event()
    release_waiter = anyio.Event()

    async def run_sample(
        sample_index: int, epoch: int, prior_arg: EvalSample | None
    ) -> str:
        if sample_index == 0 and prior_arg is None:
            flaky_done.set()
            return "failed"
        if sample_index == 0:
            return "fresh"
        with anyio.fail_after(30):
            await release_waiter.wait()
        return "waited"

    async with anyio.create_task_group() as tg:
        results: dict[tuple[int, int], str] = {}

        async def go() -> None:
            results.update(await scheduler.run([(0, 1), (1, 1)], run_sample))

        tg.start_soon(go)
        with anyio.fail_after(30):
            await flaky_done.wait()

        assert handle.accept(prior, "error") == "accepted"
        assert handle.is_pending("s1", 1)
        assert handle.pending_keys() == frozenset({("s1", 1)})
        # the double-queue guard fires synchronously inside accept
        assert handle.accept(prior, "error") == "already_pending"

        state = get_eval_state("e1")
        assert state is not None and state.errored == 0
        assert handler.error_count == 0
        # on_accept fired once, with the prior's key (the runner uses it to
        # retract the superseded progress tick and score)
        assert accepted_keys == [("s1", 1)]

        # the pending key clears when the re-run reaches a terminal outcome
        with anyio.fail_after(30):
            while handle.is_pending("s1", 1):
                await anyio.sleep(0.01)
        release_waiter.set()

    assert results[(0, 1)] == "fresh"


async def test_sample_requeue_accept_stale_prior_refused() -> None:
    """A prior record already requeued once is refused after its re-run ends.

    The pending key clears at the re-run's terminal outcome, so a directive
    whose reads straddled the whole accept → re-run → terminal cycle would
    otherwise get its stale errored ``prior`` accepted — re-running a
    now-completed sample and double-decrementing the counters. A re-read of
    the re-run's own terminal record (fresh uuid) still passes.
    """
    register_eval("e1", 2, task_id="t1")
    record_sample_errored("e1")
    handler = SampleErrorHandler(False, 2)
    handler.error_count = 1

    scheduler = SampleScheduler()
    handle = SampleRequeue(
        eval_id="e1",
        scheduler=scheduler,
        sample_error=handler,
        sample_indexes={"s1": 0, "s2": 1},
        checkpoints_dir=None,
        on_accept=lambda sample_id, epoch: None,
    )
    prior = EvalSample(
        id="s1", epoch=1, input="q", target="a", error=_error(), uuid="prior-attempt"
    )

    release_waiter = anyio.Event()

    async def run_sample(
        sample_index: int, epoch: int, prior_arg: EvalSample | None
    ) -> str:
        if sample_index == 0:
            return "fresh" if prior_arg is not None else "failed"
        with anyio.fail_after(30):
            await release_waiter.wait()
        return "waited"

    async with anyio.create_task_group() as tg:

        async def go() -> None:
            await scheduler.run([(0, 1), (1, 1)], run_sample)

        tg.start_soon(go)
        with anyio.fail_after(30):
            while not scheduler.open:
                await anyio.sleep(0.01)

        assert handle.accept(prior, "error") == "accepted"
        # wait for the re-run to reach its terminal outcome
        with anyio.fail_after(30):
            while handle.is_pending("s1", 1):
                await anyio.sleep(0.01)

        # the same record again is stale — and reconciles nothing
        assert handle.accept(prior, "error") == "stale"
        state = get_eval_state("e1")
        assert state is not None and state.errored == 0
        assert handler.error_count == 0

        # a genuine re-requeue after a second failure carries a fresh uuid
        second_failure = EvalSample(
            id="s1",
            epoch=1,
            input="q",
            target="a",
            error=_error(),
            uuid="rerun-attempt",
        )
        assert handle.accept(second_failure, "error") == "accepted"

        release_waiter.set()


async def test_sample_requeue_accept_unknown_sample() -> None:
    register_eval("e1", 1, task_id="t1")
    handle = SampleRequeue(
        eval_id="e1",
        scheduler=SampleScheduler(),
        sample_error=SampleErrorHandler(False, 1),
        sample_indexes={"s1": 0},
        checkpoints_dir=None,
        on_accept=lambda sample_id, epoch: None,
    )
    assert handle.accept(_errored_sample("not-planned"), "error") == "unknown"


async def test_sample_requeue_accept_closed_scheduler() -> None:
    register_eval("e1", 1, task_id="t1")
    record_sample_errored("e1")
    handle = SampleRequeue(
        eval_id="e1",
        scheduler=SampleScheduler(),  # never run → closed
        sample_error=SampleErrorHandler(False, 1),
        sample_indexes={"s1": 0},
        checkpoints_dir=None,
        on_accept=lambda sample_id, epoch: None,
    )
    assert handle.accept(_errored_sample(), "error") == "closed"
    # nothing was reconciled and no pending key leaked
    state = get_eval_state("e1")
    assert state is not None and state.errored == 1
    assert not handle.is_pending("s1", 1)


# ---------------------------------------------------------------------------
# Samples listing: a pending requeue renders `queued`
# ---------------------------------------------------------------------------


async def test_listing_renders_pending_requeue_as_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_samples(monkeypatch, [])

    async def _summaries() -> list[EvalSampleSummary]:
        return [
            EvalSampleSummary(
                id="s1",
                epoch=1,
                input="q",
                target="a",
                error="RuntimeError('boom')",
                retries=1,
                completed=True,
            )
        ]

    register_eval(
        "e1",
        2,
        task_id="t1",
        live=FakeLiveEvalData(summaries=_summaries),
        sample_ids=["s1", "s2"],
    )
    set_sample_requeue(
        "e1", cast(SampleRequeue, _FakeRequeueHandle(pending={("s1", 1)}))
    )

    listing = await current_sample_listing("e1")
    rows = {(r["sample_id"], r["epoch"]): r for r in listing.samples}
    row = rows[("s1", 1)]
    # the terminal record is superseded-in-waiting: it renders as the
    # scheduled re-run (queued, no error), with `retries` counting what the
    # re-run will seed (the prior retry plus the genuine terminal error)
    assert row["status"] == "queued"
    assert row["error"] is None and row["completed_at"] is None
    assert row["retries"] == 2
    assert listing.counts["queued"] == 1 and listing.counts["error"] == 0


async def test_listing_pending_snapshot_taken_after_summaries_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A re-run going terminal during the summaries read renders terminal.

    The pending key clears on the same loop as the read, and the fresh
    terminal record is in the returned summaries — a pre-await snapshot
    would render that finished sample as a phantom `queued` row for one
    response.
    """
    _patch_active_samples(monkeypatch, [])
    handle = _FakeRequeueHandle(pending={("s1", 1)})

    async def _summaries() -> list[EvalSampleSummary]:
        # the re-run reaches its terminal outcome mid-read: its pending key
        # clears and its fresh record is what this read returns
        handle._pending.clear()
        return [
            EvalSampleSummary(
                id="s1",
                epoch=1,
                input="q",
                target="a",
                completed=True,
            )
        ]

    register_eval(
        "e1",
        2,
        task_id="t1",
        live=FakeLiveEvalData(summaries=_summaries),
        sample_ids=["s1", "s2"],
    )
    set_sample_requeue("e1", cast(SampleRequeue, handle))

    listing = await current_sample_listing("e1")
    row = next(r for r in listing.samples if r["sample_id"] == "s1" and r["epoch"] == 1)
    assert row["status"] == "completed"
    assert listing.counts["queued"] == 0 and listing.counts["completed"] == 1


async def test_sample_show_renders_pending_requeue_as_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`sample show` mirrors the listing during the pending window.

    The re-opened outcome reads `queued` with no current error, and the
    prior terminal error is echoed as the retry history the re-run will
    seed — so a wrongly-targeted requeue stays visible.
    """
    _patch_active_samples(monkeypatch, [])
    prior = _errored_sample()

    async def _summaries() -> list[EvalSampleSummary]:
        return [
            EvalSampleSummary(
                id="s1",
                epoch=1,
                input="q",
                target="a",
                error="RuntimeError('boom')",
                retries=0,
                completed=True,
            )
        ]

    async def _read(
        id: str | int, epoch: int, *, exclude_fields: set[str] | None = None
    ) -> EvalSample | None:
        return prior if str(id) == "s1" and epoch == 1 else None

    register_eval(
        "e1",
        2,
        task_id="t1",
        live=FakeLiveEvalData(summaries=_summaries, sample=_read),
        sample_ids=["s1", "s2"],
    )
    set_sample_requeue(
        "e1", cast(SampleRequeue, _FakeRequeueHandle(pending={("s1", 1)}))
    )

    detail = await sample_error_detail("e1", "s1", 1, content=True)
    assert detail is not None
    assert detail["status"] == "queued"
    assert detail["error"] is None and detail["completed_at"] is None
    assert detail["retries"] == 1
    assert [e["message"] for e in detail["error_retries"]] == ["boom"]

    # coherent with the listing's row for the same key
    listing = await current_sample_listing("e1")
    row = next(r for r in listing.samples if r["sample_id"] == "s1" and r["epoch"] == 1)
    assert row["status"] == "queued" and row["retries"] == 1


# ---------------------------------------------------------------------------
# Server route
# ---------------------------------------------------------------------------


def _app() -> Any:
    from inspect_ai._control.server import ControlServer

    return ControlServer(run_id="test")._build_app()


async def test_sample_requeue_route(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_active_samples(monkeypatch, [])
    handle = _register_requeueable(prior=_errored_sample())

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        # epoch is required on this mutation — a defaulted epoch would
        # silently target the epoch-1 attempt on a multi-epoch task
        no_epoch = await client.post(
            "/evals/e1/sample/requeue", params={"sample_id": "s1"}
        )
        assert no_epoch.status_code == 400
        assert "epoch is required" in no_epoch.json()["error"]

        ok = await client.post(
            "/evals/e1/sample/requeue", params={"sample_id": "s1", "epoch": 1}
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["changed"] is True
        assert len(handle.accepts) == 1

        missing = await client.post(
            "/evals/e1/sample/requeue", params={"sample_id": "nope", "epoch": 1}
        )
        assert missing.status_code == 404
        assert "error" in missing.json()  # handler 404 carries the error key

        unknown_eval = await client.post(
            "/evals/nope/sample/requeue", params={"sample_id": "s1", "epoch": 1}
        )
        assert unknown_eval.status_code == 404


async def test_sample_requeue_route_completed_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_samples(monkeypatch, [])
    _register_requeueable(prior=EvalSample(id="s1", epoch=1, input="q", target="a"))

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        rejected = await client.post(
            "/evals/e1/sample/requeue", params={"sample_id": "s1", "epoch": 1}
        )
        assert rejected.status_code == 409
        assert "completed successfully" in rejected.json()["error"]


async def test_sample_requeue_route_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_active_samples(monkeypatch, [])
    handle = _register_requeueable(prior=_errored_sample())

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        dry = await client.post(
            "/evals/e1/sample/requeue",
            params={"sample_id": "s1", "epoch": 1, "dry_run": True},
        )
        assert dry.status_code == 200, dry.text
        body = dry.json()
        assert body["changed"] is True and body["dry_run"] is True
        assert handle.accepts == []


# ---------------------------------------------------------------------------
# End to end: requeue through a live eval
# ---------------------------------------------------------------------------

_E2E_ATTEMPTS: dict[str, int] = {}
_E2E_RELEASE: anyio.Event | None = None


@solver
def _requeue_probe():
    """Errors flaky's first attempt; parks everything else until released.

    The park (on the flaky re-run too) keeps the fanout open and the re-run
    non-terminal while the test issues its directives, so the idempotence
    assertions are deterministic.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if state.sample_id == "flaky":
            _E2E_ATTEMPTS["flaky"] = _E2E_ATTEMPTS.get("flaky", 0) + 1
            if _E2E_ATTEMPTS["flaky"] == 1:
                raise RuntimeError("transient boom")
        assert _E2E_RELEASE is not None
        with anyio.fail_after(60):
            await _E2E_RELEASE.wait()
        return state

    return solve


@scorer(metrics=[accuracy()])
def _always_correct():
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=CORRECT)

    return score


async def test_requeue_end_to_end() -> None:
    """An errored sample requeued mid-run re-runs to a clean final log.

    Exercises the whole path: the scheduler accepts the re-run while the
    task is live, the terminal counters re-open, the fresh attempt
    supersedes the log record (with the prior error seeded as retry history
    and a fresh uuid, so a stale events cursor resets), and metrics are
    computed from the fresh score.
    """
    global _E2E_RELEASE
    _E2E_ATTEMPTS.clear()
    _E2E_RELEASE = anyio.Event()

    task = Task(
        dataset=[
            Sample(id="flaky", input="x", target="y"),
            Sample(id="waiter", input="x", target="y"),
        ],
        solver=_requeue_probe(),
        scorer=_always_correct(),
        name="requeue_e2e",
    )

    init_display_type("none")
    logs: list[EvalLog] = []

    async with anyio.create_task_group() as tg:

        async def run_eval() -> None:
            logs.extend(
                await eval_async(
                    task,
                    model="mockllm/model",
                    fail_on_error=False,
                    ctl_server=False,
                    max_samples=2,
                )
            )

        tg.start_soon(run_eval)

        # wait for the flaky sample's terminal error
        with anyio.fail_after(60):
            while True:
                states = get_eval_states()
                if states and states[0].errored == 1:
                    break
                await anyio.sleep(0.01)
        eval_id = states[0].eval_id

        prior = await _full_sample(eval_id, "flaky", 1)
        assert prior is not None and prior.error is not None
        prior_uuid = prior.uuid

        first = await requeue_sample(eval_id, "flaky", 1)
        assert first is not None
        assert first["ok"] is True
        assert first["changed"] is True and first["status"] == "error"
        assert first["attempt"] == 2

        # counters re-opened synchronously in the accept path
        state = get_eval_state(eval_id)
        assert state is not None and state.errored == 0

        # an immediate repeat is the idempotent no-op (the re-run is held
        # open by the solver's park, so it cannot have gone terminal)
        second = await requeue_sample(eval_id, "flaky", 1)
        assert second is not None and second["ok"] is True
        assert second["changed"] is False

        _E2E_RELEASE.set()

    assert _E2E_ATTEMPTS["flaky"] == 2

    (log,) = logs
    assert log.status == "success"
    # read the samples back through the async reader: the returned log's
    # lazy sample list loads via the sync reader, which trio refuses
    log = await read_eval_log_async(log.location)
    assert log.samples is not None
    flaky = next(s for s in log.samples if s.id == "flaky")
    # the fresh outcome superseded the (id, epoch) record: no error, the
    # prior attempt seeded as retry history, and a fresh uuid (so a stale
    # events cursor signals a reset rather than serving misindexed events)
    assert flaky.error is None
    assert flaky.error_retries is not None and len(flaky.error_retries) == 1
    assert "transient boom" in flaky.error_retries[0].message
    assert flaky.uuid != prior_uuid
    # metrics computed from the fresh score
    assert log.results is not None
    assert log.results.scores[0].metrics["accuracy"].value == 1.0


_E2E_TWICE_ATTEMPTS: dict[str, int] = {}
_E2E_TWICE_RELEASE: anyio.Event | None = None


@solver
def _requeue_twice_probe():
    """Errors flaky's first two attempts; parks everything else until released."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if state.sample_id == "flaky":
            _E2E_TWICE_ATTEMPTS["flaky"] = _E2E_TWICE_ATTEMPTS.get("flaky", 0) + 1
            if _E2E_TWICE_ATTEMPTS["flaky"] <= 2:
                raise RuntimeError(f"transient boom {_E2E_TWICE_ATTEMPTS['flaky']}")
        assert _E2E_TWICE_RELEASE is not None
        with anyio.fail_after(60):
            await _E2E_TWICE_RELEASE.wait()
        return state

    return solve


async def test_requeue_second_requeue_with_buffered_records() -> None:
    """A second requeue after a second failure passes with unflushed records.

    With a log buffer large enough that neither terminal record flushes, the
    directive reads the prior through the recorder's flush buffer: the
    re-run's fresh failure must supersede the prior attempt there, so the
    second requeue reads the fresh uuid and is accepted — not 409'd as stale
    against the first accept — and the finished log carries one record for
    the key with the full retry history.
    """
    global _E2E_TWICE_RELEASE
    _E2E_TWICE_ATTEMPTS.clear()
    _E2E_TWICE_RELEASE = anyio.Event()

    task = Task(
        dataset=[
            Sample(id="flaky", input="x", target="y"),
            Sample(id="waiter", input="x", target="y"),
        ],
        solver=_requeue_twice_probe(),
        scorer=_always_correct(),
        name="requeue_twice_e2e",
    )

    init_display_type("none")
    logs: list[EvalLog] = []

    async with anyio.create_task_group() as tg:

        async def run_eval() -> None:
            logs.extend(
                await eval_async(
                    task,
                    model="mockllm/model",
                    fail_on_error=False,
                    ctl_server=False,
                    max_samples=2,
                    log_buffer=10,
                )
            )

        tg.start_soon(run_eval)

        async def wait_for_errored() -> Any:
            with anyio.fail_after(60):
                while True:
                    states = get_eval_states()
                    if states and states[0].errored == 1:
                        return states[0]
                    await anyio.sleep(0.01)

        state = await wait_for_errored()
        eval_id = state.eval_id

        first = await requeue_sample(eval_id, "flaky", 1)
        assert first is not None
        assert first["ok"] is True and first["changed"] is True
        assert first["attempt"] == 2

        # the re-run fails again; its record supersedes the prior in the
        # (unflushed) buffer, so this second requeue reads the fresh uuid
        await wait_for_errored()
        second = await requeue_sample(eval_id, "flaky", 1)
        assert second is not None
        assert second["ok"] is True, f"second requeue rejected: {second}"
        assert second["changed"] is True
        assert second["attempt"] == 3

        _E2E_TWICE_RELEASE.set()

    assert _E2E_TWICE_ATTEMPTS["flaky"] == 3

    (log,) = logs
    assert log.status == "success"
    log = await read_eval_log_async(log.location)
    assert log.samples is not None
    flaky_records = [s for s in log.samples if s.id == "flaky"]
    assert len(flaky_records) == 1
    assert flaky_records[0].error is None
    assert flaky_records[0].error_retries is not None
    assert len(flaky_records[0].error_retries) == 2


_E2E_OP_RELEASE: anyio.Event | None = None


@solver
def _park_probe():
    """Parks every sample until released."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        assert _E2E_OP_RELEASE is not None
        with anyio.fail_after(60):
            await _E2E_OP_RELEASE.wait()
        return state

    return solve


async def test_requeue_after_operator_errored_sample() -> None:
    """A `sample cancel --action error` prior requeues out of the errored bucket.

    The runner records that terminal with a distinct operator-error message
    (not the cancellation exception's repr), so the requeue's message-based
    classification matches the bucket the recording bumped: accept decrements
    `errored` (never `cancelled` to -1), un-counts the error toward
    fail-on-error, and the re-run seeds the operator-errored attempt as retry
    history.
    """
    global _E2E_OP_RELEASE
    _E2E_OP_RELEASE = anyio.Event()

    task = Task(
        dataset=[
            Sample(id="victim", input="x", target="y"),
            Sample(id="waiter", input="x", target="y"),
        ],
        solver=_park_probe(),
        scorer=_always_correct(),
        name="requeue_operator_error_e2e",
    )

    init_display_type("none")
    logs: list[EvalLog] = []

    async with anyio.create_task_group() as tg:

        async def run_eval() -> None:
            logs.extend(
                await eval_async(
                    task,
                    model="mockllm/model",
                    fail_on_error=False,
                    ctl_server=False,
                    max_samples=2,
                )
            )

        tg.start_soon(run_eval)

        # wait for the victim sample to be running, then error it via the
        # operator cancel directive
        with anyio.fail_after(60):
            while True:
                states = get_eval_states()
                if states:
                    active = find_active_sample(states[0].eval_id, "victim", 1)
                    if active is not None and active.started is not None:
                        break
                await anyio.sleep(0.01)
        eval_id = states[0].eval_id

        cancelled = await cancel_sample(eval_id, "victim", 1, action="error")
        assert cancelled is not None and cancelled["changed"] is True

        with anyio.fail_after(60):
            while True:
                state = get_eval_state(eval_id)
                if state is not None and state.errored == 1:
                    break
                await anyio.sleep(0.01)

        # recorded as a genuine (non-cancellation) error, consistent with
        # the errored bucket its terminal recording bumped
        prior = await _full_sample(eval_id, "victim", 1)
        assert prior is not None and prior.error is not None
        assert not is_cancellation_message(prior.error.message)

        result = await requeue_sample(eval_id, "victim", 1)
        assert result is not None
        assert result["ok"] is True and result["changed"] is True
        assert result["status"] == "error"
        assert result["attempt"] == 2

        state = get_eval_state(eval_id)
        assert state is not None
        assert state.errored == 0
        assert state.cancelled == 0

        _E2E_OP_RELEASE.set()

    (log,) = logs
    assert log.status == "success"
    log = await read_eval_log_async(log.location)
    assert log.samples is not None
    victim = next(s for s in log.samples if s.id == "victim")
    assert victim.error is None
    assert victim.error_retries is not None and len(victim.error_retries) == 1
    assert "interrupted by operator" in victim.error_retries[0].message


# ---------------------------------------------------------------------------
# End to end: requeue on a SampleSource-driven (dynamic) task
# ---------------------------------------------------------------------------

_DYN_ATTEMPTS: dict[str, int] = {}
_DYN_RELEASE: anyio.Event | None = None


@solver
def _dyn_requeue_probe():
    """The seeder enqueues `flaky` then parks; `flaky` errors its first attempt."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if state.sample_id == "seeder":
            enqueue_sample(Sample(id="flaky", input="x", target="y"))
            assert _DYN_RELEASE is not None
            with anyio.fail_after(60):
                await _DYN_RELEASE.wait()
            return state
        _DYN_ATTEMPTS["flaky"] = _DYN_ATTEMPTS.get("flaky", 0) + 1
        if _DYN_ATTEMPTS["flaky"] == 1:
            raise RuntimeError("transient boom")
        return state

    return solve


class _SeederSource(SampleSource):
    def initial_samples(self) -> list[Sample]:
        return [Sample(id="seeder", input="x", target="y")]

    async def next_samples(self) -> list[Sample] | None:
        return None


async def test_requeue_dynamic_injected_sample() -> None:
    """An errored *injected* sample can be requeued on a SampleSource task.

    Exercises the injected-sample plumbing end to end: the requeue directive
    resolves the injected id (grown into `sample_indexes`), and the re-run
    finds its source data resident (an errored epoch keeps the injected
    slot — it releases only once every epoch has completed).
    """
    global _DYN_RELEASE
    _DYN_ATTEMPTS.clear()
    _DYN_RELEASE = anyio.Event()

    task = Task(
        dataset=_SeederSource(),
        solver=_dyn_requeue_probe(),
        scorer=_always_correct(),
        name="requeue_dyn",
    )

    init_display_type("none")
    logs: list[EvalLog] = []

    async with anyio.create_task_group() as tg:

        async def run_eval() -> None:
            logs.extend(
                await eval_async(
                    task,
                    model="mockllm/model",
                    fail_on_error=False,
                    ctl_server=False,
                    max_samples=2,
                )
            )

        tg.start_soon(run_eval)

        # wait for the injected flaky sample's terminal error
        with anyio.fail_after(60):
            while True:
                states = get_eval_states()
                if states and states[0].errored == 1:
                    break
                await anyio.sleep(0.01)
        eval_id = states[0].eval_id

        result = await requeue_sample(eval_id, "flaky", 1)
        assert result is not None
        assert result["ok"] is True and result["changed"] is True
        assert result["status"] == "error"
        assert result["attempt"] == 2

        # wait for the re-run's clean completion, then release the seeder
        with anyio.fail_after(60):
            while True:
                state = get_eval_state(eval_id)
                assert state is not None
                if state.errored == 0 and state.completed == 1:
                    break
                await anyio.sleep(0.01)
        _DYN_RELEASE.set()

    assert _DYN_ATTEMPTS["flaky"] == 2

    (log,) = logs
    assert log.status == "success"
    log = await read_eval_log_async(log.location)
    assert log.samples is not None
    assert sorted(str(s.id) for s in log.samples) == ["flaky", "seeder"]
    flaky = next(s for s in log.samples if s.id == "flaky")
    assert flaky.error is None
    assert flaky.error_retries is not None and len(flaky.error_retries) == 1
    assert "transient boom" in flaky.error_retries[0].message
    assert log.results is not None
    assert log.results.scores[0].metrics["accuracy"].value == 1.0


_DYN_IDLE_ATTEMPTS: dict[str, int] = {}


@solver
def _dyn_idle_probe():
    """Errors flaky's first attempt; the re-run completes immediately."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        _DYN_IDLE_ATTEMPTS["flaky"] = _DYN_IDLE_ATTEMPTS.get("flaky", 0) + 1
        if _DYN_IDLE_ATTEMPTS["flaky"] == 1:
            raise RuntimeError("transient boom")
        return state

    return solve


class _BlockingSource(SampleSource):
    """A source that parks in next_samples() until released (an RL loop shape)."""

    def __init__(self) -> None:
        self.consulted = anyio.Event()
        self.release = anyio.Event()

    def initial_samples(self) -> list[Sample]:
        return [Sample(id="flaky", input="x", target="y")]

    async def next_samples(self) -> list[Sample] | None:
        self.consulted.set()
        with anyio.fail_after(60):
            await self.release.wait()
        return None


async def test_requeue_dynamic_while_awaiting_source() -> None:
    """A requeue is accepted while the run idles inside next_samples().

    Nothing is outstanding — only the feeder's hold keeps the fanout open —
    and the accepted re-run starts immediately rather than waiting for the
    source to produce.
    """
    _DYN_IDLE_ATTEMPTS.clear()
    source = _BlockingSource()

    task = Task(
        dataset=source,
        solver=_dyn_idle_probe(),
        scorer=_always_correct(),
        name="requeue_dyn_idle",
    )

    init_display_type("none")
    logs: list[EvalLog] = []

    async with anyio.create_task_group() as tg:

        async def run_eval() -> None:
            logs.extend(
                await eval_async(
                    task,
                    model="mockllm/model",
                    fail_on_error=False,
                    ctl_server=False,
                )
            )

        tg.start_soon(run_eval)

        # wait until flaky has errored AND the feeder is parked in the source
        with anyio.fail_after(60):
            await source.consulted.wait()
            while True:
                states = get_eval_states()
                if states and states[0].errored == 1:
                    break
                await anyio.sleep(0.01)
        eval_id = states[0].eval_id

        result = await requeue_sample(eval_id, "flaky", 1)
        assert result is not None
        assert result["ok"] is True and result["changed"] is True

        # the re-run completes while the source is still parked
        with anyio.fail_after(60):
            while True:
                state = get_eval_state(eval_id)
                assert state is not None
                if state.errored == 0 and state.completed == 1:
                    break
                await anyio.sleep(0.01)
        source.release.set()

    assert _DYN_IDLE_ATTEMPTS["flaky"] == 2

    (log,) = logs
    assert log.status == "success"
    log = await read_eval_log_async(log.location)
    assert log.samples is not None
    flaky = next(s for s in log.samples if s.id == "flaky")
    assert flaky.error is None
    assert flaky.error_retries is not None and len(flaky.error_retries) == 1
