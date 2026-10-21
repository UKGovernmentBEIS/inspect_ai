from __future__ import annotations

import contextlib
import functools
import json
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
from inspect_ai._util.registry import _registry
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
    sample_waiting_for,
    sample_waiting_time,
    sample_working_time,
    untracked_sandbox_execs,
)
from inspect_ai.agent import sandbox_agent_bridge
from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.sandbox.service import call_tool
from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import ModelAPI, get_model
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput, ModelUsage
from inspect_ai.model._registry import modelapi
from inspect_ai.model._retry import batch_admin_retry_config, model_retry_config
from inspect_ai.solver._solver import generate
from inspect_ai.solver._use_tools import use_tools
from inspect_ai.tool._tool import Tool, tool
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo
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


@pytest.mark.parametrize("suspension", [sample_wait, suspend_working_limit])
def test_suspension_outside_sample_leaves_sample_work_known(
    suspension: Callable[[], Any],
) -> None:
    """A suspension entered outside a sample (around `eval()`, say) is a no-op.

    A sample started inside it still charges its known work beside a wait.
    """
    clock = _MockTime()

    def run() -> None:
        _sample_timing.set(None)
        with suspension():
            init_sample_working_time(0.0, clock.get_time)
            with working_limit(None) as scope:
                waiter, worker = _Task(), _Task()
                wait = waiter.wait()
                work = worker.enter(known_work())
                clock.advance(5)
                worker.exit(work)
                wait.close()
                assert sample_waiting_time() == 0
                assert sample_working_time() == 5
                assert scope.usage == 5

    copy_context().run(run)


