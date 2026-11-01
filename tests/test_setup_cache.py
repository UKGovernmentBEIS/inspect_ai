"""Tests for `SetupCache`: one shared setup job per key.

Each test scripts the setup function, so it controls exactly when each job
starts, finishes or fails.
"""

import asyncio

import anyio
import pytest
from test_helpers.utils import skip_if_trio

from inspect_ai._eval.task.setup_cache import SetupCache, SetupFailure


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
    async with SetupCache(script) as cache:
        async with anyio.create_task_group() as tg:
            for _ in range(3):
                tg.start_soon(cache.ensure, ["a"])
            await script.began_event("a").wait()
            assert not cache.done(["a"])
            script.finish("a")
        assert cache.done(["a"])
        # a later request for a key that succeeded does not run it again
        await cache.ensure(["a"])
    assert script.started == ["a"]


async def test_setups_run_one_at_a_time_by_default() -> None:
    script = Script()
    async with SetupCache(script) as cache:
        async with anyio.create_task_group() as tg:
            tg.start_soon(cache.ensure, ["a", "b", "c"])
            for key in ["a", "b", "c"]:
                await script.began_event(key).wait()
                await _settle()
                assert script.running == {key}
                script.finish(key)
    assert script.most_running == 1
    assert script.started == ["a", "b", "c"]


async def test_max_setups_runs_several_at_once() -> None:
    script = Script()
    async with SetupCache(script, max_setups=2) as cache:
        cache.prefetch(["a", "b", "c"], lambda ex: None)
        await script.began_event("a").wait()
        await script.began_event("b").wait()
        await _settle()
        assert script.running == {"a", "b"}
        script.finish("a")
        await script.began_event("c").wait()
        script.finish("b")
        script.finish("c")
        await cache.ensure(["a", "b", "c"])
    assert script.most_running == 2


async def test_a_waiter_holds_no_permit() -> None:
    # 'b' joins the job of 'a' that is waiting for a permit; when 'a' is set
    # up, 'b' may start: joining did not take a second permit
    script = Script()
    async with SetupCache(script) as cache:
        cache.prefetch(["a"], lambda ex: None)
        await script.began_event("a").wait()
        cache.prefetch(["b"], lambda ex: None)
        for _ in range(5):
            cache.prefetch(["b"], lambda ex: None)
        await _settle()
        assert script.started == ["a"]
        script.finish("a")
        await script.began_event("b").wait()
        script.finish("b")
        await cache.ensure(["b"])
    assert script.started == ["a", "b"]


async def test_needed_job_goes_before_prefetched_ones_without_preempting() -> None:
    script = Script()
    async with SetupCache(script) as cache:
        cache.prefetch(["running"], lambda ex: None)
        await script.began_event("running").wait()
        cache.prefetch(["ahead1", "ahead2"], lambda ex: None)
        async with anyio.create_task_group() as tg:
            tg.start_soon(cache.ensure, ["needed"])
            await _settle()
            # the running prefetch is not pre-empted
            assert script.running == {"running"}
            script.finish("running")
            await script.began_event("needed").wait()
            script.finish("needed")
        await script.began_event("ahead1").wait()
        script.finish("ahead1")
        await script.began_event("ahead2").wait()
        script.finish("ahead2")
    assert script.started == ["running", "needed", "ahead1", "ahead2"]


async def test_need_raises_a_waiting_prefetch() -> None:
    script = Script()
    async with SetupCache(script) as cache:
        cache.prefetch(["running", "x", "y"], lambda ex: None)
        await script.began_event("running").wait()
        cache.need(["y"])
        script.finish("running")
        await script.began_event("y").wait()
        script.finish("y")
        await script.began_event("x").wait()
        script.finish("x")
    assert script.started == ["running", "y", "x"]


async def test_failure_goes_to_current_waiters_then_is_forgotten() -> None:
    script = Script()
    errors: list[BaseException] = []
    told: list[BaseException] = []

    async def wait() -> None:
        try:
            await cache.ensure(["a"])
        except Exception as ex:
            errors.append(ex)

    async with SetupCache(script) as cache:
        cache.prefetch(["a"], lambda f: told.append(f.error) if f else None)
        async with anyio.create_task_group() as tg:
            tg.start_soon(wait)
            tg.start_soon(wait)
            await script.began_event("a").wait()
            script.finish("a", ValueError("pull failed"))
        assert [str(ex) for ex in errors] == ["pull failed", "pull failed"]
        assert [str(ex) for ex in told] == ["pull failed"]
        assert not cache.done(["a"])
        # the next request starts a fresh job, which can succeed
        async with anyio.create_task_group() as tg:
            tg.start_soon(cache.ensure, ["a"])
            await script.began_event("a").wait()
            script.finish("a")
        assert cache.done(["a"])
    assert script.started == ["a", "a"]


