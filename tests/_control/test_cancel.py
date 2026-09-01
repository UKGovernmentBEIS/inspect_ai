"""Tests for the control-channel cancel and drain directives (phase 3).

Covers the directive functions in ``inspect_ai._control.cancel`` (task
cancel/drain: task-keyed, resolved to the latest attempt's registered
``TaskCancel``; sample cancel: interrupt via ``ActiveSample.interrupt``;
tool-call cancel: fire one pending ``ToolEvent``'s per-call cancel scope) and
the server routes that wrap them (``POST /tasks/<id>/cancel``,
``POST /tasks/<id>/drain``, ``POST /evals/<id>/sample/cancel``,
``POST /evals/<id>/sample/cancel-tool-call``).
"""

from types import SimpleNamespace
from typing import Any, Literal, cast

import anyio
import httpx
import pytest
from test_helpers.live_eval_data import FakeLiveEvalData

from inspect_ai import Task, eval_async
from inspect_ai._control.cancel import (
    CancelSampleResult,
    TaskCancelAction,
    cancel_sample,
    cancel_task,
    cancel_tool_call,
    drain_task,
)
from inspect_ai._control.eval_state import (
    clear_all_eval_states,
    get_eval_state,
    get_eval_states,
    mark_eval_retry_pending,
    record_sample_errored,
    register_completed_eval,
    register_eval,
    reset_gracefully_resolved,
    reset_retry_abandoned,
    set_sample_requeue,
    task_gracefully_resolved,
    task_retry_abandoned,
)
from inspect_ai._control.requeue import requeue_sample
from inspect_ai._control.state import current_sample_listing, sample_error_detail
from inspect_ai._display.core.display import CancelType, TaskCancel
from inspect_ai._eval.task.error import SampleErrorHandler
from inspect_ai._eval.task.scheduler import (
    DISCARDED,
    SampleRequeue,
    SampleScheduler,
    _SampleRun,
)
from inspect_ai.dataset import Sample
from inspect_ai.log import read_eval_log_async
from inspect_ai.log._log import EvalSample
from inspect_ai.scorer import CORRECT, Score, Target, accuracy, scorer
from inspect_ai.solver import Generate, TaskState, solver
from inspect_ai.util._display import init_display_type


@pytest.fixture(autouse=True)
def _clear_states():
    clear_all_eval_states()
    reset_retry_abandoned()
    reset_gracefully_resolved()
    yield
    clear_all_eval_states()
    reset_retry_abandoned()
    reset_gracefully_resolved()


class _FakeTaskCancel(TaskCancel):
    """A ``TaskCancel`` whose fired cancel types are recorded, not applied."""

    def __init__(self, can_retry: bool = False) -> None:
        self.fired: list[CancelType] = []

        def _fire(cancel_type: CancelType) -> None:
            self.fired.append(cancel_type)
            self.cancel_type = cancel_type

        super().__init__(can_retry=can_retry, cancel_task=_fire)


class _FakeActiveSample:
    """The slice of ``ActiveSample`` the sample-cancel directive touches."""

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
        fails_on_error: bool = False,
        pending_events: list[Any] | None = None,
    ) -> None:
        self.eval_id = eval_id
        self.sample = self._Sample(sample_id)
        self.epoch = epoch
        self.started = started
        self.completed = completed
        self.fails_on_error = fails_on_error
        self.interrupts: list[str] = []
        self.interrupt_action: Literal["score", "error", "cancel"] | None = None
        self.limit_exceeded_error: Exception | None = None
        # the slice the tool-call-cancel resolver reads: the pending-events
        # sidecar (and retry_wait, via the zero-pending activity detail)
        self.transcript = SimpleNamespace(pending_events=pending_events or [])
        self.retry_wait = None
        self.pending_interaction: str | None = None
        self.pending_interactions: tuple[object, ...] = ()

    def interrupt(self, action: Literal["score", "error", "cancel"]) -> None:
        self.interrupts.append(action)
        self.interrupt_action = action


def _patch_active_samples(
    monkeypatch: pytest.MonkeyPatch, samples: list[_FakeActiveSample]
) -> None:
    monkeypatch.setattr("inspect_ai.log._samples.active_samples", lambda: samples)


# ---------------------------------------------------------------------------
# cancel_task directive
# ---------------------------------------------------------------------------


def test_cancel_task_fires_abort() -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task="my_task", task_cancel=handle)

    result = cancel_task("t1")
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert result["task_id"] == "t1" and result["eval_id"] == "e1"
    assert handle.fired == ["abort"]


def test_cancel_task_unknown_is_none() -> None:
    assert cancel_task("nope") is None
    assert cancel_task("") is None


def test_cancel_task_dry_run_does_not_fire() -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)

    result = cancel_task("t1", dry_run=True)
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert result["dry_run"] is True
    assert handle.fired == []


def test_cancel_task_repeat_is_idempotent_noop() -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)

    first = cancel_task("t1")
    assert first is not None and first["ok"] is True and first["changed"] is True
    repeat = cancel_task("t1")
    assert repeat is not None
    assert repeat["ok"] is True and repeat["changed"] is False
    assert repeat["reason"] == "cancel already requested (abort)"
    assert handle.fired == ["abort"]  # fired exactly once


def test_cancel_task_pending_retry_abandons_requested_retry() -> None:
    """A plain cancel against a pending *retry* stamp abandons the retry.

    The attempt requested a re-run and is still tearing down (before the
    dispatcher queues the retry). A no-op here would silently drop the
    intent — the retry would dispatch the whole task fresh — so the
    directive stamps the retry-abandoned registry instead; the tearing-down
    attempt itself is untouched (no abort is fired — its scope has already
    fired).
    """
    handle = _FakeTaskCancel(can_retry=True)
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    handle.cancel_task("retry")

    result = cancel_task("t1")
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert result.get("retry_abandoned") is True
    assert handle.fired == ["retry"]  # the abort was not fired
    assert task_retry_abandoned("t1")

    # a repeat consults the registry and takes the idempotent no-op — only
    # the first request reports the abandonment
    repeat = cancel_task("t1")
    assert repeat is not None
    assert repeat["ok"] is True and repeat["changed"] is False
    assert repeat["reason"] == "pending retry already abandoned"

    # a score/error repeat gets the same honest reason — "cancel already
    # requested (retry)" would imply a retry is coming that never dispatches
    score_repeat = cancel_task("t1", action="score")
    assert score_repeat is not None
    assert score_repeat["ok"] is True and score_repeat["changed"] is False
    assert score_repeat["reason"] == "pending retry already abandoned"


def test_cancel_task_pending_retry_score_error_stay_noop() -> None:
    """Score/error against a pending retry stamp stay the named no-op.

    The attempt's samples are already resolved — there is nothing for a
    resolution to apply to, mirroring their between-attempts rejection.
    """
    handle = _FakeTaskCancel(can_retry=True)
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    handle.cancel_task("retry")

    result = cancel_task("t1", action="score")
    assert result is not None
    assert result["ok"] is True and result["changed"] is False
    assert result["reason"] == "cancel already requested (retry)"
    assert not task_retry_abandoned("t1")


def test_cancel_task_pending_retry_without_budget_is_noop() -> None:
    """A retry request that will not be honored has nothing to abandon.

    The dispatcher honors a "retry" stamp only with budget remaining
    (mirrored by ``TaskCancel.can_retry``), so when it is false no retry is
    coming — ``changed: true`` would claim an abandonment that never
    happens.
    """
    handle = _FakeTaskCancel(can_retry=False)
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    handle.cancel_task("retry")

    result = cancel_task("t1")
    assert result is not None
    assert result["ok"] is True and result["changed"] is False
    assert "retry request will not be honored" in result["reason"]
    assert not task_retry_abandoned("t1")


def test_cancel_task_finished_is_idempotent_noop() -> None:
    register_completed_eval("e1", total=5, completed=5, task_id="t1", task="my_task")
    result = cancel_task("t1")
    assert result is not None
    assert result["ok"] is True and result["changed"] is False
    assert "finished" in result["reason"]


def test_cancel_task_between_attempts_abandons_pending_retry() -> None:
    """A plain cancel of a between-attempts task abandons the queued retry.

    The task ends with its last attempt's error log (exactly the shape an
    exhausted retry budget produces): the registry is stamped for the
    dispatcher to consume, ``retry_pending`` is cleared synchronously so the
    task reads terminal the moment the directive returns, and ``will_retry``
    is cleared so cancelled samples stop rendering ``pending``.
    """
    handle = _FakeTaskCancel(can_retry=True)
    register_eval("e1", 1, task_id="t1", will_retry=True, task_cancel=handle)
    record_sample_errored("e1")  # attempt finishes (completed_at stamped) ...
    mark_eval_retry_pending("e1")  # ... and the eval-set queues a retry

    result = cancel_task("t1")
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert result.get("retry_abandoned") is True
    assert handle.fired == []  # nothing running to fire
    assert task_retry_abandoned("t1")
    state = get_eval_state("e1")
    assert state is not None
    assert state.retry_pending is False and state.will_retry is False

    # a repeat sees the registry stamp, not "task already finished"
    repeat = cancel_task("t1")
    assert repeat is not None
    assert repeat["ok"] is True and repeat["changed"] is False
    assert repeat["reason"] == "pending retry already abandoned"


def test_cancel_task_between_attempts_dry_run_does_not_abandon() -> None:
    handle = _FakeTaskCancel(can_retry=True)
    register_eval("e1", 1, task_id="t1", will_retry=True, task_cancel=handle)
    record_sample_errored("e1")
    mark_eval_retry_pending("e1")

    result = cancel_task("t1", dry_run=True)
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert result.get("retry_abandoned") is True
    assert not task_retry_abandoned("t1")
    state = get_eval_state("e1")
    assert state is not None and state.retry_pending is True


def test_cancel_task_between_attempts_score_error_rejected() -> None:
    """Score/error on a between-attempts task remain a rejection.

    There are no samples, queued or in-flight, for a resolution to apply to
    — the error points at a plain cancel (or drain) instead of the old
    "re-issue once the retry is running".
    """
    handle = _FakeTaskCancel(can_retry=True)
    register_eval("e1", 1, task_id="t1", will_retry=True, task_cancel=handle)
    record_sample_errored("e1")
    mark_eval_retry_pending("e1")

    result = cancel_task("t1", action="score")
    assert result is not None
    assert result["ok"] is False and "between attempts" in result["error"]
    assert "drain" in result["error"]
    assert handle.fired == []
    assert not task_retry_abandoned("t1")


