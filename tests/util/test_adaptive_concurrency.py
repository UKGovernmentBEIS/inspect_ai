"""Tests for AdaptiveConcurrencyController and _ceil_to_nice/_floor_to_nice."""

import time

import anyio
import pytest

from inspect_ai.util._concurrency import (
    AdaptiveConcurrency,
    AdaptiveConcurrencyController,
    DynamicSampleLimiter,
    _active_controller,
    _ceil_to_nice,
    _controller_created_observers,
    _floor_to_nice,
    _request_had_retry,
    adaptive_controllers,
    add_controller_created_observer,
    concurrency,
    init_concurrency,
)


def test_ceil_to_nice() -> None:
    # below 10: just the value
    assert _ceil_to_nice(1) == 1
    assert _ceil_to_nice(9) == 9
    # at 10: stays
    assert _ceil_to_nice(10) == 10
    # above 10: ceil to nearest 5
    assert _ceil_to_nice(11) == 15
    assert _ceil_to_nice(15) == 15
    assert _ceil_to_nice(16) == 20
    assert _ceil_to_nice(64) == 65
    assert _ceil_to_nice(100) == 100
    assert _ceil_to_nice(101) == 105


def test_floor_to_nice() -> None:
    assert _floor_to_nice(1) == 1
    assert _floor_to_nice(9) == 9
    assert _floor_to_nice(10) == 10
    assert _floor_to_nice(14) == 10
    assert _floor_to_nice(15) == 15
    assert _floor_to_nice(64) == 60
    assert _floor_to_nice(100) == 100


def test_initial_state() -> None:
    c = AdaptiveConcurrencyController(
        "test", AdaptiveConcurrency(min=2, max=80, start=10), visible=True
    )
    assert c.concurrency == 10
    assert c.value == 10  # nothing borrowed yet
    assert c.history == []


def test_slow_start_doubles_until_first_retry() -> None:
    c = AdaptiveConcurrencyController(
        "t", AdaptiveConcurrency(min=1, max=200, start=10), visible=True
    )
    # round_size starts at max(10, 4) = 10. Need 10 successes for first scale-up.
    for _ in range(10):
        c.notify_success()
    assert c.concurrency == 20
    # next round: 20 successes
    for _ in range(20):
        c.notify_success()
    assert c.concurrency == 40
    # one more: 40 successes
    for _ in range(40):
        c.notify_success()
    assert c.concurrency == 80
    # entries should all be slow_start
    assert all(entry[4] == "slow_start" for entry in c.history)


def test_aimd_after_first_retry() -> None:
    c = AdaptiveConcurrencyController(
        "t", AdaptiveConcurrency(min=1, max=200, start=40), visible=True
    )
    # trigger retry → drops to floor_to_nice(32) = 30
    c.notify_retry()
    assert c.concurrency == 30
    assert c.history[-1][4] == "rate_limit"

    # cooldown is 15s; immediate further retry is debounced (no-op)
    c.notify_retry()
    assert c.concurrency == 30  # unchanged

    # advance past cooldown so notify_success can resume counting
    c._cooldown_until = time.monotonic() - 1

    # successful round: round_size = max(30, 4) = 30. +max(1, 30*0.05) = +2 → ceil_to_nice(32) = 35
    for _ in range(30):
        c.notify_success()
    assert c.concurrency == 35
    assert c.history[-1][4] == "steady_state_up"


def test_no_success_accounting_during_cooldown() -> None:
    """Successes arriving during the retry cooldown are dropped entirely.

    Repro for the bug where a cut from N to N*0.8 could be reversed by N*0.8
    in-flight clean completions arriving inside the cooldown window. After the
    cut, those successes were almost certainly in flight from before the cut
    so they tell us nothing — and counting them would let back-pressure
    evaporate immediately.
    """
    c = AdaptiveConcurrencyController(
        "t", AdaptiveConcurrency(min=1, max=200, start=100), visible=True
    )
    # cut: 100 → floor_to_nice(80) = 80; cooldown begins
    c.notify_retry()
    assert c.concurrency == 80

    # 80 in-flight successes arrive during cooldown — none should accumulate
    for _ in range(80):
        c.notify_success()
    assert c._success_count == 0
    assert c.concurrency == 80  # NOT scaled up to 85

    # debounced retries within cooldown also keep things stable
    c.notify_retry()
    assert c.concurrency == 80  # debounced
    assert c._success_count == 0

    # advance past cooldown — fresh successes should now count
    c._cooldown_until = time.monotonic() - 1
    for _ in range(80):
        c.notify_success()
    # 80 successes = round_size; +max(1, 80*0.05) = +4 → ceil_to_nice(84) = 85
    assert c.concurrency == 85


