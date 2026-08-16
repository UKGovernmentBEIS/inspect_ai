"""Unit tests for control-channel per-sample status derivation.

Regression coverage for the transient "all samples show error" snapshot seen
when `inspect ctl samples` is run during a task-level retry teardown: the
failing sample cancels its in-flight siblings, each of which is logged with a
cancellation error. Those cancellations must not render as ``error`` — a
sample that will be retried is ``pending``; one that won't is ``cancelled``.
"""

from typing import TYPE_CHECKING, Any, cast

from inspect_ai._control.state import _summary_from_eval_sample_summary
from inspect_ai.log import EvalSampleSummary

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from tenacity import RetryCallState

    from inspect_ai._control.eval_state import LiveEvalData
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.event._tool import ToolEvent

# How a cancelled sample's error is stored (eval_error -> repr of the backend
# cancellation exception); see EvalSample.summary().
_CANCEL = "CancelledError('Cancelled via cancel scope 0x123')"
_CANCEL_TRIO = "Cancelled()"
_GENUINE = "RuntimeError('boom')"


def _summary(error: str | None, completed: bool = False) -> EvalSampleSummary:
    return EvalSampleSummary(
        id="s1", epoch=1, input="i", target="t", error=error, completed=completed
    )


def test_cancellation_during_retry_renders_as_pending() -> None:
    # The sibling was cancelled because the task is being retried — it will be
    # re-run, so it's pending, not errored.
    result = _summary_from_eval_sample_summary(_summary(_CANCEL), will_retry=True)
    assert result["status"] == "pending"
    assert result["error"] is None


def test_cancellation_trio_repr_also_pending() -> None:
    result = _summary_from_eval_sample_summary(_summary(_CANCEL_TRIO), will_retry=True)
    assert result["status"] == "pending"


def test_cancellation_without_retry_renders_as_cancelled() -> None:
    # No retry coming (final attempt / eval cancelled) — the sample is done and
    # never completed, so it's cancelled rather than pending.
    result = _summary_from_eval_sample_summary(_summary(_CANCEL), will_retry=False)
    assert result["status"] == "cancelled"
    assert result["error"] is None


def test_genuine_error_still_renders_as_error() -> None:
    # A real failure stays "error" even when a retry will follow — it genuinely
    # errored this attempt.
    result = _summary_from_eval_sample_summary(_summary(_GENUINE), will_retry=True)
    assert result["status"] == "error"
    assert result["error"] == _GENUINE


def test_completed_and_running_unaffected() -> None:
    assert (
        _summary_from_eval_sample_summary(_summary(None, completed=True))["status"]
        == "completed"
    )
    assert (
        _summary_from_eval_sample_summary(_summary(None, completed=False))["status"]
        == "running"
    )


# --- deleted-log degradation -------------------------------------------------
#
# The retry sweep (retry_cleanup) deletes superseded attempts' logs while
# their EvalStates persist through any keep-alive park; provider-less reads
# that fall back to log_location must degrade, not 500.


async def test_summaries_from_missing_log_degrade_to_empty(tmp_path) -> None:
    from inspect_ai._control.eval_state import EvalState
    from inspect_ai._control.state import _sample_summaries_from_log

    state = EvalState(
        eval_id="e1", total=1, log_location=str(tmp_path / "deleted.eval")
    )
    assert await _sample_summaries_from_log(state) == []
    # the empty degradation is never memoized: a deleted log stays a
    # per-request (cheap, failing) read rather than a pinned empty listing
    assert state.log_sample_summaries is None


async def test_full_sample_from_missing_log_degrades_to_none(tmp_path) -> None:
    from inspect_ai._control.eval_state import clear_all_eval_states, register_eval
    from inspect_ai._control.state import _full_sample

    try:
        # provider-less state (detached / reused) pointing at a deleted log
        register_eval("e1", 1, log_location=str(tmp_path / "deleted.eval"))
        assert await _full_sample("e1", "1", 1) is None
    finally:
        clear_all_eval_states()


# --- fallback summaries memo ---------------------------------------------
#
# Once the live recorder is gone the log is finalized and immutable, so the
# fallback listing read happens once and is memoized on the EvalState — a
# keep-alive-parked process polled every 30s must not re-read the log
# (possibly from S3) per poll (finding 3 in design/ctl/endpoint-cost-audit.md).
# The retry sweep clears the memo when it deletes a superseded attempt's log.