def test_cancel_task_after_pending_retry_starts() -> None:
    """Once the retry registers, the task-keyed cancel targets it normally."""
    old = _FakeTaskCancel(can_retry=True)
    register_eval("e1", 1, task_id="t1", will_retry=True, task_cancel=old)
    record_sample_errored("e1")
    mark_eval_retry_pending("e1")
    new = _FakeTaskCancel()
    register_eval("e2", 1, task_id="t1", task_cancel=new)

    result = cancel_task("t1")
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert result["eval_id"] == "e2"
    assert old.fired == [] and new.fired == ["abort"]


def test_mark_eval_retry_pending_unregistered_is_noop() -> None:
    mark_eval_retry_pending("nope")  # must not raise


def test_clear_eval_retry_pending_unwinds_pre_mark() -> None:
    """The dispatcher unwinds a runner pre-mark when no retry follows.

    The task runner flags ``retry_pending`` as soon as it decides an error
    status the eval-set would retry (before its log write); when a cancel
    stamp landing in that window supersedes the retry, the dispatcher clears
    the flag — otherwise the task would read as between attempts forever
    (listed active, requeue rejected, a repeat cancel claiming to abandon a
    retry that was never coming).
    """
    from inspect_ai._control.eval_state import clear_eval_retry_pending

    handle = _FakeTaskCancel(can_retry=True)
    register_eval("e1", 1, task_id="t1", will_retry=True, task_cancel=handle)
    record_sample_errored("e1")
    mark_eval_retry_pending("e1")  # the runner's pre-mark ...
    clear_eval_retry_pending("e1")  # ... unwound: the dispatcher won't retry
    state = get_eval_state("e1")
    assert state is not None and state.retry_pending is False

    result = cancel_task("t1")
    assert result is not None
    assert result["ok"] is True and result["changed"] is False
    assert result["reason"] == "task already finished"
    assert not task_retry_abandoned("t1")

    clear_eval_retry_pending("nope")  # unregistered: must not raise


def test_cancel_task_running_without_handle_rejected() -> None:
    # a running (not finished) state with no cancel handle can't be cancelled
    register_eval("e1", 5, task_id="t1")
    result = cancel_task("t1")
    assert result is not None
    assert result["ok"] is False and "not cancellable" in result["error"]


def test_cancel_task_resolves_latest_attempt() -> None:
    """A retry registers a fresh attempt; the task-keyed cancel targets it."""
    old = _FakeTaskCancel()
    new = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=old)
    register_eval("e2", 5, task_id="t1", task_cancel=new)

    result = cancel_task("t1")
    assert result is not None and result["ok"] is True
    assert result["eval_id"] == "e2"
    assert old.fired == [] and new.fired == ["abort"]


def test_cancel_task_counts_in_flight_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    _patch_active_samples(
        monkeypatch,
        [
            _FakeActiveSample(sample_id="s1"),
            _FakeActiveSample(sample_id="s2", started=None),  # queued
            _FakeActiveSample(sample_id="s3", completed=2.0),  # finished
            _FakeActiveSample(sample_id="s4", eval_id="other"),
        ],
    )
    result = cancel_task("t1", dry_run=True)
    assert result is not None and result["ok"] is True
    assert result["in_flight"] == 1


def test_cancel_task_score_resolution_interrupts_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A score resolution interrupts only the in-flight samples.

    The handle is stamped (no abort); queued/initializing (not-started) and
    finished samples are untouched.
    """
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    running = _FakeActiveSample(sample_id="s1")
    initializing = _FakeActiveSample(sample_id="s2", started=None)
    finished = _FakeActiveSample(sample_id="s3", completed=2.0)
    other = _FakeActiveSample(sample_id="s4", eval_id="other")
    _patch_active_samples(monkeypatch, [running, initializing, finished, other])

    result = cancel_task("t1", action="score")
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert result["action"] == "score" and result["in_flight"] == 1
    assert handle.fired == ["score"]  # stamped, not an abort
    assert running.interrupts == ["score"]
    assert initializing.interrupts == []  # resolves itself when it starts
    assert finished.interrupts == [] and other.interrupts == []


def test_cancel_task_error_resolution_interrupts_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    running = _FakeActiveSample(sample_id="s1")
    _patch_active_samples(monkeypatch, [running])

    result = cancel_task("t1", action="error")
    assert result is not None and result["ok"] is True and result["changed"] is True
    assert handle.fired == ["error"]
    assert running.interrupts == ["error"]


def test_cancel_task_error_resolution_gated_by_fails_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The task-level error resolution mirrors the sample-level gate.

    It checks initializing (not-yet-started) samples too, since they resolve
    with the stamped action when they start.
    """
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    initializing = _FakeActiveSample(sample_id="s2", started=None, fails_on_error=True)
    _patch_active_samples(monkeypatch, [initializing])

    result = cancel_task("t1", action="error")
    assert result is not None
    assert result["ok"] is False and "fail on errors" in result["error"]
    assert handle.fired == [] and initializing.interrupts == []


def test_cancel_task_score_resolution_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    running = _FakeActiveSample(sample_id="s1")
    _patch_active_samples(monkeypatch, [running])

    result = cancel_task("t1", action="score", dry_run=True)
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert result["dry_run"] is True
    assert handle.fired == [] and running.interrupts == []


def test_cancel_task_score_resolution_repeat_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    running = _FakeActiveSample(sample_id="s1")
    _patch_active_samples(monkeypatch, [running])

    first = cancel_task("t1", action="score")
    assert first is not None and first["ok"] is True and first["changed"] is True
    repeat = cancel_task("t1", action="score")
    assert repeat is not None and repeat["ok"] is True
    assert repeat["changed"] is False
    assert repeat["reason"] == "cancel already requested (score)"
    assert handle.fired == ["score"] and running.interrupts == ["score"]


def test_cancel_task_resolution_sweep_skips_already_interrupted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The in-flight sweep never overwrites a sample's existing interrupt.

    A sample that was per-sample cancelled is still "in flight" until its
    (post-scoring/logging) context exit stamps `completed`; re-interrupting
    it would flip a not-yet-handled 'cancel' to the score/error disposition
    and re-fire on_interrupt hooks on a sample already being resolved.
    """
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    already_cancelled = _FakeActiveSample(sample_id="s1")
    already_cancelled.interrupt("cancel")
    running = _FakeActiveSample(sample_id="s2")
    _patch_active_samples(monkeypatch, [already_cancelled, running])

    result = cancel_task("t1", action="score")
    assert result is not None and result["ok"] is True and result["changed"] is True
    assert already_cancelled.interrupts == ["cancel"]  # not re-interrupted
    assert running.interrupts == ["score"]


def test_cancel_task_resolution_sweep_skips_fired_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The in-flight sweep never overwrites a fired-but-unhandled limit.

    A sample whose limit has fired but whose cancellation the runner has
    not yet handled has `limit_exceeded_error` set and `interrupt_action`
    unset; the runner checks `interrupt_action` first, so interrupting it
    would hijack the limit's legitimate outcome with the sweep's
    disposition (and re-fire on_interrupt on top of the limit's firing).
    """
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    limited = _FakeActiveSample(sample_id="s1")
    limited.limit_exceeded_error = Exception("working limit")
    running = _FakeActiveSample(sample_id="s2")
    _patch_active_samples(monkeypatch, [limited, running])

    result = cancel_task("t1", action="score")
    assert result is not None and result["ok"] is True and result["changed"] is True
    assert limited.interrupts == []  # limit outcome preserved
    assert running.interrupts == ["score"]


def test_cancel_task_abort_escalates_over_pending_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain cancel tears down a task whose graceful resolution stalled."""
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    running = _FakeActiveSample(sample_id="s1")
    _patch_active_samples(monkeypatch, [running])

    first = cancel_task("t1", action="score")
    assert first is not None and first["ok"] is True and first["changed"] is True
    escalated = cancel_task("t1")
    assert escalated is not None and escalated["ok"] is True
    assert escalated["changed"] is True
    assert handle.fired == ["score", "abort"]

    # ... but a score/error request never overrides a pending abort
    repeat = cancel_task("t1", action="error")
    assert repeat is not None and repeat["ok"] is True
    assert repeat["changed"] is False
    assert repeat["reason"] == "cancel already requested (abort)"


def test_cancel_task_stamp_clears_will_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stamping any type but "retry" clears the attempt's will_retry.

    Every other stamped type suppresses the eval-set's in-run retry, so a
    cancelled sample must render terminal rather than `pending` ("re-run
    coming") on the read surface.
    """
    handle = _FakeTaskCancel(can_retry=True)
    register_eval("e1", 5, task_id="t1", will_retry=True, task_cancel=handle)
    _patch_active_samples(monkeypatch, [])

    scored = cancel_task("t1", action="score")
    assert scored is not None and scored["ok"] is True
    assert scored["changed"] is True
    state = get_eval_state("e1")
    assert state is not None and state.will_retry is False


# ---------------------------------------------------------------------------
# drain_task directive
# ---------------------------------------------------------------------------


def test_drain_task_stamps_without_sweeping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drain stamps the handle and interrupts nothing.

    In-flight samples are never touched (they finish naturally); the stamp
    alone is what queued/initializing samples observe.
    """
    handle = _FakeTaskCancel(can_retry=True)
    register_eval(
        "e1", 5, task_id="t1", task="my_task", will_retry=True, task_cancel=handle
    )
    running = _FakeActiveSample(sample_id="s1")
    initializing = _FakeActiveSample(sample_id="s2", started=None)
    _patch_active_samples(monkeypatch, [running, initializing])

    result = drain_task("t1")
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert result["task_id"] == "t1" and result["eval_id"] == "e1"
    assert "action" not in result
    assert handle.fired == ["drain"]  # stamped, nothing torn down
    assert running.interrupts == [] and initializing.interrupts == []
    # no re-run is coming — cancelled samples must read terminal
    state = get_eval_state("e1")
    assert state is not None and state.will_retry is False


def test_drain_task_reports_in_flight_queued_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The result carries the split the operator weighs: finish vs abandon."""
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    running = _FakeActiveSample(sample_id="s1")
    _patch_active_samples(monkeypatch, [running])

    result = drain_task("t1", dry_run=True)
    assert result is not None and result["ok"] is True
    assert result["in_flight"] == 1 and result.get("queued") == 4
    assert handle.fired == []  # dry run