def test_retry_debounce_via_cooldown() -> None:
    c = AdaptiveConcurrencyController(
        "t", AdaptiveConcurrency(min=1, max=200, start=80), visible=True
    )
    c.notify_retry()
    first = c.concurrency
    # immediate retries are no-ops
    for _ in range(5):
        c.notify_retry()
    assert c.concurrency == first
    # simulate cooldown elapsed
    c._cooldown_until = time.monotonic() - 1
    c.notify_retry()
    assert c.concurrency < first


def test_bounds_clamping() -> None:
    # max bound on slow-start
    c = AdaptiveConcurrencyController(
        "t", AdaptiveConcurrency(min=1, max=15, start=10), visible=True
    )
    for _ in range(10):
        c.notify_success()
    # would double to 20, capped at 15
    assert c.concurrency == 15

    # min bound on retry
    c2 = AdaptiveConcurrencyController(
        "t", AdaptiveConcurrency(min=8, max=200, start=10), visible=True
    )
    c2.notify_retry()
    # 10 * 0.8 = 8 → floor_to_nice(8) = 8 (below 10), clamped to min=8
    assert c2.concurrency == 8


def test_steady_state_up_does_not_exceed_max() -> None:
    c = AdaptiveConcurrencyController(
        "t", AdaptiveConcurrency(min=1, max=20, start=20), visible=True
    )
    c._first_retry_seen = True
    for _ in range(20):
        c.notify_success()
    assert c.concurrency == 20  # would be 25 with ceil_to_nice, capped at 20


def test_round_size_floor_at_low_limits() -> None:
    c = AdaptiveConcurrencyController(
        "t", AdaptiveConcurrency(min=1, max=200, start=2), visible=True
    )
    # round_size = max(2, 4) = 4 (not 2)
    c.notify_success()
    c.notify_success()
    assert c.concurrency == 2  # still at start
    c.notify_success()
    c.notify_success()
    assert c.concurrency == 4  # 2*2=4


def test_history_bounded() -> None:
    c = AdaptiveConcurrencyController(
        "t", AdaptiveConcurrency(min=1, max=1000, start=10), visible=True
    )
    for _ in range(c.HISTORY_LIMIT + 50):
        c._set_limit(c.concurrency + 1, "test")
    assert len(c.history) == c.HISTORY_LIMIT


def test_default_bounds() -> None:
    """Defaults are min=4, start=20, max=200."""
    cfg = AdaptiveConcurrency()
    assert cfg.min == 4
    assert cfg.start == 20
    assert cfg.max == 200


def test_advanced_fields_default_to_documented_values() -> None:
    cfg = AdaptiveConcurrency()
    assert cfg.cooldown_seconds == 15.0
    assert cfg.decrease_factor == 0.8
    assert cfg.scale_up_percent == 0.05


def test_advanced_fields_validate_ranges() -> None:
    with pytest.raises(ValueError, match="cooldown_seconds"):
        AdaptiveConcurrency(cooldown_seconds=-1)
    with pytest.raises(ValueError, match="decrease_factor"):
        AdaptiveConcurrency(decrease_factor=0)
    with pytest.raises(ValueError, match="decrease_factor"):
        AdaptiveConcurrency(decrease_factor=1)
    with pytest.raises(ValueError, match="scale_up_percent"):
        AdaptiveConcurrency(scale_up_percent=0)
    with pytest.raises(ValueError, match="scale_up_percent"):
        AdaptiveConcurrency(scale_up_percent=1.5)


