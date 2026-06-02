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