def test_graceful_resolutions_mark_task_gracefully_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Graceful stamps mark the graceful-resolution registry; abort does not.

    Drain and score/error stamps record the task in the registry (eval-set's
    completeness check honors the resolution for the life of the run — see
    log_samples_complete); an abort does not (its log never reads as a
    success), and a dry run stamps nothing.
    """
    cases: list[tuple[TaskCancelAction | None, bool]] = [
        (None, True),  # drain
        ("score", True),
        ("error", True),
        ("cancel", False),  # abort
    ]
    for action, marked in cases:
        clear_all_eval_states()
        reset_gracefully_resolved()
        handle = _FakeTaskCancel()
        register_eval("e1", 5, task_id="t1", task_cancel=handle)
        _patch_active_samples(monkeypatch, [])

        dry = (
            drain_task("t1", dry_run=True)
            if action is None
            else cancel_task("t1", action=action, dry_run=True)
        )
        assert dry is not None and dry["ok"] is True
        assert dry["changed"] is True
        assert not task_gracefully_resolved("t1")
        if action is None:
            drain_task("t1")
        else:
            cancel_task("t1", action=action)
        assert task_gracefully_resolved("t1") is marked


def test_drain_task_unknown_is_none() -> None:
    assert drain_task("nope") is None


def test_drain_task_finished_is_idempotent_noop() -> None:
    register_completed_eval("e1", total=5, completed=5, task_id="t1")
    result = drain_task("t1")
    assert result is not None and result["ok"] is True
    assert result["changed"] is False and "finished" in result["reason"]


def test_drain_task_repeat_is_idempotent_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    _patch_active_samples(monkeypatch, [])

    first = drain_task("t1")
    assert first is not None and first["ok"] is True and first["changed"] is True
    repeat = drain_task("t1")
    assert repeat is not None and repeat["ok"] is True
    assert repeat["changed"] is False
    assert repeat["reason"] == "drain already requested"
    assert handle.fired == ["drain"]  # stamped exactly once


def test_drain_task_never_escalates_over_pending_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drain is the weakest rung of the ladder: it can't un-interrupt."""
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    running = _FakeActiveSample(sample_id="s1")
    _patch_active_samples(monkeypatch, [running])

    scored = cancel_task("t1", action="score")
    assert scored is not None and scored["ok"] is True and scored["changed"] is True
    result = drain_task("t1")
    assert result is not None and result["ok"] is True
    assert result["changed"] is False
    assert result["reason"] == "cancel already requested (score)"
    assert handle.fired == ["score"]


def test_score_escalates_over_pending_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The "it's taking too long" relief valve: score interrupts a drain.

    The operator decided to stop waiting — in-flight samples are interrupted
    with the resolution and the task still completes gracefully.
    """
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    running = _FakeActiveSample(sample_id="s1")
    _patch_active_samples(monkeypatch, [running])

    drained = drain_task("t1")
    assert drained is not None and drained["ok"] is True and drained["changed"] is True
    assert running.interrupts == []
    escalated = cancel_task("t1", action="score")
    assert escalated is not None and escalated["ok"] is True
    assert escalated["changed"] is True
    assert handle.fired == ["drain", "score"]
    assert running.interrupts == ["score"]


def test_abort_escalates_over_pending_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Teardown must always remain reachable: force is spelled `task cancel`."""
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    _patch_active_samples(monkeypatch, [])

    drained = drain_task("t1")
    assert drained is not None and drained["ok"] is True and drained["changed"] is True
    escalated = cancel_task("t1")
    assert escalated is not None and escalated["ok"] is True
    assert escalated["changed"] is True
    assert handle.fired == ["drain", "abort"]


def test_drain_task_between_attempts_abandons_pending_retry() -> None:
    """Drain of a between-attempts task abandons the retry, like cancel.

    The retry attempt is new dispatch, which drain forbids; "finish with
    what you have" means the existing error log.
    """
    handle = _FakeTaskCancel(can_retry=True)
    register_eval("e1", 1, task_id="t1", will_retry=True, task_cancel=handle)
    record_sample_errored("e1")
    mark_eval_retry_pending("e1")

    result = drain_task("t1")
    assert result is not None and result["ok"] is True
    assert result["changed"] is True and result.get("retry_abandoned") is True
    assert task_retry_abandoned("t1")
    state = get_eval_state("e1")
    assert state is not None
    assert state.retry_pending is False and state.will_retry is False

    repeat = drain_task("t1")
    assert repeat is not None and repeat["ok"] is True
    assert repeat["changed"] is False
    assert repeat["reason"] == "pending retry already abandoned"


def test_drain_task_pending_retry_abandons_requested_retry() -> None:
    """Drain in the tearing-down window (pending "retry" stamp) sticks."""
    handle = _FakeTaskCancel(can_retry=True)
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    handle.cancel_task("retry")

    result = drain_task("t1")
    assert result is not None and result["ok"] is True
    assert result["changed"] is True and result.get("retry_abandoned") is True
    assert task_retry_abandoned("t1")
    assert handle.fired == ["retry"]  # the attempt itself is untouched


def test_drain_task_running_without_handle_rejected() -> None:
    register_eval("e1", 5, task_id="t1")
    result = drain_task("t1")
    assert result is not None
    assert result["ok"] is False and "not cancellable" in result["error"]


# ---------------------------------------------------------------------------
# cancel_sample directive
# ---------------------------------------------------------------------------


async def test_cancel_sample_interrupts_with_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = _FakeActiveSample()
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert result["sample_id"] == "s1" and result["epoch"] == 1
    assert result["action"] == "score"
    assert sample.interrupts == ["score"]


async def test_cancel_sample_matches_integer_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = _FakeActiveSample(sample_id=7)
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_sample("e1", "7", 1)
    assert result is not None and result["ok"] is True and result["changed"] is True
    assert result["sample_id"] == 7
    assert sample.interrupts == ["score"]