def test_advanced_fields_override_controller_behavior() -> None:
    # custom decrease_factor of 0.5 cuts harder than default 0.8
    cfg = AdaptiveConcurrency(min=1, max=200, start=40, decrease_factor=0.5)
    c = AdaptiveConcurrencyController("t", cfg, visible=True)
    c.notify_retry()
    # 40 * 0.5 = 20, floor_to_nice(20) = 20
    assert c.concurrency == 20

    # custom scale_up_percent of 0.5 grows faster than default 5%
    cfg2 = AdaptiveConcurrency(min=1, max=200, start=20, scale_up_percent=0.5)
    c2 = AdaptiveConcurrencyController("t", cfg2, visible=True)
    c2._first_retry_seen = True  # skip slow-start
    for _ in range(20):
        c2.notify_success()
    # 20 + max(1, round(20 * 0.5)) = 30, ceil_to_nice(30) = 30
    assert c2.concurrency == 30


def test_retry_after_extends_cooldown() -> None:
    cfg = AdaptiveConcurrency(min=1, max=200, start=40, cooldown_seconds=5.0)
    c = AdaptiveConcurrencyController("t", cfg, visible=True)
    before = time.monotonic()
    c.notify_retry(retry_after=60.0)
    # cooldown should be at least 60 seconds out, even though default is 5
    assert c._cooldown_until >= before + 60.0


def test_longer_retry_after_during_cooldown_extends_horizon() -> None:
    """A second 429 with a longer Retry-After should extend cooldown, not be discarded.

    Regression: the early-return for cooldown previously dropped the new
    retry_after entirely, so a 60s server hint inside an existing 15s
    cooldown was ignored.
    """
    cfg = AdaptiveConcurrency(min=1, max=200, start=40, cooldown_seconds=15.0)
    c = AdaptiveConcurrencyController("t", cfg, visible=True)
    # First retry — establishes a 15s cooldown
    c.notify_retry()
    cooldown_after_first = c._cooldown_until
    # Limit was cut once
    assert c.concurrency < 40
    cut_concurrency = c.concurrency

    # Second retry inside the cooldown window with a longer server hint
    c.notify_retry(retry_after=60.0)
    # Limit must NOT have been cut again (debounce)
    assert c.concurrency == cut_concurrency
    # But cooldown must have been extended past the 15s floor
    assert c._cooldown_until > cooldown_after_first
    # And honor the 60s server hint
    assert c._cooldown_until >= time.monotonic() + 50  # ~60s, allow scheduling slack


def test_shorter_retry_after_during_cooldown_does_not_shrink_horizon() -> None:
    """A subsequent shorter Retry-After must not pull the cooldown horizon back in."""
    cfg = AdaptiveConcurrency(min=1, max=200, start=40, cooldown_seconds=15.0)
    c = AdaptiveConcurrencyController("t", cfg, visible=True)
    c.notify_retry(retry_after=60.0)  # establishes a 60s cooldown
    long_horizon = c._cooldown_until
    c.notify_retry(retry_after=5.0)  # shorter — must not pull horizon in
    assert c._cooldown_until == long_horizon


def test_retry_after_smaller_than_cooldown_uses_floor() -> None:
    cfg = AdaptiveConcurrency(min=1, max=200, start=40, cooldown_seconds=15.0)
    c = AdaptiveConcurrencyController("t", cfg, visible=True)
    before = time.monotonic()
    c.notify_retry(retry_after=2.0)
    # cooldown should be the configured floor (15s), not the smaller server hint
    assert c._cooldown_until >= before + 15.0
    assert c._cooldown_until < before + 60.0


def test_retry_after_none_falls_back_to_cooldown() -> None:
    cfg = AdaptiveConcurrency(min=1, max=200, start=40, cooldown_seconds=10.0)
    c = AdaptiveConcurrencyController("t", cfg, visible=True)
    before = time.monotonic()
    c.notify_retry(retry_after=None)
    assert c._cooldown_until >= before + 10.0


