"""Tests for trailing-edge throttle decorator."""

from collections.abc import Callable
from unittest.mock import patch

import anyio

from inspect_ai._util.background import (
    background_task_group,
    set_background_task_group,
)
from inspect_ai.util._throttle import throttle

# ---------------------------------------------------------------------------
# Fake clock
# ---------------------------------------------------------------------------


class FakeClock:
    """Controllable clock for deterministic throttle tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def _flush_background() -> None:
    """Yield enough checkpoints for a background task to complete."""
    for _ in range(5):
        await anyio.sleep(0)


def _make_recorder(
    window: float, clock: FakeClock
) -> tuple[Callable, list[tuple[float, tuple, dict]]]:
    """Return a throttled function and its call log."""
    calls: list[tuple[float, tuple, dict]] = []

    @throttle(window)
    def record(*args: object, **kwargs: object) -> int:
        calls.append((clock.time(), args, kwargs))
        return len(calls)

    return record, calls


# ---------------------------------------------------------------------------
# Sync-only tests (no async context)
# ---------------------------------------------------------------------------


class TestThrottleSyncFallback:
    """Trailing-edge throttle without an async context."""

    def test_first_call_fires_immediately(self) -> None:
        clock = FakeClock()
        with (
            patch("inspect_ai.util._throttle.time") as mock_time,
            patch("inspect_ai.util._throttle.current_async_backend", return_value=None),
        ):
            mock_time.time = clock.time
            fn, calls = _make_recorder(1.0, clock)
            result = fn("a")
            assert len(calls) == 1
            assert calls[0][1] == ("a",)
            assert result == 1

    def test_calls_within_window_are_saved_not_fired(self) -> None:
        clock = FakeClock()
        with (
            patch("inspect_ai.util._throttle.time") as mock_time,
            patch("inspect_ai.util._throttle.current_async_backend", return_value=None),
        ):
            mock_time.time = clock.time
            fn, calls = _make_recorder(1.0, clock)
            fn("first")
            clock.advance(0.3)
            fn("second")
            clock.advance(0.3)
            fn("third")
            assert len(calls) == 1

    def test_trailing_fires_on_next_call_after_window(self) -> None:
        clock = FakeClock()
        with (
            patch("inspect_ai.util._throttle.time") as mock_time,
            patch("inspect_ai.util._throttle.current_async_backend", return_value=None),
        ):
            mock_time.time = clock.time
            fn, calls = _make_recorder(1.0, clock)
            fn("first")
            clock.advance(0.3)
            fn("trailing")
            clock.advance(1.0)
            result = fn("next_window")
            assert len(calls) == 2
            assert calls[1][1] == ("trailing",)
            assert result == 2

    def test_latest_pending_wins(self) -> None:
        clock = FakeClock()
        with (
            patch("inspect_ai.util._throttle.time") as mock_time,
            patch("inspect_ai.util._throttle.current_async_backend", return_value=None),
        ):
            mock_time.time = clock.time
            fn, calls = _make_recorder(1.0, clock)
            fn("first")
            fn("a")
            fn("b")
            fn("c")
            clock.advance(1.5)
            fn("trigger")
            assert len(calls) == 2
            assert calls[1][1] == ("c",)

    def test_idle_gap_fires_immediately(self) -> None:
        clock = FakeClock()
        with (
            patch("inspect_ai.util._throttle.time") as mock_time,
            patch("inspect_ai.util._throttle.current_async_backend", return_value=None),
        ):
            mock_time.time = clock.time
            fn, calls = _make_recorder(1.0, clock)
            fn("first")
            clock.advance(2.0)
            result = fn("after_gap")
            assert len(calls) == 2
            assert calls[1][1] == ("after_gap",)
            assert result == 2

    def test_return_value_from_first_call(self) -> None:
        clock = FakeClock()
        with (
            patch("inspect_ai.util._throttle.time") as mock_time,
            patch("inspect_ai.util._throttle.current_async_backend", return_value=None),
        ):
            mock_time.time = clock.time
            fn, calls = _make_recorder(1.0, clock)
            assert fn("a") == 1

    def test_return_value_within_window_is_stale(self) -> None:
        clock = FakeClock()
        with (
            patch("inspect_ai.util._throttle.time") as mock_time,
            patch("inspect_ai.util._throttle.current_async_backend", return_value=None),
        ):
            mock_time.time = clock.time
            fn, calls = _make_recorder(1.0, clock)
            fn("a")
            clock.advance(0.1)
            result = fn("b")
            assert result == 1

    def test_kwargs_preserved(self) -> None:
        clock = FakeClock()
        with (
            patch("inspect_ai.util._throttle.time") as mock_time,
            patch("inspect_ai.util._throttle.current_async_backend", return_value=None),
        ):
            mock_time.time = clock.time
            fn, calls = _make_recorder(1.0, clock)
            fn("first")
            clock.advance(0.1)
            fn("trailing", key="val")
            clock.advance(1.5)
            fn("trigger")
            assert calls[1][2] == {"key": "val"}

    def test_multiple_windows(self) -> None:
        clock = FakeClock()
        with (
            patch("inspect_ai.util._throttle.time") as mock_time,
            patch("inspect_ai.util._throttle.current_async_backend", return_value=None),
        ):
            mock_time.time = clock.time
            fn, calls = _make_recorder(1.0, clock)
            # Window 1
            fn("w1_lead")
            clock.advance(0.3)
            fn("w1_trail")
            clock.advance(1.0)
            # Window 2 — fires w1_trail, saves w2_lead as pending
            fn("w2_lead")
            clock.advance(0.3)
            fn("w2_trail")
            clock.advance(1.0)
            # Window 3 — fires w2_trail
            fn("w3_trigger")
            assert [c[1] for c in calls] == [
                ("w1_lead",),
                ("w1_trail",),
                ("w2_trail",),
            ]


# ---------------------------------------------------------------------------
# Async tests (with background task group)
# ---------------------------------------------------------------------------


class TestThrottleAsync:
    """Trailing-edge throttle with an active async context."""

    async def _with_task_group(self, coro):
        """Run coro inside a task group set as the background task group."""
        original_tg = background_task_group()
        try:
            async with anyio.create_task_group() as tg:
                set_background_task_group(tg)
                await coro(tg)
        finally:
            set_background_task_group(original_tg)

    async def test_first_call_fires_immediately(self) -> None:
        clock = FakeClock()

        async def run(tg):
            with patch("inspect_ai.util._throttle.time") as mock_time:
                mock_time.time = clock.time
                fn, calls = _make_recorder(1.0, clock)
                fn("a")
                assert len(calls) == 1
                assert calls[0][1] == ("a",)

        await self._with_task_group(run)

    async def test_deferred_fires_trailing_event(self) -> None:
        clock = FakeClock()

        async def run(tg):
            with (
                patch("inspect_ai.util._throttle.time") as mock_time,
                patch("inspect_ai.util._throttle.anyio") as mock_anyio,
            ):
                mock_time.time = clock.time

                async def fake_sleep(secs):
                    clock.advance(secs)

                mock_anyio.sleep = fake_sleep
                fn, calls = _make_recorder(1.0, clock)
                fn("first")
                fn("trailing")
                assert len(calls) == 1
                # Yield to let the deferred task run
                await _flush_background()
                assert len(calls) == 2
                assert calls[1][1] == ("trailing",)

        await self._with_task_group(run)

    async def test_deferred_fires_latest_pending(self) -> None:
        clock = FakeClock()

        async def run(tg):
            with (
                patch("inspect_ai.util._throttle.time") as mock_time,
                patch("inspect_ai.util._throttle.anyio") as mock_anyio,
            ):
                mock_time.time = clock.time

                async def fake_sleep(secs):
                    clock.advance(secs)

                mock_anyio.sleep = fake_sleep
                fn, calls = _make_recorder(1.0, clock)
                fn("first")
                fn("a")
                fn("b")
                fn("c")
                await _flush_background()
                assert len(calls) == 2
                assert calls[1][1] == ("c",)

        await self._with_task_group(run)

    async def test_no_deferred_when_no_pending(self) -> None:
        clock = FakeClock()

        async def run(tg):
            with (
                patch("inspect_ai.util._throttle.time") as mock_time,
                patch("inspect_ai.util._throttle.anyio") as mock_anyio,
            ):
                mock_time.time = clock.time

                async def fake_sleep(secs):
                    clock.advance(secs)

                mock_anyio.sleep = fake_sleep
                fn, calls = _make_recorder(1.0, clock)
                fn("only")
                await _flush_background()
                assert len(calls) == 1

        await self._with_task_group(run)

    async def test_idle_gap_fires_immediately(self) -> None:
        clock = FakeClock()

        async def run(tg):
            with (
                patch("inspect_ai.util._throttle.time") as mock_time,
                patch("inspect_ai.util._throttle.anyio") as mock_anyio,
            ):
                mock_time.time = clock.time

                async def fake_sleep(secs):
                    clock.advance(secs)

                mock_anyio.sleep = fake_sleep
                fn, calls = _make_recorder(1.0, clock)
                fn("first")
                clock.advance(2.0)
                fn("after_gap")
                assert len(calls) == 2
                assert calls[1][1] == ("after_gap",)

        await self._with_task_group(run)

    async def test_multiple_windows_async(self) -> None:
        clock = FakeClock()

        async def run(tg):
            with (
                patch("inspect_ai.util._throttle.time") as mock_time,
                patch("inspect_ai.util._throttle.anyio") as mock_anyio,
            ):
                mock_time.time = clock.time

                async def fake_sleep(secs):
                    clock.advance(secs)

                mock_anyio.sleep = fake_sleep
                fn, calls = _make_recorder(1.0, clock)
                # Window 1
                fn("w1_lead")
                clock.advance(0.3)
                fn("w1_trail")
                await _flush_background()  # deferred fires w1_trail
                assert calls[1][1] == ("w1_trail",)
                # Window 2 — w2_lead is pending, w2_trail overwrites it
                fn("w2_lead")
                clock.advance(0.3)
                fn("w2_trail")
                await _flush_background()  # deferred fires w2_trail
                assert len(calls) == 3
                assert calls[2][1] == ("w2_trail",)

        await self._with_task_group(run)

    async def test_deferred_updates_last_result(self) -> None:
        clock = FakeClock()

        async def run(tg):
            with (
                patch("inspect_ai.util._throttle.time") as mock_time,
                patch("inspect_ai.util._throttle.anyio") as mock_anyio,
            ):
                mock_time.time = clock.time

                async def fake_sleep(secs):
                    clock.advance(secs)

                mock_anyio.sleep = fake_sleep
                fn, calls = _make_recorder(1.0, clock)
                assert fn("first") == 1
                fn("trailing")
                await _flush_background()  # deferred fires
                clock.advance(1.5)
                assert fn("after") == 3  # first=1, trailing(deferred)=2, after=3

        await self._with_task_group(run)

    async def test_rapid_calls_only_one_deferred_scheduled(self) -> None:
        """Multiple calls within window should only schedule one deferred task."""
        clock = FakeClock()

        async def run(tg):
            with (
                patch("inspect_ai.util._throttle.time") as mock_time,
                patch("inspect_ai.util._throttle.anyio") as mock_anyio,
            ):
                mock_time.time = clock.time

                async def fake_sleep(secs):
                    clock.advance(secs)

                mock_anyio.sleep = fake_sleep
                fn, calls = _make_recorder(1.0, clock)
                fn("first")
                for i in range(20):
                    fn(f"rapid_{i}")
                await _flush_background()
                assert len(calls) == 2
                assert calls[1][1] == ("rapid_19",)

        await self._with_task_group(run)

    async def test_deferred_skips_if_sync_call_already_fired(self) -> None:
        """Deferred must not double-fire if a sync call consumed the window."""
        clock = FakeClock()

        async def run(tg):
            with (
                patch("inspect_ai.util._throttle.time") as mock_time,
                patch("inspect_ai.util._throttle.anyio") as mock_anyio,
            ):
                mock_time.time = clock.time
                fn, calls = _make_recorder(1.0, clock)

                async def fake_sleep(secs):
                    clock.advance(secs)
                    # Simulate a sync call arriving while deferred sleeps.
                    # This consumes the window and resets last_called, so
                    # the deferred re-check should see the window is no
                    # longer expired and skip.
                    fn("sync_during_sleep")

                mock_anyio.sleep = fake_sleep
                fn("first")
                fn("trailing")
                await _flush_background()
                # first fires immediately. fake_sleep advances clock past
                # window, then fn("sync_during_sleep") fires "trailing"
                # (pending) via the sync window-expired path. Deferred
                # re-checks and should NOT fire "sync_during_sleep" again.
                assert len(calls) == 2
                assert calls[0][1] == ("first",)
                assert calls[1][1] == ("trailing",)

        await self._with_task_group(run)

    async def test_kwargs_in_deferred(self) -> None:
        clock = FakeClock()

        async def run(tg):
            with (
                patch("inspect_ai.util._throttle.time") as mock_time,
                patch("inspect_ai.util._throttle.anyio") as mock_anyio,
            ):
                mock_time.time = clock.time

                async def fake_sleep(secs):
                    clock.advance(secs)

                mock_anyio.sleep = fake_sleep
                fn, calls = _make_recorder(1.0, clock)
                fn("first")
                fn("trailing", key="deferred_val")
                await _flush_background()
                assert calls[1][2] == {"key": "deferred_val"}

        await self._with_task_group(run)
