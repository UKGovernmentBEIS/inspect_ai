"""Tests for the control-channel cancel directives (phase 3).

Covers the directive functions in ``inspect_ai._control.cancel`` (task cancel:
task-keyed, resolved to the latest attempt's registered ``TaskCancel``; sample
cancel: interrupt via ``ActiveSample.interrupt``; tool-call cancel: fire one
pending ``ToolEvent``'s per-call cancel scope) and the server routes that wrap
them (``POST /tasks/<id>/cancel``, ``POST /evals/<id>/sample/cancel``,
``POST /evals/<id>/sample/cancel-tool-call``).
"""

from types import SimpleNamespace
from typing import Any, Literal

import httpx
import pytest
from test_helpers.live_eval_data import FakeLiveEvalData

from inspect_ai._control.cancel import cancel_sample, cancel_task, cancel_tool_call
from inspect_ai._control.eval_state import (
    clear_all_eval_states,
    get_eval_state,
    mark_eval_retry_pending,
    record_sample_errored,
    register_completed_eval,
    register_eval,
)
from inspect_ai._display.core.display import CancelType, TaskCancel


@pytest.fixture(autouse=True)
def _clear_states():
    clear_all_eval_states()
    yield
    clear_all_eval_states()


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


def test_cancel_task_pending_retry_cancel_named_in_noop() -> None:
    """A no-op against a pending *retry* cancel must say so.

    The TUI's cancel dialog can fire a retry-cancel on the same handle; an
    abort issued while that tears down no-ops, but the task will be
    re-queued — the reason names the pending type so the caller knows the
    task is not going away.
    """
    handle = _FakeTaskCancel(can_retry=True)
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    handle.cancel_task("retry")

    result = cancel_task("t1")
    assert result is not None
    assert result["ok"] is True and result["changed"] is False
    assert result["reason"] == "cancel already requested (retry)"
    assert handle.fired == ["retry"]  # the abort was not fired


def test_cancel_task_finished_is_idempotent_noop() -> None:
    register_completed_eval("e1", total=5, completed=5, task_id="t1", task="my_task")
    result = cancel_task("t1")
    assert result is not None
    assert result["ok"] is True and result["changed"] is False
    assert "finished" in result["reason"]


def test_cancel_task_between_attempts_rejected() -> None:
    """An errored attempt with a retry queued must not report "finished"."""
    handle = _FakeTaskCancel(can_retry=True)
    register_eval("e1", 1, task_id="t1", will_retry=True, task_cancel=handle)
    record_sample_errored("e1")  # attempt finishes (completed_at stamped) ...
    mark_eval_retry_pending("e1")  # ... and the eval-set queues a retry

    result = cancel_task("t1")
    assert result is not None
    assert result["ok"] is False and "between attempts" in result["error"]
    assert handle.fired == []


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


async def test_cancel_sample_queued_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = _FakeActiveSample(started=None)
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is False and "queued" in result["error"]
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


async def test_task_cancel_route_between_attempts_409() -> None:
    register_eval("e1", 1, task_id="t1", will_retry=True)
    record_sample_errored("e1")
    mark_eval_retry_pending("e1")

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        rejected = await client.post("/tasks/t1/cancel")
        assert rejected.status_code == 409
        assert "between attempts" in rejected.json()["error"]


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