def test_report_http_retry_transient_does_not_scale_down() -> None:
    """report_http_retry(kind='transient') marks request as retried but doesn't notify controller."""
    from inspect_ai._util.retry import report_http_retry

    init_concurrency()

    # set up a controller as the active one (mimics what _connection_concurrency does)
    cfg = AdaptiveConcurrency(min=1, max=200, start=40)
    c = AdaptiveConcurrencyController("t", cfg, visible=True)
    token_c = _active_controller.set(c)
    token_r = _request_had_retry.set(False)
    try:
        report_http_retry()  # default kind="transient"
        # no scale-down occurred
        assert c.concurrency == 40
        assert c.history == []
        # but the request IS marked as retried (so success-after-retry won't count)
        assert _request_had_retry.get() is True
    finally:
        _active_controller.reset(token_c)
        _request_had_retry.reset(token_r)


def test_report_http_retry_rate_limit_scales_down() -> None:
    from inspect_ai._util.retry import report_http_retry

    init_concurrency()

    cfg = AdaptiveConcurrency(min=1, max=200, start=40, cooldown_seconds=15.0)
    c = AdaptiveConcurrencyController("t", cfg, visible=True)
    token_c = _active_controller.set(c)
    token_r = _request_had_retry.set(False)
    try:
        report_http_retry(kind="rate_limit", retry_after=30.0)
        # 40 * 0.8 = 32, floor_to_nice(32) = 30
        assert c.concurrency == 30
        # history records it as a rate_limit cut
        assert len(c.history) == 1
        assert c.history[0][4] == "rate_limit"
        # cooldown extended by retry_after (30s > default 15s)
        before = time.monotonic()
        assert c._cooldown_until >= before + 25.0  # ~30s minus a bit
    finally:
        _active_controller.reset(token_c)
        _request_had_retry.reset(token_r)


@pytest.mark.anyio
async def test_concurrency_creates_adaptive_controller() -> None:
    init_concurrency()
    cfg = AdaptiveConcurrency(min=2, max=50, start=10)
    async with concurrency(
        name="model-x", concurrency=10, key="kx", adaptive=cfg
    ) as sem:
        assert isinstance(sem, AdaptiveConcurrencyController)
        assert sem.concurrency == 10
        assert sem.name == "model-x"
    # registered for status display
    assert any(c.name == "model-x" for c in adaptive_controllers())


@pytest.mark.anyio
async def test_contextvars_default_in_fresh_context() -> None:
    # Run in a fresh contextvars Context to bypass test-order pollution
    import contextvars

    def check() -> tuple[object, bool]:
        return _active_controller.get(), _request_had_retry.get()

    ctx = contextvars.Context()
    controller, had_retry = ctx.run(check)
    assert controller is None
    assert had_retry is False


# ---------- Observer pattern + DynamicSampleLimiter ----------


def test_observer_called_on_scale_change() -> None:
    c = AdaptiveConcurrencyController(
        "t", AdaptiveConcurrency(min=1, max=200, start=10), visible=True
    )
    events: list[tuple[int, int]] = []
    events2: list[tuple[int, int]] = []
    c.add_observer(lambda old, new: events.append((old, new)))
    c.add_observer(lambda old, new: events2.append((old, new)))
    for _ in range(10):
        c.notify_success()
    assert events == [(10, 20)]
    assert events2 == [(10, 20)]


@pytest.mark.anyio
async def test_controller_created_observer_fires_on_registry_creation() -> None:
    init_concurrency()
    seen: list[AdaptiveConcurrencyController] = []
    add_controller_created_observer(lambda ctrl: seen.append(ctrl))
    cfg = AdaptiveConcurrency(min=2, max=50, start=10)
    async with concurrency(name="model-y", concurrency=10, key="ky", adaptive=cfg):
        pass
    assert len(seen) == 1
    assert seen[0].name == "model-y"


def test_init_concurrency_clears_controller_created_observers() -> None:
    init_concurrency()
    add_controller_created_observer(lambda _ctrl: None)
    add_controller_created_observer(lambda _ctrl: None)
    assert len(_controller_created_observers) == 2
    init_concurrency()
    assert _controller_created_observers == []