async def test_cancel_sample_error_action(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = _FakeActiveSample(fails_on_error=False)
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_sample("e1", "s1", 1, action="error")
    assert result is not None and result["ok"] is True and result["changed"] is True
    assert sample.interrupts == ["error"]


async def test_cancel_sample_cancel_action(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = _FakeActiveSample()
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_sample("e1", "s1", 1, action="cancel")
    assert result is not None and result["ok"] is True and result["changed"] is True
    assert result["action"] == "cancel"
    assert sample.interrupts == ["cancel"]


async def test_cancel_sample_cancel_action_not_gated_by_fails_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fail-on-error gate does not apply to the 'cancel' action.

    'cancel' bypasses error handling entirely, and the gate exists only
    because the auto-fail would race a manual 'error'.
    """
    sample = _FakeActiveSample(fails_on_error=True)
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_sample("e1", "s1", 1, action="cancel")
    assert result is not None and result["ok"] is True and result["changed"] is True
    assert sample.interrupts == ["cancel"]


async def test_cancel_sample_error_action_gated_by_fails_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = _FakeActiveSample(fails_on_error=True)
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_sample("e1", "s1", 1, action="error")
    assert result is not None
    assert result["ok"] is False and "fail on errors" in result["error"]
    assert sample.interrupts == []


async def test_cancel_sample_dry_run_does_not_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = _FakeActiveSample()
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_sample("e1", "s1", 1, dry_run=True)
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert result["dry_run"] is True
    assert sample.interrupts == []


async def test_cancel_sample_initializing_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sample past the queue but not yet running (ActiveSample, started=None).

    The message says "initializing", not "queued" — this sample has left the
    queue, and the genuinely-queued flavors never reach this check.
    """
    sample = _FakeActiveSample(started=None)
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is False and "initializing" in result["error"]
    assert sample.interrupts == []


async def test_cancel_sample_terminal_is_idempotent_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sample that already finished reports a clean no-op, not an error."""
    from inspect_ai.log._log import EvalSample

    _patch_active_samples(monkeypatch, [])

    async def _read(
        id: str | int, epoch: int, *, exclude_fields: set[str] | None = None
    ) -> EvalSample:
        return EvalSample(id="s1", epoch=1, input="q", target="a")

    register_eval("e1", 1, task_id="t1", live=FakeLiveEvalData(sample=_read))

    result = await cancel_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is True and result["changed"] is False
    assert result["status"] == "completed"


async def test_cancel_sample_unknown_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_active_samples(monkeypatch, [])
    assert await cancel_sample("e1", "s1", 1) is None


async def test_cancel_sample_epoch_must_match(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = _FakeActiveSample(epoch=2)
    _patch_active_samples(monkeypatch, [sample])

    assert await cancel_sample("e1", "s1", 1) is None
    assert sample.interrupts == []


# ---------------------------------------------------------------------------
# cancel_tool_call directive
# ---------------------------------------------------------------------------


def _pending_model_event() -> Any:
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.model import GenerateConfig, ModelOutput

    return ModelEvent(
        model="mockllm/model",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("mockllm/model", ""),
        pending=True,
    )


def _pending_tool_event(
    id: str = "tc1", function: str = "bash", *, fired: list[str] | None = None
) -> Any:
    """A pending ``ToolEvent`` whose cancel fn records into ``fired``.

    ``fired=None`` builds an event with no cancel fn installed (the
    defensive 409 row).
    """
    from inspect_ai.event._tool import ToolEvent

    event = ToolEvent(id=id, function=function, arguments={}, pending=True)
    if fired is not None:
        event._set_cancel_fn(lambda: fired.append(id))
    return event


async def test_cancel_tool_call_explicit_id_fires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fired: list[str] = []
    events = [
        _pending_tool_event("tc1", "bash", fired=fired),
        _pending_tool_event("tc2", "python", fired=fired),
    ]
    sample = _FakeActiveSample(pending_events=events)
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_tool_call("e1", "s1", 1, tool_call_id="tc2")
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert result["sample_id"] == "s1" and result["epoch"] == 1
    assert result["tool_call_id"] == "tc2" and result["function"] == "python"
    assert result["started_at"] is not None
    assert result["running_time"] >= 0.0
    # only the targeted call's scope fired; the sibling is undisturbed
    assert fired == ["tc2"]
    assert events[0].cancelled is False and events[1].cancelled is True


async def test_cancel_tool_call_sole_pending_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no id, exactly one pending tool call is an unambiguous target.

    The response echoes what was cancelled so a wrong target (the hung call
    completing and a fresh one starting in the read-to-mutate window) is
    visible rather than silent.
    """
    fired: list[str] = []
    sample = _FakeActiveSample(
        pending_events=[_pending_tool_event("tc1", "bash", fired=fired)]
    )
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_tool_call("e1", "s1", 1)
    assert result is not None and result["ok"] is True and result["changed"] is True
    assert result["tool_call_id"] == "tc1" and result["function"] == "bash"
    assert fired == ["tc1"]


async def test_cancel_tool_call_sole_pending_ignores_non_tool_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pending model event (e.g. a nested generate) never blocks the fallback."""
    fired: list[str] = []
    model_event = _pending_model_event()
    sample = _FakeActiveSample(
        pending_events=[model_event, _pending_tool_event("tc1", fired=fired)]
    )
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_tool_call("e1", "s1", 1)
    assert result is not None and result["ok"] is True and result["changed"] is True
    assert result["tool_call_id"] == "tc1"
    assert fired == ["tc1"]


async def test_cancel_tool_call_ambiguous_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two or more pending with no id is a rejection enumerating them.

    A mutation must not guess among targets — and per the no-fan-out
    convention must not cancel them all (the TUI's fan-out shape is
    deliberately not carried over).
    """
    fired: list[str] = []
    sample = _FakeActiveSample(
        pending_events=[
            _pending_tool_event("tc1", "bash", fired=fired),
            _pending_tool_event("tc2", "python", fired=fired),
        ]
    )
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_tool_call("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is False and "2 pending tool calls" in result["error"]
    assert [p["id"] for p in result["pending"]] == ["tc1", "tc2"]
    assert result["pending"][0]["function"] == "bash"
    assert result["pending"][0]["cancel_requested"] is False
    assert fired == []  # nothing was cancelled


async def test_cancel_tool_call_repeat_is_idempotent_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A repeat reports "cancel already requested" without re-firing.

    Checked before ``_cancel()``, so — unlike ACP's post-state-only return —
    the response distinguishes "this request cancelled it" from "already
    cancelled" (which also flags a wedged call the cancel could not stop).
    """
    fired: list[str] = []
    sample = _FakeActiveSample(pending_events=[_pending_tool_event("tc1", fired=fired)])
    _patch_active_samples(monkeypatch, [sample])

    first = await cancel_tool_call("e1", "s1", 1)
    assert first is not None and first["ok"] is True and first["changed"] is True
    repeat = await cancel_tool_call("e1", "s1", 1, tool_call_id="tc1")
    assert repeat is not None
    assert repeat["ok"] is True and repeat["changed"] is False
    assert repeat["reason"] == "cancel already requested"
    assert repeat["tool_call_id"] == "tc1"
    assert fired == ["tc1"]  # fired exactly once


async def test_cancel_tool_call_unmatched_id_is_noop_with_pending_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit id with no pending match is the honest already-holds no-op.

    The call is not running (completed, or never existed — the pending scan
    cannot cheaply distinguish); the pending list in the response makes a
    typo'd id visible rather than silently absorbed.
    """
    fired: list[str] = []
    sample = _FakeActiveSample(
        pending_events=[_pending_tool_event("tc1", "bash", fired=fired)]
    )
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_tool_call("e1", "s1", 1, tool_call_id="nope")
    assert result is not None
    assert result["ok"] is True and result["changed"] is False
    assert result["reason"] == "no pending tool call with that id"
    assert [p["id"] for p in result["pending"]] == ["tc1"]
    assert fired == []


async def test_cancel_tool_call_zero_pending_noop_carries_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No pending tool calls no-ops with the sample's current activity.

    The operator learns in one round trip that the sample is stuck
    *elsewhere* (here: a pending model generation).
    """
    sample = _FakeActiveSample(pending_events=[_pending_model_event()])
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_tool_call("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is True and result["changed"] is False
    assert result["reason"] == "no pending tool calls"
    activity = result["activity"]
    assert activity is not None and activity["type"] == "model"


async def test_cancel_tool_call_no_cancel_fn_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pending match with no cancel hook is an honest rejection.

    ``_cancel()`` would silently no-op — the desired end state will not come
    to pass, so a success-shaped answer would be a lie. Defensive: production
    dispatch installs the fn before the event reaches the transcript.
    """
    sample = _FakeActiveSample(pending_events=[_pending_tool_event("tc1")])
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_tool_call("e1", "s1", 1, tool_call_id="tc1")
    assert result is not None
    assert result["ok"] is False and "cannot be cancelled" in result["error"]


async def test_cancel_tool_call_dry_run_does_not_fire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fired: list[str] = []
    events = [_pending_tool_event("tc1", "bash", fired=fired)]
    sample = _FakeActiveSample(pending_events=events)
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_tool_call("e1", "s1", 1, dry_run=True)
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert result["dry_run"] is True
    assert result["tool_call_id"] == "tc1"  # the would-be target is reported
    assert fired == [] and events[0].cancelled is False


async def test_cancel_tool_call_dry_run_reports_ambiguity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject rows report under dry-run too — a probing agent sees the real answer."""
    fired: list[str] = []
    sample = _FakeActiveSample(
        pending_events=[
            _pending_tool_event("tc1", fired=fired),
            _pending_tool_event("tc2", fired=fired),
        ]
    )
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_tool_call("e1", "s1", 1, dry_run=True)
    assert result is not None and result["ok"] is False
    assert [p["id"] for p in result["pending"]] == ["tc1", "tc2"]
    assert fired == []


async def test_cancel_tool_call_terminal_sample_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.log._log import EvalSample

    _patch_active_samples(monkeypatch, [])

    async def _read(
        id: str | int, epoch: int, *, exclude_fields: set[str] | None = None
    ) -> EvalSample:
        return EvalSample(id="s1", epoch=1, input="q", target="a")

    register_eval("e1", 1, task_id="t1", live=FakeLiveEvalData(sample=_read))

    result = await cancel_tool_call("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is True and result["changed"] is False
    assert result["reason"] == "sample already finished"
    assert result["status"] == "completed"


async def test_cancel_tool_call_unknown_sample_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_samples(monkeypatch, [])
    assert await cancel_tool_call("e1", "s1", 1) is None


async def test_cancel_tool_call_epoch_must_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fired: list[str] = []
    sample = _FakeActiveSample(
        epoch=2, pending_events=[_pending_tool_event("tc1", fired=fired)]
    )
    _patch_active_samples(monkeypatch, [sample])

    assert await cancel_tool_call("e1", "s1", 1) is None
    assert fired == []


# ---------------------------------------------------------------------------
# Server routes
# ---------------------------------------------------------------------------


def _app() -> Any:
    from inspect_ai._control.server import ControlServer

    return ControlServer(run_id="test")._build_app()


async def test_task_cancel_route_ok_404_and_409() -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    register_eval("e2", 5, task_id="t2")  # running, but no cancel handle

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        ok = await client.post("/tasks/t1/cancel")
        assert ok.status_code == 200, ok.text
        assert ok.json()["changed"] is True
        assert handle.fired == ["abort"]

        repeat = await client.post("/tasks/t1/cancel")
        assert repeat.status_code == 200
        assert repeat.json()["changed"] is False

        missing = await client.post("/tasks/missing/cancel")
        assert missing.status_code == 404

        rejected = await client.post("/tasks/t2/cancel")
        assert rejected.status_code == 409
        assert "not cancellable" in rejected.json()["error"]


async def test_task_cancel_route_action(monkeypatch: pytest.MonkeyPatch) -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    running = _FakeActiveSample(sample_id="s1")
    _patch_active_samples(monkeypatch, [running])

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        bad = await client.post("/tasks/t1/cancel", params={"action": "explode"})
        assert bad.status_code == 400
        assert "action" in bad.json()["error"]
        assert handle.fired == []

        ok = await client.post("/tasks/t1/cancel", params={"action": "score"})
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body["changed"] is True and body["action"] == "score"
        assert handle.fired == ["score"]
        assert running.interrupts == ["score"]


async def test_task_cancel_route_between_attempts() -> None:
    """A plain cancel abandons the pending retry; score/error still 409."""
    handle = _FakeTaskCancel(can_retry=True)
    register_eval("e1", 1, task_id="t1", will_retry=True, task_cancel=handle)
    record_sample_errored("e1")
    mark_eval_retry_pending("e1")

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        rejected = await client.post("/tasks/t1/cancel", params={"action": "score"})
        assert rejected.status_code == 409
        assert "between attempts" in rejected.json()["error"]

        abandoned = await client.post("/tasks/t1/cancel")
        assert abandoned.status_code == 200, abandoned.text
        body = abandoned.json()
        assert body["changed"] is True and body["retry_abandoned"] is True
        assert task_retry_abandoned("t1")


async def test_task_drain_route_ok_404_noop() -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        ok = await client.post("/tasks/t1/drain")
        assert ok.status_code == 200, ok.text
        assert ok.json()["changed"] is True
        assert handle.fired == ["drain"]

        repeat = await client.post("/tasks/t1/drain")
        assert repeat.status_code == 200
        body = repeat.json()
        assert body["changed"] is False
        assert body["reason"] == "drain already requested"

        missing = await client.post("/tasks/missing/drain")
        assert missing.status_code == 404


async def test_task_drain_route_dry_run() -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        dry = await client.post("/tasks/t1/drain", params={"dry_run": True})
        assert dry.status_code == 200, dry.text
        body = dry.json()
        assert body["changed"] is True and body["dry_run"] is True
        assert handle.fired == []


async def test_task_drain_route_rejection_409() -> None:
    # running (not finished) state with no cancel handle can't be drained
    register_eval("e1", 5, task_id="t1")

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        rejected = await client.post("/tasks/t1/drain")
        assert rejected.status_code == 409
        assert "not cancellable" in rejected.json()["error"]


async def test_task_cancel_route_dry_run() -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        dry = await client.post("/tasks/t1/cancel", params={"dry_run": True})
        assert dry.status_code == 200, dry.text
        body = dry.json()
        assert body["changed"] is True and body["dry_run"] is True
        assert handle.fired == []


async def test_sample_cancel_route(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = _FakeActiveSample()
    _patch_active_samples(monkeypatch, [sample])
    register_eval("e1", 1, task_id="t1")

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        ok = await client.post(
            "/evals/e1/sample/cancel", params={"sample_id": "s1", "epoch": 1}
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["changed"] is True
        assert sample.interrupts == ["score"]

        missing = await client.post(
            "/evals/e1/sample/cancel", params={"sample_id": "nope", "epoch": 1}
        )
        assert missing.status_code == 404

        bad_action = await client.post(
            "/evals/e1/sample/cancel",
            params={"sample_id": "s1", "epoch": 1, "action": "explode"},
        )
        assert bad_action.status_code == 400
        assert "score" in bad_action.json()["error"]

        # epoch is required on this mutation — a defaulted epoch would
        # silently target the epoch-1 attempt on a multi-epoch task
        no_epoch = await client.post(
            "/evals/e1/sample/cancel", params={"sample_id": "s1"}
        )
        assert no_epoch.status_code == 400
        assert "epoch is required" in no_epoch.json()["error"]
        assert sample.interrupts == ["score"]  # only the first call fired


async def test_sample_cancel_route_cancel_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = _FakeActiveSample()
    _patch_active_samples(monkeypatch, [sample])
    register_eval("e1", 1, task_id="t1")

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        ok = await client.post(
            "/evals/e1/sample/cancel",
            params={"sample_id": "s1", "epoch": 1, "action": "cancel"},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["changed"] is True
        assert sample.interrupts == ["cancel"]


async def test_sample_cancel_route_gates_error_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = _FakeActiveSample(fails_on_error=True)
    _patch_active_samples(monkeypatch, [sample])

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        rejected = await client.post(
            "/evals/e1/sample/cancel",
            params={"sample_id": "s1", "epoch": 1, "action": "error"},
        )
        assert rejected.status_code == 409
        assert sample.interrupts == []


async def test_sample_cancel_tool_call_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fired: list[str] = []
    sample = _FakeActiveSample(
        pending_events=[_pending_tool_event("tc1", "bash", fired=fired)]
    )
    _patch_active_samples(monkeypatch, [sample])
    register_eval("e1", 1, task_id="t1")

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        # epoch is required on this mutation — a defaulted epoch would
        # silently target the epoch-1 attempt on a multi-epoch task
        no_epoch = await client.post(
            "/evals/e1/sample/cancel-tool-call", params={"sample_id": "s1"}
        )
        assert no_epoch.status_code == 400
        assert "epoch is required" in no_epoch.json()["error"]
        assert fired == []

        ok = await client.post(
            "/evals/e1/sample/cancel-tool-call",
            params={"sample_id": "s1", "epoch": 1, "tool_call_id": "tc1"},
        )
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body["changed"] is True and body["tool_call_id"] == "tc1"
        assert fired == ["tc1"]

        repeat = await client.post(
            "/evals/e1/sample/cancel-tool-call",
            params={"sample_id": "s1", "epoch": 1, "tool_call_id": "tc1"},
        )
        assert repeat.status_code == 200
        assert repeat.json()["changed"] is False
        assert repeat.json()["reason"] == "cancel already requested"

        missing = await client.post(
            "/evals/e1/sample/cancel-tool-call",
            params={"sample_id": "nope", "epoch": 1},
        )
        assert missing.status_code == 404


async def test_sample_cancel_tool_call_route_ambiguous_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fired: list[str] = []
    sample = _FakeActiveSample(
        pending_events=[
            _pending_tool_event("tc1", "bash", fired=fired),
            _pending_tool_event("tc2", "python", fired=fired),
        ]
    )
    _patch_active_samples(monkeypatch, [sample])
    register_eval("e1", 1, task_id="t1")

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        rejected = await client.post(
            "/evals/e1/sample/cancel-tool-call",
            params={"sample_id": "s1", "epoch": 1},
        )
        assert rejected.status_code == 409
        body = rejected.json()
        assert "pending tool calls" in body["error"]
        # the pending calls ride structurally so a scripted caller can pick
        # an id without a second read
        assert [p["id"] for p in body["pending"]] == ["tc1", "tc2"]
        assert fired == []


def test_register_eval_carries_task_cancel() -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    state = get_eval_state("e1")
    assert state is not None and state.task_cancel is handle


# ---------------------------------------------------------------------------
# Queued-sample cancel (design/ctl/queued-sample-cancel.md): decision table
# ---------------------------------------------------------------------------


def _row(result: "CancelSampleResult | None") -> dict[str, Any]:
    """Assert a non-404 ``cancel_sample`` result and index it loosely.

    The queued-row tests read fields across the result union's variants
    (``status``/``reason`` on accepts and no-ops, ``error`` on rejections);
    the cast trades mypy's per-variant key checking for readable
    assertions — the values themselves are still asserted exactly.
    """
    assert result is not None
    return cast(dict[str, Any], result)


def _errored_prior(sample_id: str = "s1", epoch: int = 1) -> EvalSample:
    from inspect_ai._util.error import EvalError

    return EvalSample(
        id=sample_id,
        epoch=epoch,
        input="q",
        target="a",
        error=EvalError(message="boom", traceback="", traceback_ansi=""),
        uuid="prior-uuid",
    )


def _register_queued_eval(
    *,
    eval_id: str = "e1",
    total: int = 2,
    sample_ids: list[str | int] | None = None,
    epochs: int = 1,
    task_cancel: TaskCancel | None = None,
    error_count: int = 0,
) -> SampleRequeue:
    """Register an eval with a *real* requeue handle (real scheduler)."""
    register_eval(
        eval_id,
        total,
        task_id="t1",
        task="my_task",
        sample_ids=sample_ids if sample_ids is not None else ["s1", "s2"],
        epochs=epochs,
        task_cancel=task_cancel,
    )
    handler = SampleErrorHandler(False, total)
    handler.error_count = error_count
    handle = SampleRequeue(
        eval_id=eval_id,
        scheduler=SampleScheduler(),
        sample_error=handler,
        sample_indexes={"s1": 0, "s2": 1},
        checkpoints_dir=None,
        on_accept=lambda sample_id, epoch: None,
        on_withdraw=lambda sample_id, epoch, score: None,
    )
    set_sample_requeue(eval_id, handle)
    return handle


def _arrive(handle: SampleRequeue, sample_id: str | int, epoch: int = 1) -> _SampleRun:
    """Stamp a seed run's queue arrival (what the runner's enter hook does)."""
    run = _SampleRun(sample_index=0, epoch=epoch)
    handle.queue_arrive(sample_id, epoch, run)
    return run


async def test_cancel_never_started_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sample parked at the queue is cancelled before start.

    Counted `cancelled` synchronously at accept; a repeat is the idempotent
    "already cancelled" no-op; score/error keep rejecting.
    """
    _patch_active_samples(monkeypatch, [])
    handle = _register_queued_eval()
    _arrive(handle, "s2")

    # dry run reports the accept without mutating, with a conditional-tense
    # reason (the CLI's "Would cancel …" line interpolates it verbatim)
    dry = _row(await cancel_sample("e1", "s2", 1, action="cancel", dry_run=True))
    assert dry["ok"] is True and dry["changed"] is True
    assert dry["status"] == "cancelled"
    assert "would be cancelled" in dry["reason"]
    assert handle.sample_view("s2", 1).cancelled is None
    state = get_eval_state("e1")
    assert state is not None and state.cancelled == 0

    result = _row(await cancel_sample("e1", "s2", 1, action="cancel"))
    assert result["ok"] is True and result["changed"] is True
    assert result["status"] == "cancelled"
    assert "before start" in result["reason"]
    assert handle.sample_view("s2", 1).cancelled == "parked"
    assert state.cancelled == 1

    repeat = await cancel_sample("e1", "s2", 1, action="cancel")
    assert repeat is not None
    assert repeat["ok"] is True and repeat["changed"] is False
    assert repeat["reason"] == "already cancelled"
    assert state.cancelled == 1  # not double-counted

    # score/error have nothing to act on — a row-specific 409 (the parked
    # rows' "--action cancel" hint would just point at the no-op above)
    for action in ("score", "error"):
        rejected = await cancel_sample("e1", "s2", 1, action=action)
        assert rejected is not None
        assert rejected["ok"] is False
        assert "was cancelled before it started" in rejected["error"]
        assert "--action cancel" not in rejected["error"]


async def test_cancel_never_started_score_error_409_when_parked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """score/error on a parked (not yet cancelled) sample reject truthfully."""
    _patch_active_samples(monkeypatch, [])
    handle = _register_queued_eval()
    _arrive(handle, "s2")

    for action in ("score", "error"):
        rejected = await cancel_sample("e1", "s2", 1, action=action)
        assert rejected is not None
        assert rejected["ok"] is False and "--action cancel" in rejected["error"]
    assert handle.sample_view("s2", 1).cancelled is None


async def test_cancel_not_at_queue_409(monkeypatch: pytest.MonkeyPatch) -> None:
    """A planned sample with no arrival stamp gets the retryable 409, not a 404.

    This is the reuse-in-flight window on a retry attempt (and a seed's
    first tick): the sample may never queue at all, so cancel must not
    accept — and score/error get the same truthful answer.
    """
    _patch_active_samples(monkeypatch, [])
    handle = _register_queued_eval()

    for action in ("cancel", "score", "error"):
        result = await cancel_sample("e1", "s2", 1, action=action)
        assert result is not None, action
        assert result["ok"] is False
        assert "not at the queue yet" in result["error"]
    assert handle.sample_view("s2", 1).cancelled is None
    state = get_eval_state("e1")
    assert state is not None and state.cancelled == 0


async def test_cancel_departed_blind_window_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run past the queue-exit check but with no ActiveSample yet.

    The departure stamp is what makes this window visible: the accept must
    answer initializing rather than half-cancel a run that will also
    terminal-record on its own.
    """
    _patch_active_samples(monkeypatch, [])
    handle = _register_queued_eval()
    run = _arrive(handle, "s2")
    assert handle.queue_depart(run) is False  # uncancelled exit

    result = await cancel_sample("e1", "s2", 1, action="cancel")
    assert result is not None
    assert result["ok"] is False and "initializing" in result["error"]
    assert handle.sample_view("s2", 1).cancelled is None


async def test_cancel_drain_abandoned_sample_reads_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A drain-abandoned queued sample answers "already cancelled", not "retry".

    A graceful task cancel abandons a still-queued sample at the queue-exit
    check with no record; the abandon stamp is what keeps the outcome
    readable — without it the departed key would advise "retry once it is
    running" forever. Re-runs need no stamp (their pending key clears and
    the prior record renders), so the hook no-ops for them.
    """
    _patch_active_samples(monkeypatch, [])
    cancel = TaskCancel(can_retry=False, cancel_task=lambda _: None)
    handle = _register_queued_eval(task_cancel=cancel)
    run = _arrive(handle, "s2")
    handle.queue_depart(run)
    cancel.cancel_type = "score"  # the graceful drain is in flight
    # the runner's drain-abandon path fires the queue_abandon hook
    handle.queue_abandoned(run)
    assert handle.sample_view("s2", 1).cancelled == "discarded"

    result = await cancel_sample("e1", "s2", 1, action="cancel")
    assert result is not None
    assert result["ok"] is True and result["changed"] is False
    assert result["reason"] == "already cancelled"

    listing = await current_sample_listing("e1")
    rows = {(r["sample_id"], r["epoch"]): r for r in listing.samples}
    assert rows[("s2", 1)]["status"] == "cancelled"

    # a re-run entry is not stamped: its pending key clears via on_terminal
    # and the prior record renders
    rerun = _SampleRun(sample_index=0, epoch=1, prior=_errored_prior())
    handle.queue_abandoned(rerun)
    assert handle.sample_view("s1", 1).cancelled is None


async def test_cancel_departed_task_gates_before_retry_advice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A task-level gate answers a departed key before the "retry" advice.

    Once a task cancel is in flight (or the task has finished) "retry once
    it is running" would be advice with no exit — e.g. an abort abandons the
    departed run, and a completed sample under log_samples=False never gains
    a readable record.
    """
    _patch_active_samples(monkeypatch, [])
    cancel = TaskCancel(can_retry=False, cancel_task=lambda _: None)
    handle = _register_queued_eval(task_cancel=cancel)
    run = _arrive(handle, "s2")
    handle.queue_depart(run)
    cancel.cancel_type = "abort"

    result = await cancel_sample("e1", "s2", 1, action="cancel")
    assert result is not None
    assert result["ok"] is False
    assert "cancel is in flight" in result["error"]
    assert "initializing" not in result["error"]


async def test_cancel_retry_repark_rearrival_cancellable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Arrival overwrites a prior departure (the retry re-park cycle)."""
    _patch_active_samples(monkeypatch, [])
    handle = _register_queued_eval()
    run = _arrive(handle, "s2")
    handle.queue_depart(run)
    handle.queue_arrive("s2", 1, run)  # retry re-park re-arrives

    result = await cancel_sample("e1", "s2", 1, action="cancel")
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert handle.sample_view("s2", 1).cancelled == "parked"


async def test_cancel_queued_rows_task_level_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stamped task cancel closes the queued accept rows."""
    _patch_active_samples(monkeypatch, [])
    cancel = TaskCancel(can_retry=False, cancel_task=lambda _: None)
    cancel.cancel_type = "abort"
    handle = _register_queued_eval(task_cancel=cancel)
    _arrive(handle, "s2")

    result = await cancel_sample("e1", "s2", 1, action="cancel")
    assert result is not None
    assert result["ok"] is False and "cancel is in flight" in result["error"]
    assert handle.sample_view("s2", 1).cancelled is None


async def test_cancel_unknown_sample_still_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_samples(monkeypatch, [])
    _register_queued_eval()
    assert await cancel_sample("e1", "nope", 1, action="cancel") is None
    assert await cancel_sample("e1", "s1", 3, action="cancel") is None


async def test_cancel_before_start_discard_at_queue_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The queue-exit check discards a cancelled run without recording again."""
    _patch_active_samples(monkeypatch, [])
    handle = _register_queued_eval()
    run = _arrive(handle, "s2")
    assert _row(await cancel_sample("e1", "s2", 1, action="cancel"))["changed"]
    state = get_eval_state("e1")
    assert state is not None and state.cancelled == 1

    # the zombie drains: the exit hook reports the cancel (the runner then
    # skips materialization/recording) and flips the key to discarded
    assert handle.queue_depart(run) is True
    assert handle.sample_view("s2", 1).cancelled == "discarded"
    assert state.cancelled == 1  # the discard did not re-count

    # the repeat cancel stays the idempotent no-op after the discard
    repeat = await cancel_sample("e1", "s2", 1, action="cancel")
    assert repeat is not None
    assert repeat["ok"] is True and repeat["changed"] is False


async def test_cancel_before_start_last_outstanding_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling the last outstanding work finishes the eval.

    completed_at stamps and sample_ids clears — and the repeat-cancel no-op
    and the cancelled rendering must not key off the (now empty) planned ids.
    """
    _patch_active_samples(monkeypatch, [])
    handle = _register_queued_eval(total=1, sample_ids=["s1"])
    _arrive(handle, "s1")

    result = _row(await cancel_sample("e1", "s1", 1, action="cancel"))
    assert result["changed"] is True
    state = get_eval_state("e1")
    assert state is not None
    assert state.completed_at is not None and state.sample_ids == []

    repeat = _row(await cancel_sample("e1", "s1", 1, action="cancel"))
    assert repeat["ok"] is True and repeat["changed"] is False
    assert repeat["reason"] == "already cancelled"

    listing = await current_sample_listing("e1")
    row = next(r for r in listing.samples if str(r["sample_id"]) == "s1")
    assert row["status"] == "cancelled"


async def test_cancel_unrequeues_queued_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancel of a queued re-run withdraws the requeue — full reconciliation.

    The prior terminal record stands: bucket and fail-on-error tally are
    restored, the withdrawn entry is flagged (cancelled, on_terminal
    disarmed), the popped score is re-inserted via on_withdraw, and the same
    prior record is requeueable again (the staleness guard forgets its uuid).
    """
    register_eval("e1", 2, task_id="t1", task="my_task", sample_ids=["s1", "s2"])
    record_sample_errored("e1")
    handler = SampleErrorHandler(False, 2)
    handler.error_count = 1
    scheduler = SampleScheduler()
    accepted: list[tuple[str | int, int]] = []
    withdrawn: list[tuple[str | int, int, Any]] = []
    prior_score = {"scorer": "prior-score"}

    def on_accept(sample_id: str | int, epoch: int) -> Any:
        accepted.append((sample_id, epoch))
        return prior_score

    handle = SampleRequeue(
        eval_id="e1",
        scheduler=scheduler,
        sample_error=handler,
        sample_indexes={"s1": 0, "s2": 1},
        checkpoints_dir=None,
        on_accept=on_accept,
        on_withdraw=lambda sample_id, epoch, score: withdrawn.append(
            (sample_id, epoch, score)
        ),
    )
    set_sample_requeue("e1", handle)
    _patch_active_samples(monkeypatch, [])

    prior = _errored_prior()
    rerun_entries: list[_SampleRun] = []
    release = anyio.Event()

    async def run_sample(sample_index: int, epoch: int, entry: _SampleRun) -> Any:
        if entry.prior is not None:
            rerun_entries.append(entry)
            with anyio.fail_after(30):
                await release.wait()
            # mirror the runner's top-of-run check for a withdrawn entry
            return DISCARDED if entry.cancelled else "fresh"
        if sample_index == 0:
            return "failed"
        with anyio.fail_after(30):
            await release.wait()
        return "waited"

    results: dict[tuple[int, int], Any] = {}

    async with anyio.create_task_group() as tg:

        async def go() -> None:
            results.update(await scheduler.run([(0, 1), (1, 1)], run_sample))

        tg.start_soon(go)
        with anyio.fail_after(30):
            while not scheduler.open:
                await anyio.sleep(0.01)

        assert handle.accept(prior, "error") == "accepted"
        state = get_eval_state("e1")
        assert state is not None
        assert state.errored == 0 and handler.error_count == 0
        assert accepted == [("s1", 1)]

        # wait for the dispatcher to start the re-run (so the entry exists)
        with anyio.fail_after(30):
            while not rerun_entries:
                await anyio.sleep(0.01)

        result = _row(await cancel_sample("e1", "s1", 1, action="cancel"))
        assert result["ok"] is True and result["changed"] is True
        assert result["status"] == "error"
        assert "requeue withdrawn" in result["reason"]

        # full inverse reconciliation, synchronously at accept
        assert state.errored == 1 and handler.error_count == 1
        assert not handle.sample_view("s1", 1).pending
        entry = rerun_entries[0]
        assert entry.cancelled is True and entry.on_terminal is None
        assert withdrawn == [("s1", 1, prior_score)]

        # the same prior record is requeueable again (uuid guard restored) —
        # a fresh entry for the same key while the old zombie is still parked
        assert handle.accept(prior, "error") == "accepted"
        assert handle.sample_view("s1", 1).pending

        # the withdrawn zombie draining must not clear the fresh pending key
        # (its on_terminal was disarmed at withdraw)
        release.set()
        with anyio.fail_after(30):
            while len(rerun_entries) < 2:
                await anyio.sleep(0.01)
        # let the fresh re-run finish; the fanout closes
    # the zombie never wrote its (discarded) result; the fresh re-run did
    assert results[(0, 1)] == "fresh"
    assert not handle.sample_view("s1", 1).pending  # cleared by the *fresh* terminal


async def test_cancel_queued_rerun_score_error_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """score/error on a queued re-run reject — nothing to score or record."""
    register_eval("e1", 2, task_id="t1", sample_ids=["s1", "s2"])
    handler = SampleErrorHandler(False, 2)
    scheduler = SampleScheduler()
    handle = SampleRequeue(
        eval_id="e1",
        scheduler=scheduler,
        sample_error=handler,
        sample_indexes={"s1": 0, "s2": 1},
        checkpoints_dir=None,
        on_accept=lambda sample_id, epoch: None,
        on_withdraw=lambda sample_id, epoch, score: None,
    )
    set_sample_requeue("e1", handle)
    _patch_active_samples(monkeypatch, [])

    release = anyio.Event()

    async def run_sample(sample_index: int, epoch: int, entry: _SampleRun) -> Any:
        if sample_index == 0 and entry.prior is None:
            return "failed"
        with anyio.fail_after(30):
            await release.wait()
        return "done"

    async with anyio.create_task_group() as tg:

        async def go() -> None:
            await scheduler.run([(0, 1), (1, 1)], run_sample)

        tg.start_soon(go)
        with anyio.fail_after(30):
            while not scheduler.open:
                await anyio.sleep(0.01)
        record_sample_errored("e1")
        assert handle.accept(_errored_prior(), "error") == "accepted"

        for action in ("score", "error"):
            rejected = await cancel_sample("e1", "s1", 1, action=action)
            assert rejected is not None
            assert rejected["ok"] is False
            assert "--action cancel" in rejected["error"]
        assert handle.sample_view("s1", 1).pending  # nothing was withdrawn

        # dry run reports the un-requeue without mutating, with a
        # conditional-tense reason (the CLI interpolates it verbatim)
        dry = _row(await cancel_sample("e1", "s1", 1, action="cancel", dry_run=True))
        assert dry["ok"] is True and dry["changed"] is True
        assert "would be withdrawn" in dry["reason"]
        assert handle.sample_view("s1", 1).pending

        release.set()


async def test_cancel_unrequeue_departed_window_dry_run_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dry_run reports the departed 409 the real un-requeue would return.

    In the departed blind window (the re-run left the queue, its
    ActiveSample not yet registered) `cancel_queued` refuses — the dry-run
    path must consult the same gate rather than report the accept.
    """
    register_eval("e1", 2, task_id="t1", sample_ids=["s1", "s2"])
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
        on_withdraw=lambda sample_id, epoch, score: None,
    )
    set_sample_requeue("e1", handle)
    _patch_active_samples(monkeypatch, [])

    rerun_entries: list[_SampleRun] = []
    release = anyio.Event()

    async def run_sample(sample_index: int, epoch: int, entry: _SampleRun) -> Any:
        if entry.prior is not None:
            rerun_entries.append(entry)
        elif sample_index == 0:
            return "failed"
        with anyio.fail_after(30):
            await release.wait()
        return "done"

    async with anyio.create_task_group() as tg:

        async def go() -> None:
            await scheduler.run([(0, 1), (1, 1)], run_sample)

        tg.start_soon(go)
        with anyio.fail_after(30):
            while not scheduler.open:
                await anyio.sleep(0.01)
        record_sample_errored("e1")
        assert handle.accept(_errored_prior(), "error") == "accepted"

        with anyio.fail_after(30):
            while not rerun_entries:
                await anyio.sleep(0.01)
        # the re-run exits the queue (the runner's queue-exit stamp) but its
        # ActiveSample has not registered yet: the departed blind window
        assert handle.queue_depart(rerun_entries[0]) is False
        assert handle.sample_view("s1", 1).pending_departed is True

        # every action gets the departed 409 (the departed gate answers
        # before the action gate — otherwise score/error's "use `--action
        # cancel`" advice would immediately 409), and dry_run reports the
        # same answer the real call would
        for action in ("cancel", "score", "error"):
            for dry_run in (True, False):
                result = await cancel_sample(
                    "e1", "s1", 1, action=action, dry_run=dry_run
                )
                assert result is not None, (action, dry_run)
                assert result["ok"] is False, (action, dry_run)
                assert "initializing" in result["error"], (action, dry_run)
                assert "--action cancel" not in result["error"], (action, dry_run)
        assert handle.sample_view("s1", 1).pending  # nothing was withdrawn

        release.set()


async def test_cancel_unrequeued_zombie_rearrival_takes_no_stamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A withdrawn re-run resuming from its seeding awaits takes no queue stamp.

    `run_sample` checks `cancelled` at its top, but a re-run awaits the
    prior's log removal and checkpoint read before the arrival stamp — an
    un-requeue accepted in that window flags the entry, and the zombie's
    late `queue_arrive` must not stamp arrival or take the key: an owning
    zombie would read as a never-started row (`arrived`, not `cancelled`),
    sending a follow-up `--action cancel` into `cancel_before_start`, whose
    prior-less precondition it violates (an AssertionError → 500).
    """
    register_eval("e1", 2, task_id="t1", task="my_task", sample_ids=["s1", "s2"])
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
        on_withdraw=lambda sample_id, epoch, score: None,
    )
    set_sample_requeue("e1", handle)
    _patch_active_samples(monkeypatch, [])

    rerun_entries: list[_SampleRun] = []
    release = anyio.Event()

    async def run_sample(sample_index: int, epoch: int, entry: _SampleRun) -> Any:
        if entry.prior is not None:
            rerun_entries.append(entry)
            # suspended in the seeding awaits, before the arrival stamp
            with anyio.fail_after(30):
                await release.wait()
            # the queue-exit check (the test body stamped the late arrival)
            return DISCARDED if handle.queue_depart(entry) else "fresh"
        if sample_index == 0:
            return "failed"
        # the sibling holds the fanout open for the accept
        with anyio.fail_after(30):
            await release.wait()
        return "other"

    results: dict[tuple[int, int], Any] = {}

    async with anyio.create_task_group() as tg:

        async def go() -> None:
            results.update(await scheduler.run([(0, 1), (1, 1)], run_sample))

        tg.start_soon(go)
        with anyio.fail_after(30):
            while not scheduler.open:
                await anyio.sleep(0.01)
        assert handle.accept(_errored_prior(), "error") == "accepted"
        with anyio.fail_after(30):
            while not rerun_entries:
                await anyio.sleep(0.01)

        # un-requeue accepted while the re-run sits in its seeding awaits
        result = _row(await cancel_sample("e1", "s1", 1, action="cancel"))
        assert result["ok"] is True and result["changed"] is True
        entry = rerun_entries[0]
        assert entry.cancelled is True

        # the zombie resumes and stamps arrival (task_run_sample's enter
        # hook): no stamp, no ownership
        handle.queue_arrive("s1", 1, entry)
        view = handle.sample_view("s1", 1)
        assert view.queue is None and view.cancelled is None

        # a follow-up cancel must not misread the key as a never-started
        # row (pre-guard: dry_run reported the false accept; the real call
        # hit cancel_before_start's assert)
        for dry_run in (True, False):
            followup = await cancel_sample(
                "e1", "s1", 1, action="cancel", dry_run=dry_run
            )
            assert followup is not None, dry_run
            assert followup["ok"] is False, dry_run
            assert "not at the queue yet" in followup["error"], dry_run

        release.set()
    # the zombie discarded at the queue exit without overwriting the seed
    assert results[(0, 1)] == "failed"


async def test_scheduler_discarded_result_never_written() -> None:
    """run_one skips the results write for a DISCARDED run."""
    scheduler = SampleScheduler()

    async def run_sample(sample_index: int, epoch: int, entry: _SampleRun) -> Any:
        return DISCARDED if sample_index == 0 else "ok"

    results = await scheduler.run([(0, 1), (1, 1)], run_sample)
    assert results == {(1, 1): "ok"}


async def test_listing_and_show_render_cancelled_before_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancelled-before-start key renders `cancelled` (not `pending`)."""
    _patch_active_samples(monkeypatch, [])
    handle = _register_queued_eval()
    _arrive(handle, "s2")
    assert _row(await cancel_sample("e1", "s2", 1, action="cancel"))["changed"]

    listing = await current_sample_listing("e1")
    rows = {(r["sample_id"], r["epoch"]): r for r in listing.samples}
    assert rows[("s2", 1)]["status"] == "cancelled"
    assert rows[("s1", 1)]["status"] == "pending"  # the sibling is untouched
    # the histogram is tallied from the rendered rows, so the new row rule
    # is what corrects it
    assert listing.counts["cancelled"] == 1 and listing.counts["pending"] == 1

    detail = await sample_error_detail("e1", "s2", 1)
    assert detail is not None
    assert detail["status"] == "cancelled"
    assert detail["error"] is None and detail["error_retries"] == []


async def test_cancelled_before_start_rows_keep_typed_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelled rows echo the dataset-typed id, even after the eval finishes.

    The typed id is captured at queue arrival, so `sample show` and the
    listing agree with the planned rows (int, not the route string) — and
    keep agreeing after the last-outstanding-work carve-out clears
    `sample_ids` (the old recovery source).
    """
    _patch_active_samples(monkeypatch, [])
    register_eval("e1", 1, task_id="t1", task="my_task", sample_ids=[5], epochs=1)
    handle = SampleRequeue(
        eval_id="e1",
        scheduler=SampleScheduler(),
        sample_error=SampleErrorHandler(False, 1),
        sample_indexes={"5": 0},
        checkpoints_dir=None,
        on_accept=lambda sample_id, epoch: None,
        on_withdraw=lambda sample_id, epoch, score: None,
    )
    set_sample_requeue("e1", handle)
    # the runner passes the dataset-typed id at arrival
    handle.queue_arrive(5, 1, _SampleRun(sample_index=0, epoch=1))

    result = _row(await cancel_sample("e1", "5", 1, action="cancel"))
    assert result["changed"] is True
    assert result["sample_id"] == 5 and isinstance(result["sample_id"], int)

    # the cancel finished the eval: sample_ids has cleared, but the row and
    # the detail keep the captured int id
    state = get_eval_state("e1")
    assert state is not None
    assert state.completed_at is not None and state.sample_ids == []

    listing = await current_sample_listing("e1")
    row = next(r for r in listing.samples if r["epoch"] == 1)
    assert row["sample_id"] == 5 and isinstance(row["sample_id"], int)
    assert row["status"] == "cancelled"

    detail = await sample_error_detail("e1", "5", 1)
    assert detail is not None
    assert detail["sample_id"] == 5 and isinstance(detail["sample_id"], int)
    assert detail["status"] == "cancelled"


# ---------------------------------------------------------------------------
# End to end: queued-sample cancel through a live eval
# ---------------------------------------------------------------------------

_E2E_RUNS: dict[str, int] = {}
_E2E_RELEASE: anyio.Event | None = None
_E2E_FAIL_FIRST: set[str] = set()


@solver
def _park_or_fail_probe():
    """Counts runs per sample; fails or parks them.

    Ids in _E2E_FAIL_FIRST raise on their first attempt; everything else
    parks until released.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sample_id = str(state.sample_id)
        _E2E_RUNS[sample_id] = _E2E_RUNS.get(sample_id, 0) + 1
        if sample_id in _E2E_FAIL_FIRST and _E2E_RUNS[sample_id] == 1:
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


def _e2e_task(name: str) -> Task:
    return Task(
        dataset=[
            Sample(id="first", input="x", target="y"),
            Sample(id="second", input="x", target="y"),
        ],
        solver=_park_or_fail_probe(),
        scorer=_always_correct(),
        name=name,
    )


async def _wait_for_eval() -> str:
    with anyio.fail_after(60):
        while True:
            states = get_eval_states()
            if states:
                return states[0].eval_id
            await anyio.sleep(0.01)


async def _wait_cancellable(eval_id: str, sample_id: str, epoch: int = 1) -> None:
    """Poll a dry-run cancel until the sample reads as at-the-queue.

    Requires the queued-row probe shape (status "cancelled" + before-start
    reason) — a running sample's interrupt row also reports changed=True but
    carries no status, and matching it would make the follow-up real cancel
    interrupt a running sample instead of exercising the queued row.
    """
    with anyio.fail_after(60):
        while True:
            probe = await cancel_sample(
                eval_id, sample_id, epoch, action="cancel", dry_run=True
            )
            if (
                probe is not None
                and probe.get("ok")
                and probe.get("changed")
                and probe.get("status") == "cancelled"
            ):
                return
            await anyio.sleep(0.01)


async def _wait_one_running_pick_parked() -> str:
    """Wait until one sample holds the single slot; return the parked one.

    With ``max_samples=1`` either seed can win the slot (backend scheduling
    differs between asyncio and trio), so the tests pick the parked sample
    dynamically rather than assuming an order.
    """
    with anyio.fail_after(60):
        while not _E2E_RUNS:
            await anyio.sleep(0.01)
    running = next(iter(_E2E_RUNS))
    return "second" if running == "first" else "first"


async def test_cancel_before_start_end_to_end() -> None:
    """A parked seed is cancelled before start: counted, absent from the log."""
    global _E2E_RELEASE
    _E2E_RUNS.clear()
    _E2E_FAIL_FIRST.clear()
    _E2E_RELEASE = anyio.Event()

    init_display_type("none")
    logs: list[Any] = []

    async with anyio.create_task_group() as tg:

        async def run_eval() -> None:
            logs.extend(
                await eval_async(
                    _e2e_task("cancel_before_start_e2e"),
                    model="mockllm/model",
                    fail_on_error=False,
                    ctl_server=False,
                    max_samples=1,  # the loser parks at the sample semaphore
                )
            )

        tg.start_soon(run_eval)
        eval_id = await _wait_for_eval()
        parked = await _wait_one_running_pick_parked()
        running = "second" if parked == "first" else "first"
        await _wait_cancellable(eval_id, parked)

        result = await cancel_sample(eval_id, parked, 1, action="cancel")
        assert result is not None
        assert result["ok"] is True and result["changed"] is True

        state = get_eval_state(eval_id)
        assert state is not None and state.cancelled == 1

        listing = await current_sample_listing(eval_id)
        row = next(r for r in listing.samples if str(r["sample_id"]) == parked)
        assert row["status"] == "cancelled"

        _E2E_RELEASE.set()

    assert _E2E_RUNS == {running: 1}  # the cancelled sample never ran

    (log,) = logs
    assert log.status == "success"
    log = await read_eval_log_async(log.location)
    assert log.samples is not None
    # absent from the log — the drain-precedent treatment of queued samples
    assert [str(s.id) for s in log.samples] == [running]


async def test_cancel_before_start_then_uncancel_end_to_end() -> None:
    """Requeue un-cancels a parked cancel-before-start; the sample runs."""
    global _E2E_RELEASE
    _E2E_RUNS.clear()
    _E2E_FAIL_FIRST.clear()
    _E2E_RELEASE = anyio.Event()

    init_display_type("none")
    logs: list[Any] = []

    async with anyio.create_task_group() as tg:

        async def run_eval() -> None:
            logs.extend(
                await eval_async(
                    _e2e_task("uncancel_e2e"),
                    model="mockllm/model",
                    fail_on_error=False,
                    ctl_server=False,
                    max_samples=1,
                )
            )

        tg.start_soon(run_eval)
        eval_id = await _wait_for_eval()
        parked = await _wait_one_running_pick_parked()
        await _wait_cancellable(eval_id, parked)

        assert _row(await cancel_sample(eval_id, parked, 1, action="cancel"))["changed"]
        state = get_eval_state(eval_id)
        assert state is not None and state.cancelled == 1

        # un-cancel via requeue: the same parked coroutine serves as the run
        uncancel = await requeue_sample(eval_id, parked, 1)
        assert uncancel is not None
        assert uncancel["ok"] is True and uncancel["changed"] is True
        assert uncancel["status"] == "pending"
        assert state.cancelled == 0

        _E2E_RELEASE.set()

    assert _E2E_RUNS == {"first": 1, "second": 1}

    (log,) = logs
    assert log.status == "success"
    log = await read_eval_log_async(log.location)
    assert log.samples is not None
    assert sorted(str(s.id) for s in log.samples) == ["first", "second"]
    assert all(s.error is None for s in log.samples)


async def test_cancel_unrequeue_end_to_end() -> None:
    """Cancel of a queued re-run withdraws it; the prior record stands.

    The task's dispatch gate is paused before the requeue, so the re-run
    deterministically stays queued while the cancel withdraws it.
    """
    from inspect_ai._control.pause import pause_task, resume_task

    global _E2E_RELEASE, _E2E_FAIL
    _E2E_RUNS.clear()
    _E2E_RELEASE = anyio.Event()
    _E2E_FAIL = anyio.Event()

    init_display_type("none")
    logs: list[Any] = []

    async with anyio.create_task_group() as tg:

        async def run_eval() -> None:
            logs.extend(
                await eval_async(
                    Task(
                        dataset=[
                            Sample(id="first", input="x", target="y"),
                            Sample(id="second", input="x", target="y"),
                        ],
                        solver=_fail_on_signal_probe(),
                        scorer=_always_correct(),
                        name="unrequeue_e2e",
                    ),
                    model="mockllm/model",
                    fail_on_error=False,
                    ctl_server=False,
                    max_samples=2,
                )
            )

        tg.start_soon(run_eval)
        eval_id = await _wait_for_eval()
        state = get_eval_state(eval_id)
        assert state is not None

        # both samples running, then error `first` terminally (no retries)
        with anyio.fail_after(60):
            while _E2E_RUNS.get("first", 0) < 1 or _E2E_RUNS.get("second", 0) < 1:
                await anyio.sleep(0.01)
        assert _E2E_FAIL is not None
        _E2E_FAIL.set()
        with anyio.fail_after(60):
            while state.errored != 1:
                await anyio.sleep(0.01)

        # close the dispatch gate, then requeue: the re-run stays queued
        paused = await pause_task(state.task_id)
        assert paused is not None and paused.get("ok") is True

        requeued = await requeue_sample(eval_id, "first", 1)
        assert requeued is not None and requeued["ok"] is True
        assert requeued["changed"] is True
        assert state.errored == 0

        # withdraw it: the prior terminal record stands, counters restored
        result = _row(await cancel_sample(eval_id, "first", 1, action="cancel"))
        assert result["ok"] is True and result["changed"] is True
        assert result["status"] == "error"
        assert state.errored == 1 and state.cancelled == 0

        # a repeat cancel is the ordinary already-terminal no-op
        repeat = await cancel_sample(eval_id, "first", 1, action="cancel")
        assert repeat is not None
        assert repeat["ok"] is True and repeat["changed"] is False

        resumed = await resume_task(state.task_id)
        assert resumed is not None and resumed.get("ok") is True
        _E2E_RELEASE.set()

    assert _E2E_RUNS == {"first": 1, "second": 1}  # the re-run never ran

    (log,) = logs
    assert log.status == "success"  # fail_on_error=False
    log = await read_eval_log_async(log.location)
    assert log.samples is not None
    first_records = [s for s in log.samples if str(s.id) == "first"]
    assert len(first_records) == 1
    assert first_records[0].error is not None  # the prior record stands
    second = next(s for s in log.samples if str(s.id) == "second")
    assert second.error is None


_E2E_FAIL: anyio.Event | None = None


@solver
def _fail_on_signal_probe():
    """`first` waits for _E2E_FAIL and raises (attempt 1); the rest park."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sample_id = str(state.sample_id)
        _E2E_RUNS[sample_id] = _E2E_RUNS.get(sample_id, 0) + 1
        if sample_id == "first" and _E2E_RUNS[sample_id] == 1:
            assert _E2E_FAIL is not None
            with anyio.fail_after(60):
                await _E2E_FAIL.wait()
            raise RuntimeError("transient boom")
        assert _E2E_RELEASE is not None
        with anyio.fail_after(60):
            await _E2E_RELEASE.wait()
        return state

    return solve


async def test_cancel_retry_repark_end_to_end() -> None:
    """A sample re-parked mid retry_on_error is cancellable at the queue.

    The task's dispatch gate is paused before the attempt errors, so the
    re-park deterministically stays parked (a freed slot would otherwise
    race the re-park straight back into a running attempt 2).
    """
    from inspect_ai._control.pause import pause_task, resume_task

    global _E2E_RELEASE, _E2E_FAIL
    _E2E_RUNS.clear()
    _E2E_FAIL_FIRST.clear()
    _E2E_RELEASE = anyio.Event()
    _E2E_FAIL = anyio.Event()

    init_display_type("none")
    logs: list[Any] = []

    async with anyio.create_task_group() as tg:

        async def run_eval() -> None:
            logs.extend(
                await eval_async(
                    Task(
                        dataset=[
                            Sample(id="first", input="x", target="y"),
                            Sample(id="second", input="x", target="y"),
                        ],
                        solver=_fail_on_signal_probe(),
                        scorer=_always_correct(),
                        name="retry_repark_e2e",
                    ),
                    model="mockllm/model",
                    fail_on_error=False,
                    retry_on_error=1,
                    ctl_server=False,
                    max_samples=2,
                )
            )

        tg.start_soon(run_eval)
        eval_id = await _wait_for_eval()
        state = get_eval_state(eval_id)
        assert state is not None

        # both samples running, then close the dispatch gate and error first:
        # its retry re-parks at the (paused) gate and stays there
        with anyio.fail_after(60):
            while _E2E_RUNS.get("first", 0) < 1 or _E2E_RUNS.get("second", 0) < 1:
                await anyio.sleep(0.01)
        paused = await pause_task(state.task_id)
        assert paused is not None and paused.get("ok") is True
        _E2E_FAIL.set()
        await _wait_cancellable(eval_id, "first")

        result = _row(await cancel_sample(eval_id, "first", 1, action="cancel"))
        assert result["ok"] is True and result["changed"] is True
        assert result["status"] == "cancelled"
        # counted cancelled; the errored attempt never bumped error_count
        # (retries remained), so no fail-on-error reconciliation applies
        assert state.cancelled == 1 and state.errored == 0

        resumed = await resume_task(state.task_id)
        assert resumed is not None and resumed.get("ok") is True
        _E2E_RELEASE.set()

    assert _E2E_RUNS == {"first": 1, "second": 1}  # the retry never ran

    (log,) = logs
    assert log.status == "success"
    log = await read_eval_log_async(log.location)
    assert log.samples is not None
    # absent from the log: the errored attempt's buffered events were
    # removed at the retry decision and the re-park was discarded
    assert [str(s.id) for s in log.samples] == ["second"]