@pytest.mark.parametrize("suspension", [sample_wait, suspend_working_limit])
@pytest.mark.parametrize("form", ["sample_wait", "SampleWait", "sample_waiting_for"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_child_wait_outliving_suspension_holds_work(
    sample_clock: _MockTime,
    suspension: Callable[[], Any],
    form: str,
    cancel: bool,
) -> None:
    """A task started inside a tool's suspension holds the tool while it waits.

    The suspension runs 0-1; the child task it started waits until 6, ends
    (or is cancelled), and the tool works 6-7.
    """
    started = anyio.Event()
    release = anyio.Event()
    lock = anyio.Semaphore(0)

    async def child() -> None:
        if form == "sample_wait":
            with sample_wait():
                started.set()
                await release.wait()
        elif form == "SampleWait":
            wait = SampleWait()
            started.set()
            try:
                await release.wait()
            finally:
                wait.close()
        else:
            started.set()
            async with sample_waiting_for(lock):
                pass

    with working_limit(None) as scope, known_work():
        async with anyio.create_task_group() as tg:
            with suspension():
                tg.start_soon(child)
                await started.wait()
                sample_clock.advance(1)
            sample_clock.advance(5)
            assert sample_waiting_time() == 6
            assert scope.usage == 0
            if cancel:
                tg.cancel_scope.cancel()
            else:
                release.set()
                lock.release()
        timing = sample_timing()
        assert timing is not None and timing.open_waits == 0
        sample_clock.advance(1)
        assert sample_waiting_time() == 6
        assert scope.usage == 1
    assert sample_working_time() == 1


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


@pytest.mark.parametrize("inside_tool", [False, True])
async def test_retried_attempt_keeps_sibling_work(
    sample_clock: _MockTime, inside_tool: bool
) -> None:
    """Only the part of a retried attempt with no other known work is waiting.

    The attempt runs 0-8 and is classified as retried at 8; a sibling tool
    call runs 1-4. Inside a tool, the sibling's finished work is handed to
    the tool, and the retry's wait leaves it charged.
    """
    attempts = ModelAttempts()

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
    async def attempt(sibling: _Task) -> None:
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
        with known_work() if inside_tool else contextlib.nullcontext():
            with pytest.raises(Exception):
                await attempt(_Task())
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


@pytest.mark.parametrize("helper", ["report_sample_waiting_time", "add_sample_wait"])
@pytest.mark.parametrize("operation", ["generate", "exec", "known_work"])
@pytest.mark.parametrize("sibling", [False, True])
async def test_late_wait_withdraws_completed_operation(
    sample_clock: _MockTime, helper: str, operation: str, sibling: bool
) -> None:
    """A wait reported inside a tool withdraws the tool's finished operations.

    Inside a tool, an operation runs over `[0, 5]` and returns; the tool then
    reports `[0, 5]` as waiting. An independent sibling working over `[1, 2]`
    stays charged.
    """
    other = _Task()

    def elapse() -> None:
        sample_clock.advance(1)
        sibling_work = other.enter(known_work()) if sibling else None
        sample_clock.advance(1)
        if sibling_work is not None:
            other.exit(sibling_work)
        sample_clock.advance(3)

    def output(*_: Any) -> ModelOutput:
        elapse()
        return ModelOutput()

    with working_limit(None) as scope:
        with known_work():
            if operation == "generate":
                model = get_model("mockllm/model", custom_outputs=output, memoize=False)
                await model.generate("hello")
            elif operation == "exec":
                await SandboxEnvironmentProxy(_GatedSandbox(sample_clock, elapse)).exec(
                    ["work"]
                )
            else:
                with known_work():
                    elapse()
            assert sample_working_time() == 5
            if helper == "report_sample_waiting_time":
                report_sample_waiting_time(5)
            else:
                add_sample_wait(0, 5)
            working = 1 if sibling else 0
            assert sample_working_time() == working
            assert sample_waiting_time() == 5 - working
            assert scope.usage == working
        assert sample_working_time() == working
        assert sample_waiting_time() == 5 - working
        assert scope.usage == working


async def test_sdk_retry_wait_keeps_finished_sibling_work(
    sample_clock: _MockTime,
) -> None:
    """The SDK-retry part of an attempt does not withdraw a sibling that finished.

    Inside a tool, a generate runs over `[0, 5]` and its request took the
    last 2 s; a task the tool started works over `[1, 2]` and returns.
    """

    class ClockAPI(ModelAPI):
        async def generate(
            self,
            input: list[ChatMessage],
            tools: list[ToolInfo],
            tool_choice: ToolChoice,
            config: GenerateConfig,
        ) -> tuple[ModelOutput, ModelCall]:
            sample_clock.advance(1)
            work = sibling.enter(known_work())
            sample_clock.advance(1)
            sibling.exit(work)
            sample_clock.advance(3)
            return ModelOutput(), ModelCall.create({}, {}, time=2)

    @modelapi(name="working_clock")
    def working_clock() -> type[ModelAPI]:
        return ClockAPI

    try:
        with known_work():
            sibling = _Task()
            await get_model("working_clock/m", memoize=False).generate("hello")
    finally:
        del _registry["modelapi:working_clock"]
    assert sample_waiting_time() == 2
    assert sample_working_time() == 3


async def test_late_wait_at_top_level_leaves_finished_work(
    sample_clock: _MockTime,
) -> None:
    """Outside any known work, a late report has no finished work to withdraw."""
    with known_work():
        sample_clock.advance(5)
    report_sample_waiting_time(5)
    assert sample_waiting_time() == 0
    with sample_wait():
        with known_work():
            sample_clock.advance(5)
    assert sample_waiting_time() == 5


async def test_late_wait_after_parentless_tool_closes_leaves_its_work(
    sample_clock: _MockTime,
) -> None:
    """A top-level tool's work is dropped from late reports once it closes.

    The tool works over `[0, 5]` and starts a task; work that task does under
    the closed tool is dropped too. Reports from that task then leave both
    charged, as a report from the sample's top level would.
    """
    tool = _Task()
    tool_work = tool.enter(known_work())
    background = _Task(tool)
    sample_clock.advance(5)
    tool.exit(tool_work)
    work = background.enter(known_work())
    sample_clock.advance(1)
    background.exit(work)
    background.ctx.run(add_sample_wait, 0, 6)
    background.ctx.run(add_sample_wait, 0, 6, False)
    assert sample_waiting_time() == 0
    assert sample_working_time() == 6


@pytest.mark.parametrize("operation", ["count_tokens", "compact"])
@pytest.mark.parametrize("case", ["beside_wait", "retried", "retried_in_tool"])
async def test_token_count_and_compact_attempts_are_known_work(
    sample_clock: _MockTime,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    case: str,
) -> None:
    """A `count_tokens()` or `compact()` attempt is known work, like a generate.

    Each attempt takes 2. Beside another task's open wait, a successful
    attempt is working. A retried attempt is waiting, and a tool around it is
    not charged for it; the attempt that then succeeds is working.
    """
    attempts = 0

    async def attempt() -> None:
        nonlocal attempts
        attempts += 1
        sample_clock.advance(2)
        if case != "beside_wait" and attempts == 1:
            raise RuntimeError("retryable")

    class ClockAPI(ModelAPI):
        async def generate(
            self,
            input: list[ChatMessage],
            tools: list[ToolInfo],
            tool_choice: ToolChoice,
            config: GenerateConfig,
        ) -> ModelOutput:
            raise NotImplementedError()

        async def count_tokens(
            self, input: str | list[ChatMessage], config: GenerateConfig | None = None
        ) -> int:
            await attempt()
            return 1

        async def compact(
            self,
            input: list[ChatMessage],
            tools: list[ToolInfo],
            config: GenerateConfig,
            instructions: str | None = None,
        ) -> tuple[list[ChatMessage], ModelUsage | None]:
            await attempt()
            return input, None

        def should_retry(self, ex: Exception) -> bool:
            return isinstance(ex, RuntimeError)

    async def no_sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr("inspect_ai.model._retry._sleep", no_sleep)

    @modelapi(name="working_attempt_clock")
    def working_attempt_clock() -> type[ModelAPI]:
        return ClockAPI

    waiting = 0 if case == "beside_wait" else 2
    try:
        model = get_model("working_attempt_clock/m", memoize=False)
        wait = _Task().wait() if case == "beside_wait" else None
        with working_limit(None) as scope:
            tool = known_work() if case == "retried_in_tool" else None
            with tool if tool is not None else contextlib.nullcontext():
                if operation == "count_tokens":
                    await model.count_tokens("count")
                else:
                    await model.compact([ChatMessageUser(content="compact")], [])
                assert sample_working_time() == 2
                assert sample_waiting_time() == waiting
                assert scope.usage == 2
        if wait is not None:
            wait.close()
        assert sample_working_time() == 2
        assert sample_waiting_time() == waiting
        assert scope.usage == 2
    finally:
        del _registry["modelapi:working_attempt_clock"]


@pytest.mark.parametrize("operation", ["count_tokens", "compact", "generate"])
@pytest.mark.parametrize("sibling", [False, True])
async def test_retry_wait_withdraws_closed_ancestors_own_work(
    sample_clock: _MockTime,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    sibling: bool,
) -> None:
    """A retried attempt's wait withdraws the work of a tool that has returned.

    Inside an outer tool, an inner tool starts a background task and returns
    at 2. The task's model call runs from 0 and its attempt fails at 5 and is
    retried. For generate, the time before the provider call is the inner
    tool's own work; for `count_tokens()` and `compact()`, the attempt holds
    the inner tool. A sibling under the outer tool works over `[1, 2]` and
    stays charged.
    """
    ready, inner_closed = anyio.Event(), anyio.Event()
    other: _Task | None = None
    attempts = 0

    def before_attempt() -> None:
        sample_clock.advance(1)
        work = other.enter(known_work()) if sibling and other else None
        sample_clock.advance(1)
        if work is not None and other is not None:
            other.exit(work)

    async def attempt() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            if operation != "generate":
                before_attempt()
            ready.set()
            await inner_closed.wait()
            sample_clock.advance(3)
            raise RuntimeError("retryable")

    class ClockAPI(ModelAPI):
        async def generate(
            self,
            input: list[ChatMessage],
            tools: list[ToolInfo],
            tool_choice: ToolChoice,
            config: GenerateConfig,
        ) -> ModelOutput:
            await attempt()
            return ModelOutput()

        async def count_tokens(
            self, input: str | list[ChatMessage], config: GenerateConfig | None = None
        ) -> int:
            await attempt()
            return 1

        async def compact(
            self,
            input: list[ChatMessage],
            tools: list[ToolInfo],
            config: GenerateConfig,
            instructions: str | None = None,
        ) -> tuple[list[ChatMessage], ModelUsage | None]:
            await attempt()
            return input, None

        def should_retry(self, ex: Exception) -> bool:
            return isinstance(ex, RuntimeError)

    checks = 0

    def check_limits_before_dispatch() -> None:
        nonlocal checks
        checks += 1
        if checks == 1:
            before_attempt()

    async def no_sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr("inspect_ai.model._retry._sleep", no_sleep)
    monkeypatch.setattr(
        "inspect_ai.model._model._check_limits_before_dispatch",
        check_limits_before_dispatch,
    )

    @modelapi(name="working_retry_clock")
    def working_retry_clock() -> type[ModelAPI]:
        return ClockAPI

    async def background() -> None:
        model = get_model("working_retry_clock/m", memoize=False)
        if operation == "count_tokens":
            await model.count_tokens("count")
        elif operation == "compact":
            await model.compact([ChatMessageUser(content="compact")], [])
        else:
            await model.generate("generate")

    working = 1 if sibling else 0
    try:
        with working_limit(None) as scope:
            with known_work():
                other = _Task()
                async with anyio.create_task_group() as tg:
                    with known_work():
                        tg.start_soon(background)
                        await ready.wait()
                    inner_closed.set()
                assert sample_clock.get_time() == 5
                assert sample_working_time() == working
                assert sample_waiting_time() == 5 - working
                assert scope.usage == working
            assert sample_working_time() == working
            assert scope.usage == working
    finally:
        del _registry["modelapi:working_retry_clock"]


async def test_closed_span_passes_later_work_up(sample_clock: _MockTime) -> None:
    """Work finishing under a closed span reaches the open work above it.

    An outer tool runs an inner tool, which starts a task and returns; the
    task works over `[0, 5]` and reports it as waiting, then the outer tool
    reports the same interval.
    """
    outer = _Task()
    outer_work = outer.enter(known_work())
    inner = _Task(outer)
    inner_work = inner.enter(known_work())
    background = _Task(inner)
    inner.exit(inner_work)
    work = background.enter(known_work())
    sample_clock.advance(5)
    background.exit(work)
    assert sample_waiting_time() == 0
    outer.ctx.run(add_sample_wait, 0, 5)
    assert sample_waiting_time() == 5
    sample_clock.advance(1)
    outer.exit(outer_work)
    assert sample_working_time() == 1


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


@pytest.mark.parametrize("own_wait", [False, True])
async def test_bridged_host_tool_call_is_known_work(
    sample_clock: _MockTime, own_wait: bool
) -> None:
    """A bridged host tool call is known work, like a native tool call.

    The tool runs 5 s beside another task's open wait, through the bridge's
    `call_tool` service method. A wait inside the call holds it.
    """

    @tool
    def clock_tool() -> Tool:
        async def execute() -> str:
            """Run for 5 s on the sample clock."""
            with sample_wait() if own_wait else contextlib.nullcontext():
                sample_clock.advance(5)
            return "done"

        return execute

    bridge = SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        bridged_tools={"srv": {"clock_tool": clock_tool()}},
        proposal_exempt_servers={"srv"},
    )
    wait = _Task().wait()
    with working_limit(None) as scope:
        assert await call_tool(bridge)("srv", "clock_tool", {}) == "done"
    wait.close()
    reading = sample_working_time(), sample_waiting_time(), scope.usage
    assert reading == ((0, 5, 0) if own_wait else (5, 0, 5))


@pytest.mark.parametrize("launch", ["bridge", "exec", "exec_remote"])
async def test_bridged_agent_launch_is_not_known_work(
    sample_clock: _MockTime, monkeypatch: pytest.MonkeyPatch, launch: str
) -> None:
    """A bridged agent's launcher exec does not hide the agent's model waits.

    The agent runs in one blocking exec. Its model request (in the bridge's
    service task, started first) fails after 1 s, backs off for 5 s and then
    succeeds in 1 s, beside another task's wait open throughout. Inside
    `sandbox_agent_bridge()` the launcher is not known work, so the failed
    attempt and backoff are waiting and the successful request is working.
    The controls: the same exec outside a bridge is known work, and an
    `exec_remote` launch outside a bridge is known work only for its start.
    """

    class RemoteSandbox(_GatedSandbox):
        """Answers `exec_remote`'s requests; its poll waits for `release`."""

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
            if input is None:
                return await super().exec(cmd)
            result: dict[str, object] = {"pid": 42}
            if json.loads(input)["method"] == "exec_remote_poll":
                await self.release.wait()
                result = {"state": "completed", "exit_code": 0, "seq": 0}
                result.update(stdout="", stderr="")
            response = {"jsonrpc": "2.0", "result": result, "id": 1}
            return ExecResult(
                success=True, returncode=0, stdout=json.dumps(response), stderr=""
            )

    sandbox = RemoteSandbox(sample_clock)
    proxy = SandboxEnvironmentProxy(sandbox)
    proxy._tools_injected = True
    launched, served = anyio.Event(), anyio.Event()
    readings: list[tuple[float, float, float]] = []
    attempts = 0

    class ClockAPI(ModelAPI):
        async def generate(
            self,
            input: list[ChatMessage],
            tools: list[ToolInfo],
            tool_choice: ToolChoice,
            config: GenerateConfig,
        ) -> ModelOutput:
            nonlocal attempts
            attempts += 1
            sample_clock.advance(1)
            if attempts == 1:
                raise RuntimeError("retryable")
            return ModelOutput()

        def should_retry(self, ex: Exception) -> bool:
            return isinstance(ex, RuntimeError)

    def reading() -> tuple[float, float, float]:
        return sample_working_time(), sample_waiting_time(), scope.usage

    async def backoff(seconds: float) -> None:
        sample_clock.advance(5)
        readings.append(reading())

    async def service(started: anyio.Event) -> None:
        started.set()
        await launched.wait()
        await get_model("working_bridge_clock/m", memoize=False).generate("agent")
        served.set()
        await anyio.sleep_forever()

    class Process:
        def __aiter__(self) -> Process:
            return self

        async def __anext__(self) -> Any:
            await anyio.sleep_forever()

        async def kill(self) -> None:
            pass

    class BridgeSandbox:
        _tools_user = None

        async def exec_remote(self, cmd: list[str], options: Any) -> Process:
            return Process()

    async def injected_sandbox(sandbox_name: str | None = None) -> BridgeSandbox:
        return BridgeSandbox()

    async def model_service(*args: Any) -> None:
        await service(args[-1])

    async def agent() -> None:
        async def run() -> None:
            await served.wait()
            readings.append(reading())
            sandbox.release.set()

        async with anyio.create_task_group() as tg:
            tg.start_soon(run)
            launched.set()
            if launch == "exec_remote":
                await proxy.exec_remote(["agent"], stream=False)
            else:
                await proxy.exec(["poll"])

    monkeypatch.setattr("inspect_ai.model._retry._sleep", backoff)
    bridge_module = "inspect_ai.agent._bridge.sandbox.bridge"
    monkeypatch.setattr(
        f"{bridge_module}.sandbox_with_injected_tools", injected_sandbox
    )
    monkeypatch.setattr(f"{bridge_module}.run_model_service", model_service)

    @modelapi(name="working_bridge_clock")
    def working_bridge_clock() -> type[ModelAPI]:
        return ClockAPI

    try:
        with working_limit(None) as scope:
            wait = _Task().wait()
            if launch == "bridge":
                async with sandbox_agent_bridge():
                    await agent()
            else:
                async with anyio.create_task_group() as tg:
                    started = anyio.Event()
                    tg.start_soon(service, started)
                    await started.wait()
                    await agent()
                    tg.cancel_scope.cancel()
            wait.close()
            readings.append(reading())
    finally:
        del _registry["modelapi:working_bridge_clock"]

    # during the backoff, once served (launcher still open), and after
    if launch == "exec":
        assert readings == [(6, 0, 6), (7, 0, 7), (7, 0, 7)]
    else:
        assert readings == [(0, 6, 0), (1, 6, 1), (1, 6, 1)]


class _GatedSandbox(SandboxEnvironment):
    """`poll` waits for `release`; any other command runs `work`.

    `work` defaults to taking 5 s on the sample clock.
    """

    def __init__(
        self, clock: _MockTime, work: Callable[[], object] | None = None
    ) -> None:
        super().__init__()
        self.clock = clock
        self.work = work or (lambda: clock.advance(5))
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
            self.work()
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
    work (withdrawing finished work too, or not) and attempts classified
    after the fact.
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
            model.open_wait(context, suspended=rng.random() < 0.3)
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
            completed = rng.random() < 0.7
            model.late_wait(
                context,
                start,
                end,
                functools.partial(add_sample_wait, completed=completed),
                suspended=rng.random() < 0.3,
                completed=completed,
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
    handed_off: bool = False  # its work is final and passed up
    holder: _Span | None = None  # the span its counted work is with, if any


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
        span.holder = span
        if parent is not None:
            self._hold(parent)
        self.spans.append(span)

    def close_span(self, span: _Span) -> None:
        span.task.exit(span.cm)
        self._end(span)
        span.closed = True
        if span.holds == 0 and span.parent is not None:
            self._release(span.parent)
        if span.attempts is None:
            self._hand_off(span)

    def open_wait(self, span: _Span | None, suspended: bool = False) -> None:
        """Open a wait in a task started in `span` (inside a suspension, if set).

        A suspension opened and closed at this instant adds no wait itself;
        the task it started inherits its suppression of new work.
        """
        task = _Task(span.inner if span else None)
        if suspended:
            suspension = task.enter(sample_wait())
            child = _Task(task)
            task.exit(suspension)
            task = child
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
                span.parent,
                span.opened,
                self.clock.get_time(),
                functools.partial(add_sample_wait, completed=False),
                completed=False,
            )
            span.attempts.retried()
        else:
            span.attempts.commit()
        self._hand_off(span)

    def late_wait(
        self,
        context: _Span | None,
        start: float,
        end: float,
        report: Callable[[float, float], None],
        suspended: bool = False,
        completed: bool = True,
    ) -> None:
        """Report a wait after the fact from inside `context`'s work.

        With `suspended`, the report is made inside a `sample_wait()` opened
        at that instant, as an approver or monitor would. With `completed`,
        it withdraws the work handed to the spans it walks, as well as their
        own.
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
        chain: list[_Span] = []
        while context is not None:
            chain.append(context)
            context = context.parent
        active = [span for span in chain if span.active is not None]
        for span in chain:
            self._end(span)
        for span in self.spans:
            # the chain's spans' own work wherever it was handed, and with
            # `completed` any work handed to the chain
            if span.holder is None or span.holder not in chain:
                continue
            if not completed and span not in chain:
                continue
            span.segments = [
                piece
                for s, e in span.segments
                for piece in ([(s, e)] if e <= start or s >= end else [])
                + ([(s, start)] if s < start < e else [])
                + ([(end, e)] if s < end < e else [])
            ]
        for span in active:
            span.active = now

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

    def _hand_off(self, span: _Span) -> None:
        """Pass the work `span` holds to its first parent still taking it.

        The work is dropped when no such parent exists.
        """
        span.handed_off = True
        target: _Span | None = span
        while target is not None and target.handed_off:
            target = target.parent
        for other in self.spans:
            if other.holder is span:
                other.holder = target

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