def test_dynamic_sample_limiter_initial_size() -> None:
    init_concurrency()
    lim = DynamicSampleLimiter(AdaptiveConcurrency(min=1, max=80, start=10))
    assert lim.total_tokens == 10 + DynamicSampleLimiter.BUFFER  # 15


@pytest.mark.anyio
async def test_dynamic_sample_limiter_picks_up_new_controller() -> None:
    init_concurrency()
    lim = DynamicSampleLimiter(AdaptiveConcurrency(min=1, max=80, start=10))
    # initially 15 (10 + 5)
    assert lim.total_tokens == 15
    # create a controller via the registry — limiter should be wired in immediately
    cfg = AdaptiveConcurrency(min=1, max=80, start=10)
    async with concurrency(name="m", concurrency=10, key="k", adaptive=cfg):
        pass
    # still 15 (controller starts at 10 → 10 + 5)
    assert lim.total_tokens == 15


@pytest.mark.anyio
async def test_dynamic_sample_limiter_grows_with_controller() -> None:
    init_concurrency()
    lim = DynamicSampleLimiter(AdaptiveConcurrency(min=1, max=80, start=10))
    cfg = AdaptiveConcurrency(min=1, max=80, start=10)
    async with concurrency(name="m", concurrency=10, key="k", adaptive=cfg):
        pass
    ctrls = adaptive_controllers()
    assert len(ctrls) == 1
    # scale ctrl from 10 to 20 (one full slow-start round)
    for _ in range(10):
        ctrls[0].notify_success()
    assert ctrls[0].concurrency == 20
    # limiter should track: 20 + 5 = 25
    assert lim.total_tokens == 25


@pytest.mark.anyio
async def test_dynamic_sample_limiter_shrinks_with_controller() -> None:
    init_concurrency()
    lim = DynamicSampleLimiter(AdaptiveConcurrency(min=1, max=200, start=40))
    cfg = AdaptiveConcurrency(min=1, max=200, start=40)
    async with concurrency(name="m", concurrency=40, key="k", adaptive=cfg):
        pass
    ctrls = adaptive_controllers()
    # initial: ctrl=40, limiter = 40 + 5 = 45
    assert lim.total_tokens == 45
    ctrls[0].notify_retry()
    # ctrl drops to floor_to_nice(40*0.8=32) = 30; limiter = 30 + 5 = 35
    assert ctrls[0].concurrency == 30
    assert lim.total_tokens == 35


@pytest.mark.anyio
async def test_dynamic_sample_limiter_recovers_after_shrinking_below_borrowed() -> None:
    """Shrinking below borrowed tokens should block new samples, not deadlock."""
    init_concurrency()
    lim = DynamicSampleLimiter(AdaptiveConcurrency(min=1, max=80, start=10))
    cfg = AdaptiveConcurrency(min=1, max=80, start=10)
    async with concurrency(name="m", concurrency=10, key="k", adaptive=cfg):
        pass
    ctrl = adaptive_controllers()[0]

    initial_tokens = 10 + DynamicSampleLimiter.BUFFER
    release_events = [anyio.Event() for _ in range(initial_tokens)]
    all_holders_entered = anyio.Event()
    extra_started = anyio.Event()
    extra_entered = anyio.Event()
    entered_holders = 0

    async def holder(index: int) -> None:
        nonlocal entered_holders
        async with lim:
            entered_holders += 1
            if entered_holders == initial_tokens:
                all_holders_entered.set()
            await release_events[index].wait()

    async def extra_holder() -> None:
        extra_started.set()
        async with lim:
            extra_entered.set()

    async with anyio.create_task_group() as tg:
        try:
            for i in range(initial_tokens):
                tg.start_soon(holder, i)
            with anyio.fail_after(1):
                await all_holders_entered.wait()

            ctrl.notify_retry()
            assert ctrl.concurrency == 8
            assert lim.total_tokens == 8 + DynamicSampleLimiter.BUFFER

            tg.start_soon(extra_holder)
            await extra_started.wait()
            await anyio.sleep(0)
            assert not extra_entered.is_set()

            # Releasing only down to the new capacity should not admit another
            # sample. CapacityLimiter wakes waiters only once borrowed < total.
            release_events[0].set()
            release_events[1].set()
            await anyio.sleep(0)
            assert not extra_entered.is_set()

            release_events[2].set()
            with anyio.fail_after(1):
                await extra_entered.wait()
        finally:
            for event in release_events:
                event.set()


