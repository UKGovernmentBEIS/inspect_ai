"""Dump/restore of sample-root limit usage and related runtime across resume."""

from __future__ import annotations

import anyio
import pytest
from pydantic import JsonValue

from inspect_ai._util._async import tg_collect
from inspect_ai._util.working import (
    init_sample_working_time,
    report_sample_waiting_time,
    sample_waiting_time,
    sample_working_time,
)
from inspect_ai.model._model import (
    init_sample_model_data,
    sample_model_fallbacks_context_var,
    sample_model_usage,
    sample_role_usage,
)
from inspect_ai.model._model_output import ModelUsage
from inspect_ai.util._checkpoint.sample_runtime import (
    dump_sample_runtime,
    restore_sample_runtime,
)
from inspect_ai.util._limit import (
    LimitExceededError,
    cost_limit,
    record_model_cost,
    record_model_usage,
    record_turn,
    time_limit,
    token_limit,
    turn_limit,
    working_limit,
    working_limit_exceeded,
)


def test_restore_absent_runtime_is_noop() -> None:
    """A checkpoint without sample_runtime.json leaves live usage unchanged."""
    with token_limit(100) as limit:
        record_model_usage(ModelUsage(total_tokens=5))
        restore_sample_runtime(None, check=False)
        assert limit.usage == 5


def test_restore_reseeds_token_cost_turn_usage() -> None:
    """Token/cost/turn usage after restore matches the snapshot, not zero."""
    with (
        token_limit(100, type="output") as dumped_token,
        cost_limit(10.0),
        turn_limit(20),
    ):
        record_model_usage(
            ModelUsage(input_tokens=10, output_tokens=3, total_tokens=13)
        )
        record_model_cost(1.25)
        record_turn()
        record_turn()
        payload = dump_sample_runtime()
        assert dumped_token.usage == 3  # metered (output); payload must keep raw

    with (
        token_limit(100, type="output") as token,
        cost_limit(10.0) as cost,
        turn_limit(20) as turns,
    ):
        restore_sample_runtime(payload, check=False)
        restored = dump_sample_runtime()
        assert isinstance(restored, dict)
        token_usage = restored["token_usage"]
        assert isinstance(token_usage, dict)
        assert token_usage["input_tokens"] == 10
        assert token_usage["output_tokens"] == 3
        assert token_usage["total_tokens"] == 13
        assert token.usage == 3
        assert cost.usage == 1.25
        assert turns.usage == 2


def test_over_limit_seed_does_not_raise_until_check() -> None:
    """Seeding over-limit usage is silent; check=True raises after restore."""
    with token_limit(10):
        record_model_usage(ModelUsage(total_tokens=11))
        payload = dump_sample_runtime()

    with token_limit(10) as limit:
        restore_sample_runtime(payload, check=False)
        assert limit.usage == 11

    with token_limit(10), pytest.raises(LimitExceededError) as exc_info:
        restore_sample_runtime(payload, check=True)
    assert exc_info.value.type == "token"
    assert exc_info.value.value == 11
    assert exc_info.value.limit == 10


def test_over_cost_limit_raises_on_check() -> None:
    """Cost over-limit is silent on seed and raises from check=True."""
    with cost_limit(1.0):
        record_model_cost(1.5)
        payload = dump_sample_runtime()

    with cost_limit(1.0) as limit:
        restore_sample_runtime(payload, check=False)
        assert limit.usage == pytest.approx(1.5)

    with cost_limit(1.0), pytest.raises(LimitExceededError) as exc_info:
        restore_sample_runtime(payload, check=True)
    assert exc_info.value.type == "cost"


def test_over_turn_limit_raises_on_check() -> None:
    """Turn over-limit is silent on seed and raises from check=True."""
    with turn_limit(10):
        record_turn()
        record_turn()
        record_turn()
        payload = dump_sample_runtime()

    with turn_limit(2) as limit:
        restore_sample_runtime(payload, check=False)
        assert limit.usage == 3

    with turn_limit(2), pytest.raises(LimitExceededError) as exc_info:
        restore_sample_runtime(payload, check=True)
    assert exc_info.value.type == "turn"