async def test_fallback_summaries_read_once_and_memoized(monkeypatch) -> None:
    import inspect_ai.log._file as log_file
    from inspect_ai._control.eval_state import clear_all_eval_states, register_eval
    from inspect_ai._control.state import current_sample_summaries

    monkeypatch.setattr("inspect_ai.log._samples.active_samples", lambda: [])
    calls = {"n": 0}

    async def fake_read(location: str) -> list[EvalSampleSummary]:
        calls["n"] += 1
        return [_summary(None, completed=True)]

    monkeypatch.setattr(log_file, "read_eval_log_sample_summaries_async", fake_read)
    try:
        register_eval("e-memo", 1, log_location="logs/a.eval")

        rows = await current_sample_summaries("e-memo")
        assert [r["status"] for r in rows] == ["completed"]
        assert rows == await current_sample_summaries("e-memo")
        assert calls["n"] == 1
    finally:
        clear_all_eval_states()


async def test_retry_sweep_invalidation_degrades_listing_to_empty(monkeypatch) -> None:
    import inspect_ai.log._file as log_file
    from inspect_ai._control.eval_state import (
        clear_all_eval_states,
        get_eval_state,
        invalidate_log_sample_summaries,
        register_eval,
    )
    from inspect_ai._control.state import current_sample_summaries

    monkeypatch.setattr("inspect_ai.log._samples.active_samples", lambda: [])
    deleted = {"is": False}

    async def fake_read(location: str) -> list[EvalSampleSummary]:
        if deleted["is"]:
            raise FileNotFoundError(location)
        return [_summary(None, completed=True)]

    monkeypatch.setattr(log_file, "read_eval_log_sample_summaries_async", fake_read)
    try:
        register_eval("e-swept", 1, log_location="logs/a.eval")
        assert len(await current_sample_summaries("e-swept")) == 1

        # the sweep deletes the log and clears the memo: the listing degrades
        # to empty (the pre-memo behavior) instead of serving memoized rows
        # for a log that no longer exists (whose samples 404 on detail reads)
        deleted["is"] = True
        invalidate_log_sample_summaries("e-swept")
        assert await current_sample_summaries("e-swept") == []
        state = get_eval_state("e-swept")
        assert state is not None and state.log_sample_summaries is None
    finally:
        clear_all_eval_states()


# --- token-limit usage + turn count fields -----------------------------------
#
# The per-sample summary carries a metered token-limit usage/ceiling pair and a
# turn count. Every builder (pending / terminal / running) must emit the same
# keys so a `jq` consumer sees a stable shape across statuses; values are `None`
# only where genuinely unavailable.

_TOKEN_TURN_KEYS = {
    "turn_count",
    "token_limit_usage",
    "token_limit_total",
    "token_limit_type",
}


def test_pending_summary_carries_token_turn_keys() -> None:
    from inspect_ai._control.state import _pending_summary

    row = _pending_summary("s1", 1)
    assert _TOKEN_TURN_KEYS <= row.keys()
    # nothing is known for a not-yet-started sample
    assert all(row[k] is None for k in _TOKEN_TURN_KEYS)


def test_terminal_summary_copies_turn_and_usage() -> None:
    summary = EvalSampleSummary(
        id="s1",
        epoch=1,
        input="i",
        target="t",
        completed=True,
        turn_count=4,
        token_limit=5000,
        token_limit_type="output",
        token_limit_usage=1234,
    )
    row = _summary_from_eval_sample_summary(summary)
    assert _TOKEN_TURN_KEYS <= row.keys()
    assert row["turn_count"] == 4
    assert row["token_limit_usage"] == 1234
    assert row["token_limit_total"] == 5000
    assert row["token_limit_type"] == "output"


def test_terminal_summary_token_limit_none_when_unlimited() -> None:
    # samples without a configured token limit (and pre-upgrade logs) carry
    # None for the whole limit group
    summary = EvalSampleSummary(id="s1", epoch=1, input="i", target="t", completed=True)
    row = _summary_from_eval_sample_summary(summary)
    assert row["token_limit_usage"] is None
    assert row["token_limit_total"] is None
    assert row["token_limit_type"] is None


