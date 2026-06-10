"""Unit tests for the process-level EvalState terminal-counter reconciliation.

``finalize_eval`` is the task-finish safety net: samples cancelled while
still queued (parked at the sample semaphore when the task group tears down)
never reach a per-sample terminal record, so without reconciliation the
counters never reach ``total`` and the eval reads "running" forever.
"""

from typing import Any

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


def test_detach_eval_providers_nulls_live_accessors() -> None:
    """Detaching a superseded attempt removes its live providers only.

    On task retry the (shared) TaskLogger is re-pointed at the new attempt;
    the superseded attempt's bound-method providers would otherwise serve the
    new attempt's data under the old eval_id. Counters and metadata persist.
    """
    from inspect_ai._control.eval_state import detach_eval_providers

    async def summaries():
        return []

    async def sample(id, epoch, *, exclude_fields=None):
        return None

    register_eval(
        "e1",
        2,
        log_location="logs/a.eval",
        summaries_provider=summaries,
        sample_provider=sample,
        events_provider=lambda id, epoch: None,
    )
    record_sample_errored("e1")

    detach_eval_providers("e1")

    state = get_eval_state("e1")
    assert state is not None
    assert state.summaries_provider is None
    assert state.sample_provider is None
    assert state.events_provider is None
    # everything else is untouched
    assert state.errored == 1
    assert state.log_location == "logs/a.eval"

    # unregistered evals no-op
    detach_eval_providers("never-registered")


async def test_deferred_sample_stats_resolve_lazily_and_once() -> None:
    """Reused evals' summaries-derived stats resolve on first read, memoized.

    Registration is header-only (eval-set already parsed the headers to
    decide reuse); the per-log summaries read happens on the first
    ``current_eval_summaries`` call — never at eval-set startup — and exactly
    once.
    """
    from inspect_ai._control.eval_state import (
        DeferredSampleStats,
        register_completed_eval,
    )
    from inspect_ai._control.state import current_eval_summaries

    calls = {"n": 0}

    async def provider() -> DeferredSampleStats:
        calls["n"] += 1
        return DeferredSampleStats(total_messages=7, completed=1, errored=1)

    register_completed_eval(
        "e1",
        total=2,
        completed=2,  # provisional header-derived split
        errored=0,
        task="t",
        task_id="tid",
        deferred_sample_stats=provider,
    )
    assert calls["n"] == 0  # nothing read at registration

    [entry] = await current_eval_summaries(0.0)
    assert calls["n"] == 1
    assert entry["samples"]["completed"] == 1
    assert entry["samples"]["errored"] == 1
    assert entry["total_messages"] == 7

    # memoized: subsequent reads don't re-read
    [entry] = await current_eval_summaries(0.0)
    assert calls["n"] == 1
    assert entry["samples"]["errored"] == 1


async def test_deferred_sample_stats_failure_keeps_provisional_split() -> None:
    """A failed resolution keeps the header-derived provisional values.

    They sum to ``total``, so the row still renders terminal (no phantom
    ``queued``) — just with the header's coarser completed/errored split.
    The provider is not retried.
    """
    from inspect_ai._control.eval_state import register_completed_eval
    from inspect_ai._control.state import current_eval_summaries

    calls = {"n": 0}

    async def failing_provider() -> Any:
        calls["n"] += 1
        raise OSError("log unreadable")

    register_completed_eval(
        "e1",
        total=3,
        completed=2,
        errored=1,
        task="t",
        task_id="tid",
        deferred_sample_stats=failing_provider,
    )

    [entry] = await current_eval_summaries(0.0)
    assert entry["samples"] == {
        "total": 3,
        "completed": 2,
        "errored": 1,
        "cancelled": 0,
        "in_flight": 0,
        "queued": 0,
    }
    [entry] = await current_eval_summaries(0.0)
    assert calls["n"] == 1  # no retry storm