async def test_ensure_raises_the_first_failure() -> None:
    script = Script()
    async with SetupCache(script) as cache:
        async with anyio.create_task_group() as tg:

            async def finish() -> None:
                await script.began_event("a").wait()
                script.finish("a", RuntimeError("no docker"))

            tg.start_soon(finish)
            with pytest.raises(RuntimeError, match="no docker"):
                await cache.ensure(["a", "b"])
        # 'b' started once 'a' freed the permit, and runs to the end
        await script.began_event("b").wait()
        script.finish("b")
    assert script.started == ["a", "b"]
    assert cache.done(["b"])


async def test_a_cancelled_waiter_does_not_cancel_the_job() -> None:
    script = Script()
    async with SetupCache(script) as cache:
        with anyio.move_on_after(0.05):
            await cache.ensure(["a"])
        assert script.started == ["a"]
        assert script.running == {"a"}
        script.finish("a")
        await cache.ensure(["a"])
        assert cache.done(["a"])
    assert script.started == ["a"]


async def test_leaving_the_cache_lets_jobs_in_progress_finish_and_drops_the_rest() -> (
    None
):
    # a setup cut short could leave what it made behind with no cleanup, so a
    # normal exit waits for it; a job not yet started is dropped
    script = Script()
    left = anyio.Event()

    async def leave() -> None:
        async with SetupCache(script) as cache:
            cache.prefetch(["a", "b"], lambda ex: None)
            await script.began_event("a").wait()
        left.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(leave)
        await _settle()
        assert not left.is_set()
        script.finish("a")
    assert left.is_set()
    assert script.started == ["a"]
    with pytest.raises(RuntimeError, match="has been left"):
        SetupCache(script).prefetch(["c"], lambda ex: None)


async def test_cancel_running_and_leaving_with_an_error_cut_setups_short() -> None:
    cancelled: list[str] = []

    async def setup(key: str) -> None:
        try:
            await anyio.sleep_forever()
        finally:
            cancelled.append(key)

    async with SetupCache(setup) as cache:
        cache.prefetch(["a"], lambda ex: None)
        await _settle()
        # the run was cancelled
        cache.cancel_running()
    assert cancelled == ["a"]

    with pytest.raises(ValueError, match="run failed"):
        async with SetupCache(setup) as cache:
            cache.prefetch(["b"], lambda ex: None)
            await _settle()
            raise ValueError("run failed")
    assert cancelled == ["a", "b"]


async def test_timeout_is_an_ordinary_failure() -> None:
    async def setup(key: str) -> None:
        await anyio.sleep_forever()

    async with SetupCache(setup, timeout=0.05) as cache:
        with pytest.raises(TimeoutError):
            await cache.ensure(["a"])
        assert not cache.done(["a"])


class _Fatal(BaseException):
    """Stands in for ``KeyboardInterrupt``/``SystemExit``.

    asyncio stops its event loop on those when a task raises them.
    """


async def test_base_exceptions_reach_waiters_and_the_run() -> None:
    async def setup(key: str) -> None:
        raise _Fatal

    told: list[SetupFailure | None] = []
    # also raised when the cache is left (the run ends with it), as the run
    # here went on
    with pytest.raises(_Fatal):
        async with SetupCache(setup) as cache:
            with pytest.raises(_Fatal):
                await cache.ensure(["a"])
            cache.prefetch(["b"], told.append)
            await _settle()
            assert len(told) == 1 and told[0] is not None
            assert isinstance(told[0].error, _Fatal)
            # not remembered: the next request runs the setup again
            with pytest.raises(_Fatal):
                await cache.ensure(["a"])


async def test_base_exception_with_no_waiter_is_raised_on_exit() -> None:
    release = anyio.Event()

    async def setup(key: str) -> None:
        await release.wait()
        raise _Fatal

    with pytest.raises(_Fatal):
        async with SetupCache(setup) as cache:
            # the only waiter stops waiting
            with anyio.move_on_after(0.05):
                await cache.ensure(["a"])
            release.set()
            await _settle()


async def test_run_cancellation_is_not_a_failure() -> None:
    told: list[SetupFailure | None] = []

    async def setup(key: str) -> None:
        await anyio.sleep_forever()

    with anyio.CancelScope() as scope:
        async with SetupCache(setup) as cache:
            cache.prefetch(["a"], told.append)
            await _settle()
            scope.cancel()
            await anyio.sleep_forever()
    assert told == []


@skip_if_trio
async def test_cancelled_error_raised_by_the_setup_is_a_failure() -> None:
    # e.g. a provider awaiting a shared background task someone else cancelled
    async def setup(key: str) -> None:
        pull = asyncio.ensure_future(asyncio.Event().wait())
        pull.cancel()
        await pull

    async with SetupCache(setup) as cache:
        with pytest.raises(RuntimeError, match="CancelledError"):
            await cache.ensure(["a"])
        assert not cache.done(["a"])