async def test_time_remaining_does_not_charge_downtime() -> None:
    """Remaining time is limit minus fire-time elapsed; the dump-to-restore gap is not charged."""
    with time_limit(10.0) as limit:
        await anyio.sleep(0.15)
        payload = dump_sample_runtime()
        assert isinstance(payload, dict)
        elapsed = payload["time_elapsed"]
        assert isinstance(elapsed, (int, float))
        elapsed = float(elapsed)
        await anyio.sleep(0.25)
        restore_sample_runtime(payload, check=False)
        assert limit.usage == pytest.approx(elapsed, abs=0.05)
        assert limit.remaining == pytest.approx(10.0 - elapsed, abs=0.05)


async def test_working_restore_continues_from_snapshot() -> None:
    """Working/waiting continue from the snapshot; downtime is not working time."""
    import time

    init_sample_working_time(time.monotonic())
    with working_limit(30.0) as limit:
        report_sample_waiting_time(0.4)
        await anyio.sleep(0.12)
        payload = dump_sample_runtime()
        assert isinstance(payload, dict)
        waiting = payload["working_waiting"]
        elapsed = payload["working_elapsed"]
        assert isinstance(waiting, (int, float))
        assert isinstance(elapsed, (int, float))
        assert float(waiting) == pytest.approx(0.4)
        await anyio.sleep(0.25)
        restore_sample_runtime(payload, check=True)
        assert limit.usage == pytest.approx(float(elapsed), abs=0.08)


async def test_scoring_resume_does_not_seed_working_enforcement() -> None:
    """A scoring resume leaves working anchors fresh, so the monitor can't cancel it.

    ``monitor_working_limit`` polls ``working_limit_exceeded()`` every second
    with no attempt awareness; seeded anchors would cancel the plan task group
    of the very attempt that exists to score the sample.
    """
    with working_limit(30.0) as limit:
        restore_sample_runtime({"working_elapsed": 45.0}, check=False)
        assert limit.usage < 1.0
        assert working_limit_exceeded() is None


async def test_over_working_limit_raises_on_check() -> None:
    """A normal resume over the working budget reports it at hydrate, not ~1s later."""
    with working_limit(30.0), pytest.raises(LimitExceededError) as exc_info:
        restore_sample_runtime({"working_elapsed": 45.0}, check=True)
    assert exc_info.value.type == "working"


async def test_restore_keeps_waiting_time_attempt_local() -> None:
    """Prior waiting time does not follow the sample into the logged working time.

    ``create_eval_sample`` logs ``total_time - sample_waiting_time()``, where
    ``total_time`` is this attempt's wall clock. A restored cumulative waiting
    value drives that figure negative on a short resumed attempt.

    ``sample_waiting_time`` is a key older snapshots carry, so restore has to
    ignore it rather than merely stop writing it.
    """
    import time

    init_sample_working_time(time.monotonic())
    restore_sample_runtime(
        {
            "working_elapsed": 120.0,
            "working_waiting": 60.0,
            "sample_waiting_time": 60.0,
        },
        check=False,
    )
    assert sample_waiting_time() == 0.0
    # the working-time origin still carries the prior attempt, so event
    # `working_start` values keep climbing across attempts
    assert sample_working_time() == pytest.approx(120.0, abs=0.5)


async def test_scoring_resume_over_time_budget_is_not_cancelled() -> None:
    """A scoring resume of a sample whose time budget was spent still runs."""
    with time_limit(30) as limit:
        restore_sample_runtime({"time_elapsed": 45.0}, check=False)
        await anyio.sleep(0.05)
        assert limit.usage == pytest.approx(45.0, abs=0.5)