@pytest.mark.anyio
async def test_dynamic_sample_limiter_caps_at_adaptive_max_plus_buffer() -> None:
    init_concurrency()
    lim = DynamicSampleLimiter(AdaptiveConcurrency(min=1, max=20, start=10))
    cfg = AdaptiveConcurrency(min=1, max=20, start=10)
    async with concurrency(name="m", concurrency=10, key="k", adaptive=cfg):
        pass
    ctrls = adaptive_controllers()
    # scale to ctrl.max (20) — limiter capped at 20 + 5 = 25
    for _ in range(10):
        ctrls[0].notify_success()
    assert ctrls[0].concurrency == 20
    assert lim.total_tokens == 25
    # further successes don't grow ctrl past max, limiter stays at cap
    for _ in range(20):
        ctrls[0].notify_success()
    assert lim.total_tokens == 25


@pytest.mark.anyio
async def test_dynamic_sample_limiter_catches_up_to_existing_controllers() -> None:
    """A limiter created after a controller has already scaled picks up the current limit immediately, not the controller's start value."""
    init_concurrency()
    cfg = AdaptiveConcurrency(min=1, max=200, start=10)
    # create a controller and scale it up (simulate prior activity)
    async with concurrency(name="m", concurrency=10, key="k", adaptive=cfg):
        pass
    ctrls = adaptive_controllers()
    assert len(ctrls) == 1
    for _ in range(10):
        ctrls[0].notify_success()
    assert ctrls[0].concurrency == 20  # scaled up via slow-start

    # now create a DynamicSampleLimiter — it should catch up to 20 + buffer
    lim = DynamicSampleLimiter(AdaptiveConcurrency(min=1, max=200, start=10))
    assert lim.total_tokens == 20 + DynamicSampleLimiter.BUFFER  # 25, not 15


@pytest.mark.anyio
async def test_registry_separates_adaptive_and_static_storage() -> None:
    """Static and adaptive calls for the same key get independent storage.

    Otherwise: a static call followed by adaptive would return the existing
    Semaphore (failing the caller's isinstance assert), and adaptive followed
    by static would silently use the AdaptiveConcurrencyController, defeating
    the 'explicit max_connections wins' precedence rule.
    """
    init_concurrency()

    # Static call for key K — gets a plain Semaphore
    async with concurrency(name="m", concurrency=10, key="K") as static_sem:
        assert not isinstance(static_sem, AdaptiveConcurrencyController)

    # Adaptive call for SAME key K — must get an AdaptiveConcurrencyController
    cfg = AdaptiveConcurrency(min=1, max=80, start=10)
    async with concurrency(
        name="m", concurrency=10, key="K", adaptive=cfg
    ) as adaptive_sem:
        assert isinstance(adaptive_sem, AdaptiveConcurrencyController)

    # Subsequent static call for K must still get a Semaphore (not the
    # adaptive controller cached above)
    async with concurrency(name="m", concurrency=10, key="K") as static_sem2:
        assert not isinstance(static_sem2, AdaptiveConcurrencyController)


@pytest.mark.anyio
async def test_dynamic_sample_limiter_multi_controller() -> None:
    init_concurrency()
    lim = DynamicSampleLimiter(AdaptiveConcurrency(min=1, max=200, start=10))
    cfg = AdaptiveConcurrency(min=1, max=200, start=10)
    async with concurrency(name="m1", concurrency=10, key="k1", adaptive=cfg):
        pass
    async with concurrency(name="m2", concurrency=10, key="k2", adaptive=cfg):
        pass
    ctrls = adaptive_controllers()
    assert len(ctrls) == 2
    # scale m2 only
    target = next(c for c in ctrls if c.name == "m2")
    for _ in range(10):
        target.notify_success()
    assert target.concurrency == 20
    # limiter tracks max across controllers (= 20)
    assert lim.total_tokens == 25
