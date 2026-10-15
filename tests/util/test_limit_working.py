from __future__ import annotations

import random
from contextvars import Context, copy_context
from dataclasses import dataclass, field
from typing import Any, Callable, Generator, Literal, overload
from unittest.mock import patch

import anyio
import pytest
from tenacity import retry
from test_helpers.utils import skip_if_no_docker

from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai._util.working import (
    ModelAttempts,
    SampleTiming,
    SampleWait,
    _sample_timing,
    add_sample_wait,
    init_sample_working_time,
    known_work,
    report_sample_waiting_time,
    sample_timing,
    sample_wait,
    sample_waiting_time,
    sample_working_time,
    untracked_sandbox_execs,
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
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from inspect_ai.util._sandbox.events import SandboxEnvironmentProxy
from inspect_ai.util._subprocess import ExecResult


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


class _Task:
    """A task context (a copied `Context`) for driving spans step by step."""

    def __init__(self, parent: _Task | None = None) -> None:
        self.ctx: Context = parent.ctx.run(copy_context) if parent else copy_context()

    def enter(self, cm: Any) -> Any:
        self.ctx.run(cm.__enter__)
        return cm

    def exit(self, cm: Any) -> None:
        self.ctx.run(cm.__exit__, None, None, None)

    def wait(self) -> SampleWait:
        return self.ctx.run(SampleWait)


async def test_known_work_overrides_sibling_wait(sample_clock: _MockTime) -> None:
    waiter, worker = _Task(), _Task()
    wait = waiter.wait()
    sample_clock.advance(1)
    work = worker.enter(known_work())
    sample_clock.advance(2)
    assert sample_waiting_time() == 1
    worker.exit(work)
    sample_clock.advance(1)
    wait.close()
    assert sample_waiting_time() == 2
    assert sample_waiting_time(1, 3) == 0


async def test_wait_in_own_context_holds_work(sample_clock: _MockTime) -> None:
    """A wait in the work's own context (or a task it started) holds it."""
    tool = _Task()
    work = tool.enter(known_work())
    sample_clock.advance(1)
    queued = tool.wait()  # e.g. its exec queued on max_subprocesses
    sample_clock.advance(2)
    assert sample_waiting_time() == 2
    queued.close()
    sample_clock.advance(1)
    child = _Task(tool)
    approval = child.enter(sample_wait())
    sample_clock.advance(2)
    child.exit(approval)
    tool.exit(work)
    assert sample_waiting_time() == 4
    assert sample_working_time() == 2


async def test_work_inside_suspension_is_not_known_work(
    sample_clock: _MockTime,
) -> None:
    """An approver's or monitor's own model call does not restart the clock."""
    agent = _Task()
    with suspend_working_limit():
        monitor = _Task()
        attempts = ModelAttempts()
        attempt = monitor.enter(attempts.attempt())
        tool = monitor.enter(known_work())
        sample_clock.advance(3)
        monitor.exit(tool)
        monitor.exit(attempt)
        attempts.commit()
    work = agent.enter(known_work())
    sample_clock.advance(1)
    agent.exit(work)
    assert sample_waiting_time() == 3
    assert sample_working_time() == 1


async def test_retried_attempt_keeps_sibling_work(sample_clock: _MockTime) -> None:
    """Only the part of a retried attempt with no other known work is waiting.

    The attempt runs 0-8 and is classified as retried at 8; a sibling tool
    call runs 1-4.
    """
    attempts = ModelAttempts()
    sibling = _Task()

    @retry(
        **model_retry_config(
            "m",
            0,
            None,
            lambda ex: True,
            lambda ex: None,
            lambda m, rs: None,
            sample_waits=True,
            attempts=attempts,
        )
    )
    async def attempt() -> None:
        with attempts.attempt():
            sample_clock.advance(1)
            tool = sibling.enter(known_work())
            sample_clock.advance(3)
            sibling.exit(tool)
            sample_clock.advance(4)
            # in flight, the attempt is known work
            assert sample_waiting_time() == 0
            raise RuntimeError("retryable")

    with working_limit(None) as limit:
        with pytest.raises(Exception):
            await attempt()
        attempts.commit()  # nothing pending: the retry loop dropped it
        assert sample_waiting_time() == 5
        assert limit.usage == 3


async def test_attempt_charged_unless_retried(sample_clock: _MockTime) -> None:
    """A successful attempt is work, except the part split off as SDK retries."""
    attempts = ModelAttempts()
    caller, waiter = _Task(), _Task()
    wait = waiter.wait()
    attempt = caller.enter(attempts.attempt())
    sample_clock.advance(8)
    caller.exit(attempt)
    assert sample_waiting_time() == 0
    # the request took the last 2 s; the SDK retried before it
    add_sample_wait(0, 6)
    attempts.exclude_before(6)
    assert sample_waiting_time() == 6
    attempts.commit()
    assert sample_waiting_time() == 6
    sample_clock.advance(1)
    wait.close()
    assert sample_waiting_time() == 7


async def test_nested_attempt_holds_enclosing_tool(sample_clock: _MockTime) -> None:
    """A tool's nested model call owns its time, so a retry makes it a wait."""
    tool_task = _Task()
    attempts = ModelAttempts()
    tool = tool_task.enter(known_work())
    sample_clock.advance(2)
    attempt = tool_task.enter(attempts.attempt())
    sample_clock.advance(4)
    tool_task.exit(attempt)
    add_sample_wait(2, 6)
    attempts.retried()
    sample_clock.advance(4)
    tool_task.exit(tool)
    assert sample_waiting_time() == 4
    assert sample_working_time() == 6


async def test_late_wait_withdraws_own_work(sample_clock: _MockTime) -> None:
    """A wait reported after the fact is not covered by its own context's work.

    The outer tool opens at 0 and an inner tool in a task it started at 2;
    the inner task reports the last 5 s as waiting at 5.
    """
    outer = _Task()
    outer_work = outer.enter(known_work())
    sample_clock.advance(2)
    inner = _Task(outer)
    inner_work = inner.enter(known_work())
    sample_clock.advance(3)
    inner.ctx.run(report_sample_waiting_time, 5)
    assert sample_waiting_time() == 5
    sample_clock.advance(1)
    inner.exit(inner_work)
    outer.exit(outer_work)
    assert sample_waiting_time() == 5
    assert sample_working_time() == 1


@pytest.mark.parametrize("helper", ["report_sample_waiting_time", "add_sample_wait"])
@pytest.mark.parametrize("suspension", [sample_wait, suspend_working_limit])
@pytest.mark.parametrize("sibling", [False, True])
async def test_late_wait_inside_suspension_withdraws_own_work(
    sample_clock: _MockTime,
    helper: str,
    suspension: Callable[[], Any],
    sibling: bool,
) -> None:
    """A wait reported inside a suspension still withdraws its context's work.

    A tool runs from 0, enters a suspension at 3 and reports `[0, 5]` at 5.
    An independent sibling working over `[1, 2]` stays charged.
    """
    with working_limit(None) as scope:
        tool, other = _Task(), _Task()
        tool_work = tool.enter(known_work())
        sample_clock.advance(1)
        sibling_work = other.enter(known_work()) if sibling else None
        sample_clock.advance(1)
        if sibling_work is not None:
            other.exit(sibling_work)
        sample_clock.advance(1)
        suspended = tool.enter(suspension())
        sample_clock.advance(2)
        if helper == "report_sample_waiting_time":
            tool.ctx.run(report_sample_waiting_time, 5)
        else:
            tool.ctx.run(add_sample_wait, 0, 5)
        working = 1 if sibling else 0
        assert sample_working_time() == working
        assert scope.usage == working
        tool.exit(suspended)
        tool.exit(tool_work)
        assert sample_working_time() == working
        assert sample_waiting_time() == 5 - working
        assert scope.usage == working


async def test_late_wait_keeps_sibling_work(sample_clock: _MockTime) -> None:
    tool, sibling = _Task(), _Task()
    tool_work = tool.enter(known_work())
    sibling_work = sibling.enter(known_work())
    sample_clock.advance(5)
    tool.ctx.run(add_sample_wait, 0, 5)
    assert sample_waiting_time() == 0
    tool.exit(tool_work)
    sibling.exit(sibling_work)
    assert sample_waiting_time() == 0


async def test_task_outliving_inner_span_holds_open_ancestor(
    sample_clock: _MockTime,
) -> None:
    """A task started by a closed inner tool still holds the outer tool.

    For example, a background agent dispatched by a tool that has returned,
    inside an agent running as a tool.
    """
    outer = _Task()
    outer_work = outer.enter(known_work())
    inner = _Task(outer)
    inner_work = inner.enter(known_work())
    background = _Task(inner)
    inner.exit(inner_work)
    sample_clock.advance(1)
    wait = background.enter(sample_wait())
    sample_clock.advance(5)
    background.exit(wait)
    assert sample_waiting_time() == 5
    # a model attempt from the same task holds the outer tool, and is retried
    attempts = ModelAttempts()
    attempt = background.enter(attempts.attempt())
    sample_clock.advance(2)
    background.exit(attempt)
    background.ctx.run(add_sample_wait, 6, 8)
    attempts.retried()
    outer.exit(outer_work)
    assert sample_waiting_time() == 7
    assert sample_working_time() == 1


async def test_wait_outlasting_its_span_keeps_ancestor_held(
    sample_clock: _MockTime,
) -> None:
    outer = _Task()
    outer_work = outer.enter(known_work())
    inner = _Task(outer)
    inner_work = inner.enter(known_work())
    wait = _Task(inner).wait()
    inner.exit(inner_work)
    sample_clock.advance(5)
    assert sample_waiting_time() == 5
    wait.close()
    sample_clock.advance(1)
    outer.exit(outer_work)
    assert sample_waiting_time() == 5
    assert sample_working_time() == 1


async def test_exec_beside_event_suppressed_exec_is_known_work(
    sample_clock: _MockTime,
) -> None:
    """`no_events()` in one task does not make another task's exec unseen."""
    sandbox = _GatedSandbox(sample_clock)
    proxy = SandboxEnvironmentProxy(sandbox)
    wait = SampleWait()
    polling = anyio.Event()

    async def poll() -> None:
        with proxy.no_events():
            polling.set()
            await proxy.exec(["poll"])

    async with anyio.create_task_group() as tg:
        tg.start_soon(poll)
        await polling.wait()
        await proxy.exec(["work"])
        assert sample_waiting_time() == 0
        sandbox.release.set()
    wait.close()
    assert sample_waiting_time() == 0


@pytest.mark.parametrize(
    "cmd",
    [
        ["sh", "-c", "work # /var/tmp/sandbox-services"],
        ["ls", "/var/tmp", "sandbox-services"],
    ],
)
async def test_exec_naming_service_directory_is_known_work(
    sample_clock: _MockTime, cmd: list[str]
) -> None:
    """Whether an exec is known work never depends on its command text."""
    proxy = SandboxEnvironmentProxy(_GatedSandbox(sample_clock))
    wait = SampleWait()
    await proxy.exec(cmd)
    wait.close()
    assert sample_waiting_time() == 0


async def test_untracked_sandbox_execs_are_not_known_work(
    sample_clock: _MockTime,
) -> None:
    """Inspect's own plumbing (sandbox service commands, polls) is not known work."""
    proxy = SandboxEnvironmentProxy(_GatedSandbox(sample_clock))
    wait = SampleWait()
    with untracked_sandbox_execs():
        await proxy.exec(["work"])
    wait.close()
    assert sample_waiting_time() == 5


class _GatedSandbox(SandboxEnvironment):
    """`poll` waits for `release`; any other command takes 5 s on the sample clock."""

    def __init__(self, clock: _MockTime) -> None:
        super().__init__()
        self.clock = clock
        self.release = anyio.Event()

    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        if cmd == ["poll"]:
            await self.release.wait()
        else:
            self.clock.advance(5)
        return ExecResult(success=True, returncode=0, stdout="", stderr="")

    async def write_file(self, file: str, contents: str | bytes) -> None:
        raise NotImplementedError()

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    async def read_file(self, file: str, text: bool = True) -> str | bytes:
        raise NotImplementedError()

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        pass


@pytest.mark.parametrize("seed", range(30))
async def test_random_work_and_waits_match_reference(seed: int) -> None:
    """Readings match a brute-force evaluation of the rule, within bounds.

    Waits and known work open and close in separate tasks, nested in each
    other's contexts (closed spans' contexts included, as for a task that
    outlives the span that started it), with late waits reported from inside
    work and attempts classified after the fact.
    """
    rng = random.Random(seed)
    clock = _MockTime()
    init_sample_working_time(0.0, clock.get_time)
    model = _RuleModel(clock)
    scopes: list[tuple[Any, float]] = []
    for _ in range(250):
        op = rng.random()
        open_spans = [s for s in model.spans if not s.closed]
        context = (
            rng.choice(model.spans) if model.spans and rng.random() < 0.6 else None
        )
        if op < 0.25:
            clock.advance(rng.choice([0, rng.random() * 3]))
        elif op < 0.37:
            model.open_span(context, attempt=rng.random() < 0.4)
        elif op < 0.47 and open_spans:
            model.close_span(rng.choice(open_spans))
        elif op < 0.57:
            model.open_wait(context)
        elif op < 0.67 and model.open_waits:
            model.close_wait(rng.randrange(len(model.open_waits)))
        elif op < 0.75:
            closed = [s for s in model.spans if s.attempts and s.closed and not s.done]
            if closed:
                model.classify(rng.choice(closed), retried=rng.random() < 0.5)
        elif op < 0.85:
            now = clock.get_time()
            start = rng.uniform(-1, now + 1)
            end = rng.uniform(start, now + 2)
            model.late_wait(
                context, start, end, add_sample_wait, suspended=rng.random() < 0.3
            )
        elif op < 0.9:
            scope = working_limit(None)
            scope.__enter__()
            scopes.append((scope, clock.get_time()))
        else:
            now = clock.get_time()
            model.late_wait(
                context,
                now - rng.random() * 4,
                now,
                lambda start, end: report_sample_waiting_time(end - start),
                suspended=rng.random() < 0.3,
            )
        _check_rule(rng, model, scopes)
    # closing everything leaves every reading unchanged
    now = clock.get_time()
    windows = [(rng.uniform(0, now), now) for _ in range(5)] + [(0, now)]
    before = [sample_waiting_time(a, b) for a, b in windows]
    for span in [s for s in model.spans if not s.closed]:
        model.close_span(span)
    while model.open_waits:
        model.close_wait(0)
    for span in [s for s in model.spans if s.attempts and not s.done]:
        model.classify(span, retried=False)
    after = [sample_waiting_time(a, b) for a, b in windows]
    assert after == pytest.approx(before, abs=1e-9)
    _check_rule(rng, model, scopes)


@dataclass
class _Span:
    task: _Task
    inner: _Task  # a task started while the span was open
    cm: Any
    parent: _Span | None
    attempts: ModelAttempts | None
    opened: float
    segments: list[tuple[float, float]] = field(default_factory=list)
    active: float | None = None
    holds: int = 0
    closed: bool = False
    done: bool = False  # an attempt that has been classified
    dropped: bool = False


class _RuleModel:
    """Drives the implementation and tracks the waits and work it should see."""

    def __init__(self, clock: _MockTime) -> None:
        self.clock = clock
        self.spans: list[_Span] = []
        self.waits: list[tuple[float, float]] = []
        self.open_waits: list[tuple[SampleWait, _Span | None, float]] = []

    def open_span(self, parent: _Span | None, attempt: bool) -> None:
        task = _Task(parent.inner if parent else None)
        attempts = ModelAttempts() if attempt else None
        cm = attempts.attempt() if attempts else known_work()
        task.enter(cm)
        now = self.clock.get_time()
        span = _Span(task, _Task(task), cm, parent, attempts, now, active=now)
        if parent is not None:
            self._hold(parent)
        self.spans.append(span)

    def close_span(self, span: _Span) -> None:
        span.task.exit(span.cm)
        self._end(span)
        span.closed = True
        if span.holds == 0 and span.parent is not None:
            self._release(span.parent)

    def open_wait(self, span: _Span | None) -> None:
        task = _Task(span.inner if span else None)
        self.open_waits.append((task.wait(), span, self.clock.get_time()))
        if span is not None:
            self._hold(span)

    def close_wait(self, index: int) -> None:
        wait, span, start = self.open_waits.pop(index)
        wait.close()
        self.waits.append((start, self.clock.get_time()))
        if span is not None:
            self._release(span)

    def classify(self, span: _Span, retried: bool) -> None:
        assert span.attempts is not None
        span.done = True
        if retried:
            # the retry loop runs in the context that started the attempt
            span.dropped = True
            self.late_wait(
                span.parent, span.opened, self.clock.get_time(), add_sample_wait
            )
            span.attempts.retried()
        else:
            span.attempts.commit()

    def late_wait(
        self,
        context: _Span | None,
        start: float,
        end: float,
        report: Callable[[float, float], None],
        suspended: bool = False,
    ) -> None:
        """Report a wait after the fact from inside `context`'s work.

        With `suspended`, the report is made inside a `sample_wait()` opened
        at that instant, as an approver or monitor would.
        """

        def run() -> None:
            if suspended:
                with sample_wait():
                    report(start, end)
            else:
                report(start, end)

        _Task(context.inner if context else None).ctx.run(run)
        now = self.clock.get_time()
        start, end = max(start, 0), min(end, now)
        if end <= start:
            return
        self.waits.append((start, end))
        while context is not None:
            active = context.active is not None
            self._end(context)
            context.segments = [
                piece
                for s, e in context.segments
                for piece in ([(s, e)] if e <= start or s >= end else [])
                + ([(s, start)] if s < start < e else [])
                + ([(end, e)] if s < end < e else [])
            ]
            if active:
                context.active = now
            context = context.parent

    def intervals(self) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        now = self.clock.get_time()
        waits = self.waits + [(start, now) for _, _, start in self.open_waits]
        work: list[tuple[float, float]] = []
        for span in self.spans:
            if not span.dropped:
                work += span.segments
                if span.active is not None:
                    work.append((span.active, now))
        return waits, work

    def _hold(self, span: _Span) -> None:
        if span.holds == 0:
            if span.closed:
                if span.parent is not None:
                    self._hold(span.parent)
            else:
                self._end(span)
        span.holds += 1

    def _release(self, span: _Span) -> None:
        span.holds -= 1
        if span.holds == 0:
            if span.closed:
                if span.parent is not None:
                    self._release(span.parent)
            else:
                span.active = self.clock.get_time()

    def _end(self, span: _Span) -> None:
        if span.active is not None:
            span.segments.append((span.active, self.clock.get_time()))
            span.active = None


def _check_rule(
    rng: random.Random, model: _RuleModel, scopes: list[tuple[Any, float]]
) -> None:
    now = model.clock.get_time()
    waits, work = model.intervals()
    assert 0 <= sample_working_time() <= now + 1e-9
    assert sample_waiting_time() == pytest.approx(
        _rule_waiting(waits, work, 0, now), abs=1e-9
    )
    for _ in range(3):
        a = rng.uniform(0, now)
        b = rng.uniform(a, now)
        waiting = sample_waiting_time(a, b)
        assert waiting == pytest.approx(_rule_waiting(waits, work, a, b), abs=1e-9)
        assert -1e-9 <= (b - a) - waiting <= b - a + 1e-9
    for scope, start in scopes:
        assert -1e-9 <= scope.usage <= now - start + 1e-9


def _rule_waiting(
    waits: list[tuple[float, float]],
    work: list[tuple[float, float]],
    a: float,
    b: float,
) -> float:
    """Length of `[a, b]` inside some wait and outside all known work."""
    points = sorted({a, b} | {x for s, e in waits + work for x in (s, e) if a < x < b})
    total = 0.0
    for lo, hi in zip(points, points[1:]):
        mid = (lo + hi) / 2
        if any(s <= mid <= e for s, e in waits) and not any(
            s <= mid <= e for s, e in work
        ):
            total += hi - lo
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
