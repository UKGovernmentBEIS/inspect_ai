"""Unit tests for control-channel per-sample status derivation.

Regression coverage for the transient "all samples show error" snapshot seen
when `inspect ctl samples` is run during a task-level retry teardown: the
failing sample cancels its in-flight siblings, each of which is logged with a
cancellation error. Those cancellations must not render as ``error`` — a
sample that will be retried is ``pending``; one that won't is ``cancelled``.
"""

from inspect_ai._control.state import _summary_from_eval_sample_summary
from inspect_ai.log import EvalSampleSummary

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
    from inspect_ai._control.state import _sample_summaries_from_log

    assert await _sample_summaries_from_log(str(tmp_path / "deleted.eval")) == []


async def test_full_sample_from_missing_log_degrades_to_none(tmp_path) -> None:
    from inspect_ai._control.eval_state import clear_all_eval_states, register_eval
    from inspect_ai._control.state import _full_sample

    try:
        # provider-less state (detached / reused) pointing at a deleted log
        register_eval("e1", 1, log_location=str(tmp_path / "deleted.eval"))
        assert await _full_sample("e1", "1", 1) is None
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
        token_limit_usage=1234,
    )
    row = _summary_from_eval_sample_summary(summary)
    assert _TOKEN_TURN_KEYS <= row.keys()
    assert row["turn_count"] == 4
    assert row["token_limit_usage"] == 1234
    # the on-disk summary carries metered usage but not the ceiling or type
    assert row["token_limit_total"] is None
    assert row["token_limit_type"] is None


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
