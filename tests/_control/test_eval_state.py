"""Unit tests for the process-level EvalState terminal-counter reconciliation.

``finalize_eval`` is the task-finish safety net: samples cancelled while
still queued (parked at the sample semaphore when the task group tears down)
never reach a per-sample terminal record, so without reconciliation the
counters never reach ``total`` and the eval reads "running" forever.
"""

import pytest

from inspect_ai._control.eval_state import (
    clear_all_eval_states,
    finalize_eval,
    get_eval_state,
    record_sample_completed,
    record_sample_errored,
    register_eval,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_all_eval_states()
    yield
    clear_all_eval_states()


def test_finalize_folds_unaccounted_samples_into_cancelled() -> None:
    # 6 planned; one errored, none of the queued 5 ever recorded (the
    # semaphore-parked cancellation shape)
    register_eval("e1", 6)
    record_sample_errored("e1")

    finalize_eval("e1")

    state = get_eval_state("e1")
    assert state is not None
    assert state.errored == 1
    assert state.cancelled == 5
    assert state.is_finished
    assert state.completed_at is not None


def test_finalize_is_a_noop_when_counters_already_complete() -> None:
    register_eval("e1", 2)
    record_sample_completed("e1")
    record_sample_completed("e1")
    state = get_eval_state("e1")
    assert state is not None
    completed_at = state.completed_at
    assert completed_at is not None

    finalize_eval("e1")

    assert state.cancelled == 0
    # the original finish time is preserved (no re-stamp)
    assert state.completed_at == completed_at


def test_finalize_is_a_noop_for_unregistered_eval() -> None:
    # eg. run_samples=False returns before register_eval
    finalize_eval("never-registered")
    assert get_eval_state("never-registered") is None


def test_finalize_preserves_recorded_outcomes() -> None:
    # recorded outcomes are untouched; only the shortfall is folded
    register_eval("e1", 4)
    record_sample_completed("e1", tokens=10, messages=2)
    record_sample_errored("e1", tokens=5, messages=1)

    finalize_eval("e1")

    state = get_eval_state("e1")
    assert state is not None
    assert state.completed == 1
    assert state.errored == 1
    assert state.cancelled == 2
    assert state.total_tokens == 15
    assert state.total_messages == 3