# --- errors-filtered listing ----------------------------------------------
#
# `sample_filter="errors"` is the eval-set triage read behind `ctl sample
# errors`: it must return only errored/retried samples and must NOT
# synthesize the pending dataset × epochs grid (which can never carry errors
# and dominates the response on large evals).


class _FakeLive:
    """Minimal LiveEvalData stand-in serving canned sample summaries."""

    def __init__(self, summaries: list[EvalSampleSummary]) -> None:
        self._summaries = summaries

    async def sample_summaries(self) -> list[EvalSampleSummary]:
        return self._summaries


async def test_errors_filter_filters_and_skips_pending_grid(monkeypatch) -> None:
    from inspect_ai._control.eval_state import clear_all_eval_states, register_eval
    from inspect_ai._control.state import current_sample_summaries

    monkeypatch.setattr("inspect_ai.log._samples.active_samples", lambda: [])
    completed = [
        EvalSampleSummary(
            id="ok", epoch=1, input="i", target="t", completed=True, retries=0
        ),
        EvalSampleSummary(id="bad", epoch=1, input="i", target="t", error=_GENUINE),
        EvalSampleSummary(
            id="retried", epoch=1, input="i", target="t", completed=True, retries=2
        ),
    ]
    try:
        register_eval(
            "e-errs",
            6,
            live=cast("LiveEvalData", _FakeLive(completed)),
            sample_ids=["ok", "bad", "retried"],
            epochs=2,
        )

        rows = await current_sample_summaries("e-errs", sample_filter="errors")
        assert {(r["sample_id"], r["status"]) for r in rows} == {
            ("bad", "error"),
            ("retried", "completed"),
        }
        assert all(r["status"] != "pending" for r in rows)

        # the unfiltered read still builds the full grid (3 ids × 2 epochs)
        full = await current_sample_summaries("e-errs")
        assert len(full) == 6
        assert sum(1 for r in full if r["status"] == "pending") == 3
    finally:
        clear_all_eval_states()


async def test_listing_withholds_error_message_unless_content(monkeypatch) -> None:
    """The listing's error message (agent-influenced free text) is gated.

    Withheld by default — the row still reads ``status == "error"`` — and
    included with ``content=True``.
    """
    from inspect_ai._control.eval_state import clear_all_eval_states, register_eval
    from inspect_ai._control.state import current_sample_listing

    monkeypatch.setattr("inspect_ai.log._samples.active_samples", lambda: [])
    completed = [
        EvalSampleSummary(id="bad", epoch=1, input="i", target="t", error=_GENUINE),
    ]
    try:
        register_eval(
            "e-content",
            7,
            live=cast("LiveEvalData", _FakeLive(completed)),
            sample_ids=["bad"],
            epochs=1,
        )

        listing = await current_sample_listing("e-content")
        [row] = [r for r in listing.samples if r["sample_id"] == "bad"]
        assert row["status"] == "error"
        assert row["error"] is None

        listing = await current_sample_listing("e-content", content=True)
        [row] = [r for r in listing.samples if r["sample_id"] == "bad"]
        assert row["error"] == _GENUINE
    finally:
        clear_all_eval_states()


async def test_error_detail_withholds_free_text_unless_content(monkeypatch) -> None:
    """``sample_error_detail`` gates the error free text.

    By default each error renders as an empty dict (presence without the
    agent-influenced message / tracebacks); ``content=True`` restores the
    full fields.
    """
    from types import SimpleNamespace

    import inspect_ai._control.state as state_mod
    from inspect_ai.log import EvalError

    monkeypatch.setattr("inspect_ai.log._samples.active_samples", lambda: [])

    error = EvalError(message="boom", traceback="TB", traceback_ansi="TB-ANSI")
    sample = SimpleNamespace(
        id="s1", epoch=1, error=error, error_retries=[error], scores=None
    )

    async def full_sample(*args: Any, **kwargs: Any) -> Any:
        return sample

    async def no_rows(eval_id: str) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(state_mod, "_full_sample", full_sample)
    monkeypatch.setattr(state_mod, "_completed_sample_summaries", no_rows)
    monkeypatch.setattr(state_mod, "_pending_requeue_keys", lambda eid: frozenset())

    detail = await state_mod.sample_error_detail("e1", "s1", 1)
    assert detail is not None
    assert detail["status"] == "error"
    assert detail["error"] == {} and detail["error_retries"] == [{}]

    detail = await state_mod.sample_error_detail("e1", "s1", 1, content=True)
    assert detail is not None
    assert detail["error"] == {
        "message": "boom",
        "traceback": "TB",
        "traceback_ansi": "TB-ANSI",
    }
    assert [e["message"] for e in detail["error_retries"]] == ["boom"]


