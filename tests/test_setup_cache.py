"""Tests for `SetupCache`: one shared setup job per key.

Each test scripts the setup function, so it controls exactly when each job
starts, finishes or fails.
"""

import asyncio
from typing import Any

import anyio
import pytest
from test_helpers.utils import skip_if_trio

from inspect_ai._eval.task.setup_cache import SetupCache, SetupFailure


def _done(cache: SetupCache[Any], keys: list[str]) -> bool:
    """Whether every key has been set up."""
    return all(key in cache._jobs and cache._jobs[key].succeeded for key in keys)


class Script:
    """A setup function whose jobs finish when the test says so."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.running: set[str] = set()
        self.most_running = 0
        self.release: dict[str, anyio.Event] = {}
        self.fail: dict[str, Exception] = {}
        self.began: dict[str, anyio.Event] = {}

    def began_event(self, key: str) -> anyio.Event:
        return self.began.setdefault(key, anyio.Event())

    def finish(self, key: str, error: Exception | None = None) -> None:
        if error is not None:
            self.fail[key] = error
        self.release.setdefault(key, anyio.Event()).set()

    async def __call__(self, key: str) -> None:
        self.started.append(key)
        self.running.add(key)
        self.most_running = max(self.most_running, len(self.running))
        self.began_event(key).set()
        try:
            await self.release.setdefault(key, anyio.Event()).wait()
            # the next run of this key waits for a fresh release
            del self.release[key]
            self.began.pop(key, None)
            if key in self.fail:
                raise self.fail.pop(key)
        finally:
            self.running.discard(key)


async def _settle() -> None:
    for _ in range(20):
        await anyio.sleep(0)


async def test_waiters_join_one_job_per_key() -> None:
    script = Script()
    async with SetupCache(script, on_done=lambda: None) as cache:
        async with anyio.create_task_group() as tg:
            for _ in range(3):
                tg.start_soon(cache.ensure, ["a"])
            await script.began_event("a").wait()
            assert not _done(cache, ["a"])
            script.finish("a")
        assert _done(cache, ["a"])
        # a later request for a key that succeeded does not run it again
        await cache.ensure(["a"])
    assert script.started == ["a"]


async def test_setups_run_one_at_a_time_in_request_order() -> None:
    script = Script()
    async with SetupCache(script, on_done=lambda: None) as cache:
        async with anyio.create_task_group() as tg:
            tg.start_soon(cache.ensure, ["a", "b", "c"])
            for key in ["a", "b", "c"]:
                await script.began_event(key).wait()
                await _settle()
                assert script.running == {key}
                script.finish(key)
    assert script.most_running == 1
    assert script.started == ["a", "b", "c"]


async def test_a_job_waited_for_now_goes_ahead_of_requested_ones() -> None:
    script = Script()
    async with SetupCache(script, on_done=lambda: None) as cache:
        cache.request(["a", "b", "c"])
        await _settle()
        assert script.started == ["a"]
        async with anyio.create_task_group() as tg:
            tg.start_soon(cache.ensure, ["new", "c"])
            await _settle()
            for key in ["a", "new", "c", "b"]:
                assert script.started[-1] == key
                script.finish(key)
                await _settle()
    assert script.started == ["a", "new", "c", "b"]


async def test_failure_goes_to_waiters_and_is_kept() -> None:
    script = Script()
    errors: list[BaseException] = []
    told: list[SetupFailure | None] = []

    async def wait() -> None:
        try:
            await cache.ensure(["a"])
        except Exception as ex:
            errors.append(ex)

    # the listener is told as each job ends
    async with SetupCache(script, on_done=lambda: told.append(job.failure)) as cache:
        [job] = cache.request(["a"])
        async with anyio.create_task_group() as tg:
            tg.start_soon(wait)
            tg.start_soon(wait)
            await script.began_event("a").wait()
            script.finish("a", ValueError("pull failed"))
        assert [str(ex) for ex in errors] == ["pull failed", "pull failed"]
        assert [str(f.error) for f in told if f] == ["pull failed"]
        # later requests join the failed job: no setup runs again
        assert cache.request(["a"]) == [job]
        await wait()
        assert [str(ex) for ex in errors] == ["pull failed"] * 3
    assert script.started == ["a"]


async def test_a_retry_sets_a_failed_key_up_again_once_per_attempt() -> None:
    # tasks share key a, whose setups fail: the first retry for attempt 2
    # adds a job and the others join it; a task whose earlier attempt joined
    # the failed attempt-2 job joins it again for its own attempt 2, and gets
    # a new job only for attempt 3
    script = Script()
    async with SetupCache(script, on_done=lambda: None) as cache:
        [first] = cache.request(["a"])
        await script.began_event("a").wait()
        script.finish("a", ValueError("broken"))
        await first.done.wait()
        [second] = cache.request_for_retry(["a"], attempt=2)
        assert second is not first
        assert cache.request_for_retry(["a"], attempt=2) == [second]
        await script.began_event("a").wait()
        script.finish("a", ValueError("broken"))
        await second.done.wait()
        # a later task: its first attempt joins the failed job, as does its
        # retry for attempt 2
        assert cache.request(["a"]) == [second]
        assert cache.request_for_retry(["a"], attempt=2) == [second]
        [third] = cache.request_for_retry(["a"], attempt=3)
        assert third.attempt == 3
        await script.began_event("a").wait()
        script.finish("a")
        await third.done.wait()
        assert third.succeeded
        # a succeeded job is joined by every retry
        assert cache.request_for_retry(["a"], attempt=4) == [third]
    assert script.started == ["a", "a", "a"]


async def test_ensure_raises_the_first_failure() -> None:
    script = Script()
    async with SetupCache(script, on_done=lambda: None) as cache:
        async with anyio.create_task_group() as tg:

            async def finish() -> None:
                await script.began_event("a").wait()
                script.finish("a", RuntimeError("no docker"))

            tg.start_soon(finish)
            with pytest.raises(RuntimeError, match="no docker"):
                await cache.ensure(["a", "b"])
        # 'b' starts once 'a' has ended
        await script.began_event("b").wait()
        script.finish("b")
    assert script.started == ["a", "b"]
    assert _done(cache, ["b"])


async def test_a_cancelled_waiter_does_not_cancel_the_job() -> None:
    script = Script()
    async with SetupCache(script, on_done=lambda: None) as cache:
        with anyio.move_on_after(0.05):
            await cache.ensure(["a"])
        assert script.started == ["a"]
        assert script.running == {"a"}
        script.finish("a")
        await cache.ensure(["a"])
        assert _done(cache, ["a"])
    assert script.started == ["a"]


class _Fatal(BaseException):
    """Stands in for ``KeyboardInterrupt``/``SystemExit``.

    asyncio stops its event loop on those when a task raises them.
    """


async def test_run_cancellation_is_not_a_failure() -> None:
    told: list[None] = []

    async def setup(key: str) -> None:
        await anyio.sleep_forever()

    with anyio.CancelScope() as scope:
        async with SetupCache(setup, on_done=lambda: told.append(None)) as cache:
            cache.request(["a"])
            await _settle()
            scope.cancel()
            await anyio.sleep_forever()
    assert told == []


async def test_leaving_after_the_host_absorbed_a_run_cancellation() -> None:
    # the run's cancellation also cancelled the running setup; the host
    # absorbed it (as the run does for Ctrl-C), so leaving the cache does not
    # raise it again
    async def setup(key: str) -> None:
        await anyio.sleep_forever()

    left = False
    with anyio.CancelScope() as scope:
        async with SetupCache(setup, on_done=lambda: None) as cache:
            cache.request(["a"])
            await _settle()
            scope.cancel()
            try:
                await anyio.sleep_forever()
            except anyio.get_cancelled_exc_class():
                pass
        left = True
    assert left


@skip_if_trio
async def test_cancelled_error_raised_by_the_setup_is_a_failure() -> None:
    # e.g. a provider awaiting a shared background task someone else cancelled
    async def setup(key: str) -> None:
        pull = asyncio.ensure_future(asyncio.Event().wait())
        pull.cancel()
        await pull

    async with SetupCache(setup, on_done=lambda: None) as cache:
        with pytest.raises(RuntimeError, match="CancelledError"):
            await cache.ensure(["a"])
        assert not _done(cache, ["a"])


async def test_leaving_the_cache_cancels_the_running_job_and_drops_the_rest() -> None:
    cancelled: list[str] = []

    async def setup(key: str) -> None:
        try:
            await anyio.sleep_forever()
        finally:
            cancelled.append(key)

    async with SetupCache(setup, on_done=lambda: None) as cache:
        cache.request(["a", "b"])
        await _settle()
    assert cancelled == ["a"]

    with pytest.raises(ValueError, match="run failed"):
        async with SetupCache(setup, on_done=lambda: None) as cache:
            cache.request(["c"])
            await _settle()
            raise ValueError("run failed")
    assert cancelled == ["a", "c"]
    with pytest.raises(RuntimeError, match="has been left"):
        cache.request(["d"])


async def test_base_exceptions_reach_waiters_and_are_kept_for_the_run() -> None:
    async def setup(key: str) -> None:
        raise _Fatal

    async with SetupCache(setup, on_done=lambda: None) as cache:
        with pytest.raises(_Fatal):
            await cache.ensure(["a"])
        assert isinstance(cache.fatal, _Fatal)
        # kept, like any failure: the next request raises it at once
        with pytest.raises(_Fatal):
            await cache.ensure(["a"])


async def test_dropping_waiting_jobs_keeps_started_and_ensured_ones() -> None:
    # nobody needs a, b or c any more, but a has started (it runs on) and an
    # ensure() call waits for c: only b is dropped
    script = Script()
    async with SetupCache(script, on_done=lambda: None) as cache:
        cache.request(["a", "b", "c"])
        await script.began_event("a").wait()
        async with anyio.create_task_group() as tg:
            tg.start_soon(cache.ensure, ["c"])
            await _settle()
            cache.drop_waiting([])
            assert sorted(cache._jobs) == ["a", "c"]
            script.finish("a")
            await script.began_event("c").wait()
            script.finish("c")
        assert script.started == ["a", "c"]
        assert _done(cache, ["a", "c"])
        # a dropped key is set up again when requested again
        [job] = cache.request(["b"])
        await script.began_event("b").wait()
        script.finish("b")
        await job.done.wait()
        assert script.started == ["a", "c", "b"]