async def test_scoring_resume_retune_does_not_rearm_spent_deadline() -> None:
    """A live time_limit retune during a scoring resume does not re-arm the spent budget.

    ``set_sample_limit_override`` re-derives the deadline of every live time
    scope; the restored elapsed must stay out of that derivation, or a retune
    in the plan window cancels the very attempt that exists to score.
    """
    from inspect_ai.util._limit import message_limit
    from inspect_ai.util._limit_overrides import (
        reset_sample_limit_overrides,
        sample_limit_override_scope,
        set_sample_limit_override,
    )

    time_node = time_limit(30)
    try:
        with sample_limit_override_scope(
            "t-scoring",
            time=time_node,
            token=token_limit(None),
            message=message_limit(None),
        ):
            with time_node:
                restore_sample_runtime({"time_elapsed": 45.0}, check=False)
                set_sample_limit_override("t-scoring", "time_limit", 30)
                await anyio.sleep(0.05)
                assert time_node.usage == pytest.approx(45.0, abs=0.5)
    finally:
        reset_sample_limit_overrides()


async def test_resume_arms_time_deadline_when_over_budget() -> None:
    """A normal resume over the time budget is still cancelled."""
    with pytest.raises(LimitExceededError) as exc_info:
        with time_limit(30):
            restore_sample_runtime({"time_elapsed": 45.0}, check=True)
            await anyio.sleep(1)
    assert exc_info.value.type == "time"


async def test_counted_limit_reported_before_time_cancellation() -> None:
    """Over on both tokens and time, the resume reports the token limit.

    Arming the deadline first would leave a cancellation pending while the
    token error unwinds through async frames.
    """
    payload: dict[str, JsonValue] = {
        "time_elapsed": 45.0,
        "token_usage": ModelUsage(total_tokens=1500).model_dump(mode="json"),
    }
    with time_limit(30), token_limit(1000):
        with pytest.raises(LimitExceededError) as exc_info:
            restore_sample_runtime(payload, check=True)
        assert exc_info.value.type == "token"
        # an armed deadline would cancel the scope here, and the time limit
        # would replace the token error on the way out
        await anyio.sleep(0.05)


async def test_time_elapsed_restore_sets_remaining() -> None:
    """Restoring a known elapsed value sets remaining to limit minus that elapsed."""
    with time_limit(100.0) as limit:
        payload = dump_sample_runtime()
        assert isinstance(payload, dict)
        payload["time_elapsed"] = 40.0
        restore_sample_runtime(payload, check=False)
        assert limit.usage == pytest.approx(40.0, abs=0.05)
        assert limit.remaining == pytest.approx(60.0, abs=0.05)


async def test_model_usage_restore_from_child_visible_on_outer() -> None:
    """In-place dict update from a child task is visible on the outer context."""
    init_sample_model_data()
    sample_model_usage()["mock"] = ModelUsage(total_tokens=1)
    sample_model_fallbacks_context_var.get()[("a", "b")] = 1

    payload = dump_sample_runtime()
    assert isinstance(payload, dict)
    payload["model_usage"] = {
        "mock": ModelUsage(total_tokens=42).model_dump(mode="json")
    }
    payload["model_fallbacks"] = [
        {"model": "a", "fallback_model": "b", "count": 3},
    ]

    async def restore_in_child() -> None:
        restore_sample_runtime(payload, check=False)

    await tg_collect([restore_in_child])
    assert sample_model_usage()["mock"].total_tokens == 42
    assert sample_model_fallbacks_context_var.get()[("a", "b")] == 3


def test_role_usage_round_trips() -> None:
    """Per-sample role usage is restored in place, not left empty."""
    init_sample_model_data()
    sample_role_usage()["solver"] = ModelUsage(total_tokens=7)
    payload = dump_sample_runtime()

    init_sample_model_data()
    assert sample_role_usage() == {}
    restore_sample_runtime(payload, check=False)
    assert sample_role_usage()["solver"].total_tokens == 7
