"""Unit tests for ModelGenerateAccounting."""

from datetime import datetime, timedelta, timezone

import anyio

from inspect_ai.event._model import ModelEvent
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._generate_accounting import (
    ModelGenerateAccounting,
    current_model_generate_accounting,
    model_generate_accounting,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput


def _empty_event(call_id: str, attempt: int) -> ModelEvent:
    return ModelEvent(
        model="fake",
        input=[ChatMessageUser(content="x")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("fake", "ok"),
        call_id=call_id,
        attempt=attempt,
    )


def test_new_accounting_has_call_id_zero_counters_no_last_event() -> None:
    acc = ModelGenerateAccounting.new(
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc), working_start=0.0
    )
    assert acc.call_id
    assert acc.attempt_count == 0
    assert acc.call_retry_count == 0
    assert acc.http_retry_count == 0
    assert acc.last_event is None


def test_register_event_stamps_call_id_and_attempt() -> None:
    acc = ModelGenerateAccounting.new(
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc), working_start=0.0
    )
    ev1 = _empty_event(call_id="", attempt=0)
    ev1.call_id = None
    ev1.attempt = None
    acc.register_event(ev1)
    assert ev1.call_id == acc.call_id
    assert ev1.attempt == 1
    assert acc.last_event is ev1

    ev2 = _empty_event(call_id="", attempt=0)
    ev2.call_id = None
    ev2.attempt = None
    acc.register_event(ev2)
    assert ev2.attempt == 2
    assert acc.last_event is ev2


def test_retry_counters_are_independent() -> None:
    acc = ModelGenerateAccounting.new(
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc), working_start=0.0
    )
    acc.record_call_retry()
    acc.record_call_retry()
    acc.record_http_retry()
    assert acc.call_retry_count == 2
    assert acc.http_retry_count == 1


def test_finalize_terminal_event_sets_call_fields_and_legacy_retries() -> None:
    start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    acc = ModelGenerateAccounting.new(started_at=start, working_start=0.0)
    ev = _empty_event(call_id=acc.call_id, attempt=2)
    acc.last_event = ev
    acc.record_call_retry()
    acc.record_http_retry()
    acc.record_http_retry()

    end = start + timedelta(seconds=3.0)
    acc.finalize_terminal_event(event=ev, completed_at=end, working_now=2.5)

    assert ev.call_started_at == start
    assert ev.call_completed_at == end
    assert ev.call_working_start == 0.0
    assert ev.call_working_time == 2.5
    assert ev.call_retries == 1
    assert ev.http_retries == 2
    assert ev.retries == 2


def test_finalize_terminal_event_is_idempotent() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    acc = ModelGenerateAccounting.new(started_at=start, working_start=0.0)
    ev = _empty_event(call_id=acc.call_id, attempt=1)
    acc.finalize_terminal_event(event=ev, completed_at=start, working_now=1.0)
    original_completed = ev.call_completed_at
    acc.record_call_retry()
    acc.finalize_terminal_event(
        event=ev, completed_at=start + timedelta(seconds=10), working_now=99.0
    )
    assert ev.call_completed_at == original_completed
    assert ev.call_retries == 0


async def test_context_manager_sets_and_clears() -> None:
    assert current_model_generate_accounting() is None
    acc = ModelGenerateAccounting.new(
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc), working_start=0.0
    )
    async with model_generate_accounting(acc):
        assert current_model_generate_accounting() is acc
    assert current_model_generate_accounting() is None


async def test_re_entrant_restores_outer() -> None:
    outer = ModelGenerateAccounting.new(
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc), working_start=0.0
    )
    inner = ModelGenerateAccounting.new(
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc), working_start=0.0
    )
    async with model_generate_accounting(outer):
        async with model_generate_accounting(inner):
            assert current_model_generate_accounting() is inner
        assert current_model_generate_accounting() is outer


async def test_concurrent_tasks_have_independent_accounting() -> None:
    results: list[str | None] = []

    async def task(date: datetime) -> None:
        acc = ModelGenerateAccounting.new(started_at=date, working_start=0.0)
        async with model_generate_accounting(acc):
            await anyio.sleep(0.01)
            cur = current_model_generate_accounting()
            results.append(cur.call_id if cur else None)

    async with anyio.create_task_group() as tg:
        tg.start_soon(task, datetime(2026, 1, 1, tzinfo=timezone.utc))
        tg.start_soon(task, datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert len(results) == 2
    assert results[0] != results[1]


def test_legacy_retries_mirrors_call_retries_when_no_http() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    acc = ModelGenerateAccounting.new(started_at=start, working_start=0.0)
    ev = _empty_event(call_id=acc.call_id, attempt=2)
    acc.record_call_retry()
    acc.finalize_terminal_event(event=ev, completed_at=start, working_now=0.0)
    assert ev.retries == 1
