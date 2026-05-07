"""Top-level retry-event invariants."""

# pyright: reportImplicitRelativeImport=false

# ruff: noqa: E402

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import anyio
import pytest

hypothesis = pytest.importorskip("hypothesis")
from _helpers.event_assertions import assert_no_legacy_rewrite, model_events
from _helpers.retry_provider import (
    RetryableModelError,
    install_retry_classifier,
    make_mockllm_with_callable,
)
from _helpers.strategies import RetryScenario, retry_scenarios

HealthCheck = cast(Any, hypothesis.HealthCheck)
given = cast(Any, hypothesis.given)
settings = cast(Any, hypothesis.settings)
st = cast(Any, hypothesis.strategies)

from inspect_ai.event._model import ModelEvent
from inspect_ai.log._transcript import Transcript, init_transcript
from inspect_ai.model import GenerateConfig
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._generate_accounting import ModelGenerateAccounting
from inspect_ai.model._model_output import ModelOutput


@given(scenario=retry_scenarios())
@settings(
    max_examples=25,
    deadline=5000,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_property_attempts_contiguous(scenario: RetryScenario) -> None:
    anyio.run(_check_property_attempts_contiguous, scenario)


async def _check_property_attempts_contiguous(scenario: RetryScenario) -> None:
    terminal = scenario.outcomes[-1]
    remaining = [scenario.outcomes.count("fail-retryable")]

    def custom_outputs(input, tools, tool_choice, config):
        if remaining[0] > 0:
            remaining[0] -= 1
            raise RetryableModelError("transient")
        if terminal != "success":
            raise ValueError("permanent")
        return ModelOutput.from_content("mockllm", "ok")

    transcript = Transcript()
    init_transcript(transcript)
    model = make_mockllm_with_callable(custom_outputs)
    install_retry_classifier(model)
    try:
        await model.generate(
            "x", config=GenerateConfig(max_retries=scenario.max_retries)
        )
    except Exception:
        pass

    events = model_events(transcript)
    if events:
        assert len({event.call_id for event in events}) == 1
        assert [event.attempt for event in events] == list(range(1, len(events) + 1))


@given(scenario=retry_scenarios())
@settings(max_examples=25, deadline=5000)
def test_property_no_legacy_rewrite(scenario: RetryScenario) -> None:
    anyio.run(_check_property_no_legacy_rewrite, scenario)


async def _check_property_no_legacy_rewrite(scenario: RetryScenario) -> None:
    remaining = [scenario.outcomes.count("fail-retryable")]

    def custom_outputs(input, tools, tool_choice, config):
        if remaining[0] > 0:
            remaining[0] -= 1
            raise RetryableModelError("transient")
        return ModelOutput.from_content("mockllm", "ok")

    transcript = Transcript()
    init_transcript(transcript)
    model = make_mockllm_with_callable(custom_outputs)
    install_retry_classifier(model)
    try:
        await model.generate(
            "x", config=GenerateConfig(max_retries=scenario.max_retries)
        )
    except Exception:
        pass
    assert_no_legacy_rewrite(model_events(transcript))


@given(
    offset=st.floats(min_value=0.0, max_value=60.0, allow_nan=False),
    working_time=st.floats(min_value=0.0, max_value=60.0, allow_nan=False),
)
def test_property_call_working_time_le_wall_duration(
    offset: float, working_time: float
) -> None:
    started = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    completed = started + timedelta(seconds=offset + working_time)
    event = ModelEvent(
        model="x",
        input=[ChatMessageUser(content="x")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("x", "y"),
        call_id="abc",
        attempt=1,
        call_started_at=started,
        call_completed_at=completed,
        call_working_start=0.0,
        call_working_time=working_time,
    )
    assert event.call_completed_at is not None
    assert event.call_started_at is not None
    assert event.call_working_time is not None
    wall = (event.call_completed_at - event.call_started_at).total_seconds()
    assert event.call_working_time <= wall + 1e-6


@given(
    working_now=st.floats(min_value=-100.0, max_value=100.0, allow_nan=False),
    working_start=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
)
def test_property_finalize_clamps_negative_working_time(
    working_now: float, working_start: float
) -> None:
    acc = ModelGenerateAccounting.new(
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        working_start=working_start,
    )
    event = ModelEvent(
        model="x",
        input=[ChatMessageUser(content="x")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("x", "y"),
    )
    acc.finalize_terminal_event(
        event=event,
        completed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        working_now=working_now,
    )
    assert event.call_working_time is not None
    assert event.call_working_time >= 0
