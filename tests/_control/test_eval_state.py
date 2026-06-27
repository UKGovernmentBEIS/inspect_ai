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


async def test_deferred_resolution_failure_never_fails_request_or_siblings() -> None:
    """Any Exception from a provider degrades that row only.

    The summaries read of a corrupt reused log raises outside (OSError,
    ValueError) — eg. zipfile.BadZipFile. It must neither fail the GET /evals
    request (a 500 for the whole listing) nor cancel sibling resolutions
    mid-read (which would strand THEIR rows on provisional values too).
    """
    from zipfile import BadZipFile

    from inspect_ai._control.eval_state import (
        DeferredSampleStats,
        register_completed_eval,
    )
    from inspect_ai._control.state import current_eval_summaries

    async def corrupt_provider() -> DeferredSampleStats:
        raise BadZipFile("truncated central directory")

    async def healthy_provider() -> DeferredSampleStats:
        return DeferredSampleStats(total_messages=5, completed=1, errored=1)

    register_completed_eval(
        "corrupt",
        total=4,
        completed=4,
        errored=0,
        task="a",
        task_id="ta",
        deferred_sample_stats=corrupt_provider,
    )
    register_completed_eval(
        "healthy",
        total=2,
        completed=2,
        errored=0,
        task="b",
        task_id="tb",
        deferred_sample_stats=healthy_provider,
    )

    entries = {e["task"]: e for e in await current_eval_summaries(0.0)}
    # corrupt row degrades to its provisional split; healthy row refines
    assert entries["a"]["samples"]["completed"] == 4
    assert entries["a"]["samples"]["errored"] == 0
    assert entries["b"]["samples"]["completed"] == 1
    assert entries["b"]["samples"]["errored"] == 1


async def test_deferred_resolution_cancelled_mid_read_retries_later() -> None:
    """Cancellation mid-read restores the claim for a later retry.

    A client disconnect (or server teardown) cancels the resolving request
    mid-await. The provider was already claimed; without restoring it the row
    would be stranded on provisional values forever — a LATER request must
    retry and refine.
    """
    import anyio

    from inspect_ai._control.eval_state import (
        DeferredSampleStats,
        register_completed_eval,
        resolve_deferred_sample_stats,
    )
    from inspect_ai._control.state import current_eval_summaries

    started = anyio.Event()
    calls = {"n": 0}

    async def provider() -> DeferredSampleStats:
        calls["n"] += 1
        if calls["n"] == 1:
            started.set()
            await anyio.Event().wait()  # parked until cancelled
        return DeferredSampleStats(total_messages=7, completed=1, errored=1)

    state = register_completed_eval(
        "e1",
        total=2,
        completed=2,
        errored=0,
        task="t",
        task_id="tid",
        deferred_sample_stats=provider,
    )

    # request 1: cancelled mid-read (the client went away)
    async with anyio.create_task_group() as tg:
        tg.start_soon(resolve_deferred_sample_stats, state)
        await started.wait()
        tg.cancel_scope.cancel()

    assert state.deferred_sample_stats is not None, "claim must be restored"

    # request 2: retries and refines
    [entry] = await current_eval_summaries(0.0)
    assert calls["n"] == 2
    assert entry["samples"]["errored"] == 1
    assert entry["total_messages"] == 7


async def test_deferred_resolutions_run_concurrently() -> None:
    """The first-request resolution fans out concurrently (not serially).

    Effective concurrency is governed by the filesystem's connection pool
    (matching the bulk header reads in ``read_eval_logs_async``) — at this
    layer the reads just must not serialize.
    """
    import anyio

    from inspect_ai._control.eval_state import (
        DeferredSampleStats,
        register_completed_eval,
    )
    from inspect_ai._control.state import current_eval_summaries

    in_flight = {"now": 0, "max": 0}

    def make_provider() -> Any:
        async def provider() -> DeferredSampleStats:
            in_flight["now"] += 1
            in_flight["max"] = max(in_flight["max"], in_flight["now"])
            await anyio.sleep(0.001)
            in_flight["now"] -= 1
            return DeferredSampleStats(total_messages=1, completed=1, errored=0)

        return provider

    for i in range(20):
        register_completed_eval(
            f"e{i}",
            total=1,
            completed=1,
            errored=0,
            task=f"t{i}",
            task_id=f"tid{i}",
            deferred_sample_stats=make_provider(),
        )

    entries = await current_eval_summaries(0.0)
    assert len(entries) == 20
    assert all(e["total_messages"] == 1 for e in entries)
    assert in_flight["max"] > 1  # genuinely concurrent


async def test_started_at_pinned_as_samples_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``started_at`` stays fixed at the earliest sample start.

    Regression for #4305: the start was recomputed as the min over
    *currently active* samples on every read, so it crept forward as early
    samples finished and left ``active_samples``. It must instead pin to the
    eval's first sample start.
    """
    from types import SimpleNamespace

    import inspect_ai.log._samples as samples_mod
    from inspect_ai._control.state import current_eval_summaries

    register_eval("e1", 3, task="t", task_id="tid")

    def _sample(started: float) -> Any:
        return SimpleNamespace(
            eval_id="e1",
            run_id="r",
            task="t",
            model="m",
            log_location="logs/a.eval",
            started=started,
            completed=None,
            total_tokens=0,
            total_messages=0,
        )

    # First poll: all three samples in flight (starts 100, 200, 300).
    monkeypatch.setattr(
        samples_mod,
        "active_samples",
        lambda: [_sample(100.0), _sample(200.0), _sample(300.0)],
    )
    [entry] = await current_eval_summaries(0.0)
    assert entry["started_at"] == 100.0

    # Later poll: the two earliest finished and left ``active_samples``; only
    # the last (start 300) is still live. The reported start must stay 100.
    monkeypatch.setattr(samples_mod, "active_samples", lambda: [_sample(300.0)])
    [entry] = await current_eval_summaries(0.0)
    assert entry["started_at"] == 100.0


async def test_started_at_pinned_from_terminal_record_before_first_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The earliest start is pinned even if its sample finishes before any poll.

    ``active_samples`` only holds *live* samples, so a sample that started and
    finished between polls would never be seen there. ``record_sample_*``
    captures its start (``started=``), so the eval's reported start still pins
    to it rather than to a later still-running sample.
    """
    from types import SimpleNamespace

    import inspect_ai.log._samples as samples_mod
    from inspect_ai._control.state import current_eval_summaries

    register_eval("e1", 2, task="t", task_id="tid")

    def _sample(started: float) -> Any:
        return SimpleNamespace(
            eval_id="e1",
            run_id="r",
            task="t",
            model="m",
            log_location="logs/a.eval",
            started=started,
            completed=None,
            total_tokens=0,
            total_messages=0,
        )

    # The earliest sample (start 100) finished and left active_samples before
    # the first poll ever ran — its start survives only via the terminal record.
    record_sample_completed("e1", started=100.0)

    # First poll sees only the later still-running sample (start 300), yet the
    # reported start must be the recorded 100, not 300.
    monkeypatch.setattr(samples_mod, "active_samples", lambda: [_sample(300.0)])
    [entry] = await current_eval_summaries(0.0)
    assert entry["started_at"] == 100.0