def test_running_summary_reports_token_limit_and_turns(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from inspect_ai._control.state import _sample_summaries_from_active

    s = MagicMock()
    s.eval_id = "e1"
    s.completed = None
    s.started = 100.0
    s.sample.id = "s1"
    s.epoch = 1
    s.running_time = 5.0
    s.total_tokens = 900
    s.total_messages = 3
    s.total_turns = 2
    s.token_limit_usage = 42
    s.token_limit = 5000
    s.token_limit_type = "output"
    s.transcript.history.last_event = None
    s.transcript.history.event_count = 7
    s.transcript.pending_events = []
    s.retry_wait = None
    s.retries = 0

    monkeypatch.setattr("inspect_ai.log._samples.active_samples", lambda: [s])
    rows = _sample_summaries_from_active("e1")
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "running"
    assert _TOKEN_TURN_KEYS <= row.keys()
    assert row["turn_count"] == 2
    assert row["token_limit_usage"] == 42
    assert row["token_limit_total"] == 5000
    assert row["token_limit_type"] == "output"
    # nothing pending and no retry backoff → the key is present but null
    assert row["activity"] is None


# --- in-flight activity classification --------------------------------------
#
# The `activity` field names a running sample's in-flight operation, read
# off the transcript's pending-events sidecar (and, when no event is
# pending, the sample's retry-wait record). Classification must match the
# TUI's: pending tool wins over pending model (earliest tool leads); a
# retry backoff only shows when nothing is pending.


def _pending_model_event(retries: int | None = None) -> "ModelEvent":
    from inspect_ai.event._model import ModelEvent
    from inspect_ai.model import GenerateConfig, ModelOutput

    return ModelEvent(
        model="openai/gpt-5-nano",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("openai/gpt-5-nano", ""),
        pending=True,
        retries=retries,
    )


def _pending_tool_event(function: str = "bash") -> "ToolEvent":
    from inspect_ai.event._tool import ToolEvent

    return ToolEvent(id="t1", function=function, arguments={}, pending=True)


def _active_with(pending_events: list[Any], retry_wait: Any = None) -> "MagicMock":
    from unittest.mock import MagicMock

    s = MagicMock()
    s.transcript.pending_events = pending_events
    s.retry_wait = retry_wait
    return s


def test_activity_pending_model() -> None:
    from inspect_ai._control.state import _sample_activity

    event = _pending_model_event()
    activity = _sample_activity(_active_with([event]))
    assert activity is not None
    assert activity["type"] == "model"
    assert activity["count"] == 1
    assert activity["started_at"] == event.timestamp.timestamp()
    assert activity["detail"] == "openai/gpt-5-nano"
    assert activity["retries"] is None
    # layer-2 fields are present (stable shape) but null until it ships
    assert activity["tokens"] is None
    assert activity["last_progress_at"] is None


def test_activity_pending_model_carries_in_call_retries() -> None:
    from inspect_ai._control.state import _sample_activity

    activity = _sample_activity(_active_with([_pending_model_event(retries=3)]))
    assert activity is not None
    assert activity["retries"] == 3


def test_activity_tool_wins_over_model_and_earliest_leads() -> None:
    from inspect_ai._control.state import _sample_activity

    first_tool = _pending_tool_event("bash")
    events = [_pending_model_event(), first_tool, _pending_tool_event("python")]
    activity = _sample_activity(_active_with(events))
    assert activity is not None
    assert activity["type"] == "tool"
    assert activity["count"] == 2
    assert activity["detail"] == "bash"
    assert activity["started_at"] == first_tool.timestamp.timestamp()


def test_activity_retry_wait_when_nothing_pending() -> None:
    from inspect_ai._control.state import _sample_activity
    from inspect_ai.log._samples import ActiveSampleRetryWait

    wait = ActiveSampleRetryWait(
        model="openai/gpt-5-nano", attempt=2, started_at=100.0, deadline=130.0
    )
    activity = _sample_activity(_active_with([], retry_wait=wait))
    assert activity is not None
    assert activity["type"] == "retry_wait"
    assert activity["count"] == 2
    assert activity["started_at"] == 100.0
    assert activity["deadline"] == 130.0
    assert activity["detail"] == "openai/gpt-5-nano"


def test_activity_pending_event_wins_over_retry_wait() -> None:
    # a concurrent generate's pending event is live progress; the backoff
    # record only fills the window where nothing at all is in flight
    from inspect_ai._control.state import _sample_activity
    from inspect_ai.log._samples import ActiveSampleRetryWait

    wait = ActiveSampleRetryWait(model="m", attempt=1, started_at=100.0, deadline=130.0)
    activity = _sample_activity(_active_with([_pending_model_event()], retry_wait=wait))
    assert activity is not None
    assert activity["type"] == "model"


def test_activity_none_when_nothing_in_flight() -> None:
    from inspect_ai._control.state import _sample_activity

    assert _sample_activity(_active_with([])) is None


def test_terminal_and_pending_rows_carry_null_activity() -> None:
    from inspect_ai._control.state import _pending_summary

    terminal = _summary_from_eval_sample_summary(_summary(None, completed=True))
    assert "activity" in terminal and terminal["activity"] is None
    pending = _pending_summary("s1", 1)
    assert "activity" in pending and pending["activity"] is None


# --- retry-wait record plumbing ----------------------------------------------
#
# The record is stamped by the model retry loop's before-sleep callback and
# cleared when the retried call resolves; the ownership guard keeps a
# concurrent sibling call's clear from dropping a live wait. Batch admin-op
# retry loops must not stamp at all (their worker task inherits an arbitrary
# sample's context).


def _stamped_active() -> "MagicMock":
    from unittest.mock import MagicMock

    active = MagicMock()
    active.retry_wait = None
    return active


def test_retry_wait_reporter_stamps_and_clears() -> None:
    from inspect_ai.log._samples import (
        _sample_active,
        clear_active_sample_retry_wait,
        report_active_sample_retry_wait,
    )

    active = _stamped_active()
    token = _sample_active.set(active)
    try:
        report_active_sample_retry_wait("m", 2, 30.0)
        record = active.retry_wait
        assert record is not None
        assert record.model == "m"
        assert record.attempt == 2
        assert record.deadline == record.started_at + 30.0

        clear_active_sample_retry_wait()
        assert active.retry_wait is None
        # idempotent: a second clear (or one with no stamp) is a no-op
        clear_active_sample_retry_wait()
        assert active.retry_wait is None
    finally:
        _sample_active.reset(token)


def test_retry_wait_reporter_noop_without_active_sample() -> None:
    from inspect_ai.log._samples import (
        clear_active_sample_retry_wait,
        report_active_sample_retry_wait,
    )

    # neither call should raise outside a sample context
    report_active_sample_retry_wait("m", 1, 5.0)
    clear_active_sample_retry_wait()


async def test_retry_wait_clear_preserves_concurrent_siblings_record() -> None:
    import anyio

    from inspect_ai._util._async import tg_collect
    from inspect_ai.log._samples import (
        _sample_active,
        clear_active_sample_retry_wait,
        report_active_sample_retry_wait,
    )

    active = _stamped_active()
    token = _sample_active.set(active)
    a_stamped = anyio.Event()
    b_stamped = anyio.Event()

    async def call_a() -> None:
        report_active_sample_retry_wait("m", 1, 10.0)
        a_stamped.set()
        await b_stamped.wait()
        # B has since overwritten the slot; A's clear must not drop B's wait
        clear_active_sample_retry_wait()

    async def call_b() -> None:
        await a_stamped.wait()
        report_active_sample_retry_wait("m", 3, 20.0)
        b_stamped.set()

    try:
        await tg_collect([call_a, call_b])
        assert active.retry_wait is not None
        assert active.retry_wait.attempt == 3
    finally:
        _sample_active.reset(token)


def _retry_call_state(upcoming_sleep: float, attempt_number: int) -> "RetryCallState":
    from tenacity import RetryCallState

    state = RetryCallState(cast(Any, None), None, (), {})
    state.upcoming_sleep = upcoming_sleep
    state.attempt_number = attempt_number
    return state


async def test_model_retry_before_sleep_stamps_retry_wait() -> None:
    from inspect_ai.log._samples import _sample_active
    from inspect_ai.model._retry import model_retry_config

    active = _stamped_active()
    token = _sample_active.set(active)
    try:
        config = model_retry_config(
            "m", None, None, lambda ex: True, lambda ex: None, lambda name, rs: None
        )
        result = config["before_sleep"](_retry_call_state(30.0, 2))
        if result is not None:
            await result
        assert active.retry_wait is not None
        assert active.retry_wait.attempt == 2
    finally:
        _sample_active.reset(token)


async def test_batch_admin_retry_does_not_stamp_retry_wait() -> None:
    from inspect_ai.log._samples import _sample_active
    from inspect_ai.model._generate_config import GenerateConfig
    from inspect_ai.model._retry import batch_admin_retry_config

    active = _stamped_active()
    token = _sample_active.set(active)
    try:
        config = batch_admin_retry_config("m", GenerateConfig(), lambda ex: True)
        result = config["before_sleep"](_retry_call_state(30.0, 2))
        if result is not None:
            await result
        assert active.retry_wait is None
    finally:
        _sample_active.reset(token)


def test_task_summary_adds_live_counts_to_the_eval_total(monkeypatch) -> None:
    """Refusals / HTTP retries are reported as ``eval total + sum(in flight)``.

    Both terms are needed and neither is sufficient. The eval total alone misses
    everything the running samples have seen so far — which on a long-episode
    benchmark is everything, since no sample may finish for hours, and a retry
    storm is worth knowing about while the run can still be steered. The live sum
    alone falls back toward zero as samples finish and leave ``active_samples``,
    the bug already fixed for ``total_tokens``.
    """
    from types import SimpleNamespace

    from inspect_ai._control.eval_state import (
        clear_all_eval_states,
        get_eval_state,
        record_sample_event_counts,
        register_eval,
    )
    from inspect_ai._control.state import _build_summary

    clear_all_eval_states()
    try:
        register_eval("e1", 3, task="t", task_id="tid")
        # two samples already finished and left active_samples
        record_sample_event_counts("e1", refusals=2, http_retries=7)
        latest = get_eval_state("e1")
        assert latest is not None

        in_flight = SimpleNamespace(
            eval_id="e1",
            run_id="r",
            task="t",
            model="m",
            log_location="logs/a.eval",
            started=100.0,
            completed=None,
            total_tokens=0,
            total_messages=0,
            refusals=1,
            http_retries=4,
        )
        summary = _build_summary(
            latest=latest,
            states=[latest],
            samples=[cast("Any", in_flight)],
            attempts=1,
            started_at_fallback=0.0,
        )
        assert summary["refusals"] == 3
        assert summary["http_retries"] == 11
    finally:
        clear_all_eval_states()


def test_task_summary_sums_event_counts_across_retry_attempts() -> None:
    """A task-level retry must not discard the prior attempt's tallies.

    ``current_eval_summaries`` folds every attempt of a task onto ONE row, and the
    state counters deliberately come from the latest attempt only (a retry's
    ``completed`` already includes reused successes, so summing double-counts).
    Event counts are the exception: they record what happened, and the attempt that
    FAILED is the one whose retries matter most — a provider problem bad enough to
    fail a task is what triggered the retry. With ``retry_attempts`` defaulting to
    10, reading these off ``latest`` reset them on the default path.
    """
    from inspect_ai._control.eval_state import (
        clear_all_eval_states,
        get_eval_states,
        record_sample_event_counts,
        register_eval,
    )
    from inspect_ai._control.state import _build_summary

    clear_all_eval_states()
    try:
        register_eval("e1", 2, task="t", task_id="tid")  # attempt 1
        record_sample_event_counts("e1", refusals=2, http_retries=5)
        register_eval("e2", 2, task="t", task_id="tid")  # its retry
        record_sample_event_counts("e2", refusals=1, http_retries=3)
        states = list(get_eval_states())
        assert len(states) == 2

        summary = _build_summary(
            latest=states[-1],
            states=states,
            samples=[],
            attempts=len(states),
            started_at_fallback=0.0,
        )
        assert summary["refusals"] == 3
        assert summary["http_retries"] == 8
    finally:
        clear_all_eval_states()
