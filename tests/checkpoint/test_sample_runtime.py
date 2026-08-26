"""Dump/restore of sample-root limit usage and related runtime across resume."""

from __future__ import annotations

import anyio
import pytest

from inspect_ai._util._async import tg_collect
from inspect_ai._util.working import (
    init_sample_working_time,
    report_sample_waiting_time,
    sample_waiting_time,
)
from inspect_ai.model._model import (
    init_sample_model_data,
    sample_model_fallbacks_context_var,
    sample_model_usage,
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
    init_sample_working_time(0.0)
    with working_limit(10.0):
        report_sample_waiting_time(0.4)
        payload = dump_sample_runtime()
        assert isinstance(payload, dict)
        waiting = payload["working_waiting"]
        assert isinstance(waiting, (int, float))
        assert float(waiting) == pytest.approx(0.4)
        restore_sample_runtime(payload, check=False)
        restored = dump_sample_runtime()
        assert isinstance(restored, dict)
        restored_waiting = restored["working_waiting"]
        assert isinstance(restored_waiting, (int, float))
        assert float(restored_waiting) == pytest.approx(0.4)
        assert sample_waiting_time() == pytest.approx(0.4)


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
