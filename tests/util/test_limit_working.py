from __future__ import annotations

import random
from typing import Generator
from unittest.mock import patch

import anyio
import pytest
from tenacity import retry
from test_helpers.utils import skip_if_no_docker

from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai._util.working import (
    SampleTiming,
    SampleWait,
    _sample_timing,
    add_sample_wait,
    init_sample_working_time,
    report_sample_waiting_time,
    sample_timing,
    sample_wait,
    sample_waiting_time,
    sample_working_time,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import get_model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.model._retry import batch_admin_retry_config, model_retry_config
from inspect_ai.solver._solver import generate
from inspect_ai.solver._use_tools import use_tools
from inspect_ai.tool._tools._execute import bash
from inspect_ai.util._limit import (
    LimitExceededError,
    check_working_limit,
    suspend_working_limit,
    working_limit,
)


@pytest.fixture
def mock_time() -> Generator[_MockTime, None, None]:
    mock = _MockTime()
    with patch("anyio.current_time", side_effect=mock.get_time):
        yield mock


@pytest.fixture
def sample_clock() -> Generator[_MockTime, None, None]:
    """A running sample whose clock starts at 0."""
    clock = _MockTime()
    token = _sample_timing.set(SampleTiming(start_time=0.0, clock=clock.get_time))
    yield clock
    _sample_timing.reset(token)


async def test_can_report_waiting_time_with_no_active_limits() -> None:
    report_sample_waiting_time(10)


async def test_can_check_token_limit_with_no_active_limits() -> None:
    check_working_limit()


async def test_validates_limit_parameter() -> None:
    with pytest.raises(ValueError):
        working_limit(-1)


async def test_can_create_with_none_limit(mock_time: _MockTime) -> None:
    with working_limit(None):
        mock_time.advance(10)
        check_working_limit()


async def test_can_create_with_zero_limit() -> None:
    with working_limit(0):
        pass


async def test_does_not_raise_error_when_limit_not_exceeded() -> None:
    with working_limit(10):
        check_working_limit()


async def test_raises_error_when_limit_exceeded(mock_time: _MockTime) -> None:
    with working_limit(1) as limit:
        with pytest.raises(LimitExceededError) as exc_info:
            mock_time.advance(5)
            check_working_limit()

    assert exc_info.value.type == "working"
    assert exc_info.value.value == 5
    assert exc_info.value.limit == 1
    assert exc_info.value.source is limit


async def test_raises_error_when_limit_repeatedly_exceeded(
    mock_time: _MockTime,
) -> None:
    with working_limit(1):
        with pytest.raises(LimitExceededError):
            mock_time.advance(2)
            check_working_limit()
        with pytest.raises(LimitExceededError) as exc_info:
            mock_time.advance(1)
            check_working_limit()

    assert exc_info.value.value == 3
    assert exc_info.value.limit == 1


async def test_stack_can_trigger_outer_limit(mock_time: _MockTime) -> None:
    with working_limit(1):
        with working_limit(10):
            with pytest.raises(LimitExceededError) as exc_info:
                mock_time.advance(2)
                check_working_limit()

    assert exc_info.value.limit == 1


async def test_stack_can_trigger_inner_limit(mock_time: _MockTime) -> None:
    with working_limit(10):
        with working_limit(1):
            with pytest.raises(LimitExceededError) as exc_info:
                mock_time.advance(2)
                check_working_limit()

    assert exc_info.value.limit == 1


async def test_outer_limit_is_checked_after_inner_limit_popped(
    mock_time: _MockTime,
) -> None:
    with working_limit(1):
        with working_limit(10):
            pass

        with pytest.raises(LimitExceededError) as exc_info:
            mock_time.advance(2)
            check_working_limit()

    assert exc_info.value.limit == 1
    assert exc_info.value.value == 2


async def test_out_of_scope_limits_are_not_checked(mock_time: _MockTime) -> None:
    with working_limit(1):
        pass

    mock_time.advance(2)
    check_working_limit()


async def test_subtracts_waiting_time(sample_clock: _MockTime) -> None:
    with working_limit(1):
        sample_clock.advance(2)
        report_sample_waiting_time(2)
        check_working_limit()

        sample_clock.advance(10)
        with pytest.raises(LimitExceededError) as exc_info:
            check_working_limit()

    assert exc_info.value.value == 10


async def test_subtracts_waiting_time_from_ancestors(sample_clock: _MockTime) -> None:
    with working_limit(2):
        with working_limit(10):
            sample_clock.advance(3)
            report_sample_waiting_time(1)
            check_working_limit()

            with pytest.raises(LimitExceededError) as exc_info:
                sample_clock.advance(1)
                check_working_limit()

    assert exc_info.value.value == 3


async def test_outermost_limit_raises_error_when_multiple_limits_exceeded(
    mock_time: _MockTime,
) -> None:
    with pytest.raises(LimitExceededError) as exc_info:
        with working_limit(1) as outer:
            with working_limit(2):
                mock_time.advance(10)
                check_working_limit()

    # The outermost limit is the one that the error is raised against, despite both
    # limits being exceeded.
    # This prevents sub-agent architectures (e.g. one that dispatches a new sub-agent
    # each time a sub-agent reaches a working limit) from getting stuck in an infinite
    # loop.
    assert exc_info.value.limit == 1
    assert exc_info.value.source is outer


def test_can_get_limit_value() -> None:
    limit = working_limit(10)

    assert limit.limit == 10


async def test_can_get_usage_while_context_manager_open(
    sample_clock: _MockTime,
) -> None:
    with working_limit(10) as limit:
        sample_clock.advance(3)
        report_sample_waiting_time(1)

        assert limit.usage == 2


async def test_can_get_usage_before_context_manager_opened(
    sample_clock: _MockTime,
) -> None:
    limit = working_limit(10)
    sample_clock.advance(3)
    report_sample_waiting_time(1)

    assert limit.usage == 0


async def test_can_get_usage_after_context_manager_closed(
    sample_clock: _MockTime,
) -> None:
    with working_limit(10) as limit:
        sample_clock.advance(3)
        report_sample_waiting_time(1)

    sample_clock.advance(10)
    report_sample_waiting_time(10)

    assert limit.usage == 2


async def test_can_get_usage_nested(mock_time: _MockTime) -> None:
    with working_limit(10) as outer_limit:
        mock_time.advance(3)
        with working_limit(10) as inner_limit:
            mock_time.advance(3)

    assert outer_limit.usage == 6
    assert inner_limit.usage == 3


async def test_can_get_usage_after_limit_error(sample_clock: _MockTime) -> None:
    with pytest.raises(LimitExceededError):
        with working_limit(1) as limit:
            sample_clock.advance(10)
            report_sample_waiting_time(1)
            check_working_limit()

    assert limit.usage == 9


async def test_can_get_remaining(mock_time: _MockTime) -> None:
    limit = working_limit(10)
    with limit:
        mock_time.advance(4)

        assert limit.remaining is not None
        assert limit.remaining == 6


async def test_cannot_reuse_context_manager() -> None:
    limit = working_limit(10)
    with limit:
        pass

    with pytest.raises(RuntimeError) as exc_info:
        # Reusing the same Limit instance.
        with limit:
            pass

    assert "Each Limit may only be used once in a single 'with' block" in str(
        exc_info.value
    )


async def test_cannot_reuse_context_manager_in_stack() -> None:
    limit = working_limit(10)

    with pytest.raises(RuntimeError) as exc_info:
        with limit:
            # Reusing the same Limit instance in a stack.
            with limit:
                pass

    assert "Each Limit may only be used once in a single 'with' block" in str(
        exc_info.value
    )


async def test_interval_union_and_retroactive_insertion(
    sample_clock: _MockTime,
) -> None:
    sample_clock.advance(10)
    add_sample_wait(1, 3)
    add_sample_wait(6, 8)
    assert sample_waiting_time() == 4
    # overlapping and adjacent intervals merge
    add_sample_wait(2, 4)
    add_sample_wait(8, 9)
    assert sample_waiting_time() == 6
    # an interval covering several merges them all
    add_sample_wait(0, 10)
    assert sample_waiting_time() == 10
    assert sample_working_time() == 0


async def test_interval_clipped_to_attempt(sample_clock: _MockTime) -> None:
    sample_clock.advance(2)
    # before the attempt started and after now
    add_sample_wait(-5, 1)
    add_sample_wait(1.5, 20)
    assert sample_waiting_time() == 1.5
    # a report longer than the attempt so far
    report_sample_waiting_time(100)
    assert sample_waiting_time() == 2
    assert sample_working_time() == 0


async def test_waiting_window_with_open_span(sample_clock: _MockTime) -> None:
    add_sample_wait(0, 0)  # empty interval is ignored
    sample_clock.advance(1)
    add_sample_wait(0, 1)
    sample_clock.advance(1)
    wait = SampleWait()
    sample_clock.advance(2)
    add_sample_wait(3, 4)  # inside the open span: counted once
    # windows over closed [0, 1] and open [2, 4]
    assert sample_waiting_time(0, 4) == 3
    assert sample_waiting_time(0.5, 2.5) == 1
    assert sample_waiting_time(3, 4) == 1
    assert sample_waiting_time(1, 2) == 0
    readings = [sample_waiting_time(a, 4) for a in (0, 1, 2, 3)]
    wait.close()
    # closing the span leaves every reading unchanged
    assert [sample_waiting_time(a, 4) for a in (0, 1, 2, 3)] == readings
    wait.close()  # idempotent
    timing = sample_timing()
    assert timing is not None and timing.open_waits == 0


async def test_late_report_overlap_is_deduplicated(sample_clock: _MockTime) -> None:
    sample_clock.advance(3)
    add_sample_wait(0, 1)
    add_sample_wait(1, 3)
    report_sample_waiting_time(1)  # [2, 3] is already counted
    assert sample_waiting_time() == 3


@pytest.mark.parametrize("history,expected", [([(0, 1)], 3), ([(1, 2)], 2)])
async def test_late_report_extends_union(
    history: list[tuple[float, float]], expected: float
) -> None:
    """Histories totalling 1 reach different totals after a late `[1, 3]`."""
    clock = _MockTime()
    init_sample_working_time(0.0, clock.get_time)
    clock.advance(3)
    for start, end in history:
        add_sample_wait(start, end)
    assert sample_waiting_time() == 1
    report_sample_waiting_time(2)  # [1, 3]
    assert sample_waiting_time() == expected


async def test_report_inside_open_native_wait(sample_clock: _MockTime) -> None:
    """A private report inside an open native wait counts once.

    METR's approver reports every second while the native approval wait is
    open.
    """
    with working_limit(None) as sample_limit:
        with suspend_working_limit():
            sample_clock.advance(1)
            with working_limit(None) as scope:
                sample_clock.advance(1)
                report_sample_waiting_time(1)  # [1, 2]
                assert sample_waiting_time(0, 2) == 2
                assert sample_working_time() == 0
                assert sample_limit.usage == 0
                assert scope.usage == 0
        # closing the span leaves the readings unchanged
        assert sample_waiting_time(0, 2) == 2
        assert sample_limit.usage == 0
        assert scope.usage == 0


async def test_retried_attempt_during_open_backoff(sample_clock: _MockTime) -> None:
    """A retried attempt classified during a sibling's backoff counts once."""
    with sample_wait():  # sibling backoff from 2
        sample_clock.advance(2)
        backoff = SampleWait()
        sample_clock.advance(3)
        add_sample_wait(1, 5)  # retried attempt [1, 5], classified at 5
        assert sample_waiting_time() == 5
        sample_clock.advance(1)
        assert sample_waiting_time() == 6
        backoff.close()
        assert sample_waiting_time(0, 6) == 6


async def test_scope_entered_during_later_retried_attempt(
    sample_clock: _MockTime,
) -> None:
    """A scope reads the waits inside its own interval, including late ones.

    The attempt runs 0–8 and is classified as retried at 8; the scope starts
    at 5. A reading difference saved at entry would give -3 at 10.
    """
    sample_clock.advance(5)
    with working_limit(1) as scope:
        sample_clock.advance(3)
        add_sample_wait(0, 8)
        sample_clock.advance(2)
        assert scope.usage == 2
        assert sample_working_time() == 2
        with pytest.raises(LimitExceededError) as exc_info:
            check_working_limit()
    assert exc_info.value.source is scope


async def test_suspend_working_limit_counts_as_waiting(
    sample_clock: _MockTime,
) -> None:
    with working_limit(10) as limit:
        sample_clock.advance(1)
        with suspend_working_limit():
            sample_clock.advance(5)
            assert limit.usage == 1
        sample_clock.advance(1)
        assert limit.usage == 2


async def test_suspend_working_limit_outside_sample(mock_time: _MockTime) -> None:
    with working_limit(10) as limit:
        with suspend_working_limit():
            mock_time.advance(5)
        assert limit.usage == 5


async def test_retry_backoff_and_retried_attempts_are_waits(
    sample_clock: _MockTime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The backoff sleep is an open wait that closes when cancelled."""
    sleeping = anyio.Event()

    async def fake_sleep(seconds: float) -> None:
        sample_clock.advance(2)
        sleeping.set()
        await anyio.sleep_forever()

    monkeypatch.setattr("inspect_ai.model._retry._sleep", fake_sleep)

    @retry(
        **model_retry_config(
            "m",
            None,
            None,
            lambda ex: True,
            lambda ex: None,
            lambda m, rs: None,
            sample_waits=True,
        )
    )
    async def attempt() -> None:
        sample_clock.advance(1)
        raise RuntimeError("retryable")

    timing = sample_timing()
    assert timing is not None
    with working_limit(None) as limit:
        sample_clock.advance(1)
        async with anyio.create_task_group() as tg:
            tg.start_soon(attempt)
            await sleeping.wait()
            assert timing.open_waits == 1
            # the retried attempt [1, 2] and the backoff so far [2, 4]
            assert sample_waiting_time() == 3
            assert limit.usage == 1
            tg.cancel_scope.cancel()
    assert timing.open_waits == 0
    assert sample_waiting_time() == 3


def test_batch_admin_retries_record_no_sample_waits() -> None:
    config = batch_admin_retry_config("m", GenerateConfig(), lambda ex: True)
    assert "sleep" not in config
    assert "after" not in config


@pytest.mark.parametrize("seed", range(20))
async def test_random_waits_match_union(seed: int) -> None:
    """Random waits always read as the union of the intervals."""
    rng = random.Random(seed)
    clock = _MockTime()
    init_sample_working_time(0.0, clock.get_time)
    timing = sample_timing()
    assert timing is not None
    closed: list[tuple[float, float]] = []
    open_spans: list[tuple[SampleWait, float]] = []
    for _ in range(200):
        op = rng.random()
        if op < 0.3:
            clock.advance(rng.choice([0, rng.random() * 3]))
        elif op < 0.45:
            open_spans.append((SampleWait(), clock.get_time()))
        elif op < 0.6 and open_spans:
            wait, start = open_spans.pop(rng.randrange(len(open_spans)))
            wait.close()
            closed.append((start, clock.get_time()))
        elif op < 0.8:
            now = clock.get_time()
            start = rng.uniform(-1, now + 1)
            end = rng.uniform(start, now + 2)
            add_sample_wait(start, end)
            closed.append((max(start, 0), min(end, now)))
        else:
            seconds = rng.random() * 4
            now = clock.get_time()
            report_sample_waiting_time(seconds)
            closed.append((max(now - seconds, 0), now))
        _check_readings(rng, timing, clock.get_time(), closed, open_spans)


def _check_readings(
    rng: random.Random,
    timing: SampleTiming,
    now: float,
    closed: list[tuple[float, float]],
    open_spans: list[tuple[SampleWait, float]],
) -> None:
    intervals = closed + [(start, now) for _, start in open_spans]
    assert 0 <= sample_working_time() <= now + 1e-9
    assert sample_waiting_time() == pytest.approx(_union(intervals, 0, now))
    for _ in range(3):
        a = rng.uniform(0, now)
        b = rng.uniform(a, now)
        waiting = sample_waiting_time(a, b)
        assert waiting == pytest.approx(_union(intervals, a, b), abs=1e-9)
        assert -1e-9 <= (b - a) - waiting <= b - a + 1e-9


def _union(intervals: list[tuple[float, float]], a: float, b: float) -> float:
    clipped = sorted(
        (max(s, a), min(e, b)) for s, e in intervals if min(e, b) > max(s, a)
    )
    total = 0.0
    cur_s, cur_e = None, None
    for s, e in clipped:
        if cur_e is None or s > cur_e:
            if cur_e is not None and cur_s is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None and cur_s is not None:
        total += cur_e - cur_s
    return total


def test_working_limit_interrupts_local_sandbox_exec():
    check_working_limit_interrupts_sandbox_exec("local")


@pytest.mark.slow
@skip_if_no_docker
def test_working_limit_interrupts_docker_sandbox_exec():
    check_working_limit_interrupts_sandbox_exec("docker")


def check_working_limit_interrupts_sandbox_exec(sandbox: str):
    task = Task(
        solver=[use_tools([bash()]), generate()],
        sandbox=sandbox,
    )
    log = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="bash",
                    tool_arguments={"command": "sleep 100"},
                )
            ],
        ),
        working_limit=1,
    )[0]

    assert log.samples
    assert log.samples[0].limit
    assert log.samples[0].limit.type == "working"


class _MockTime:
    def __init__(self) -> None:
        self._current_time = 0.0

    def get_time(self) -> float:
        return self._current_time

    def advance(self, seconds: float) -> float:
        self._current_time += seconds
        return self._current_time
