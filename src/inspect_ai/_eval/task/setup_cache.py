"""One shared setup job per sandbox config, for one eval run.

Many tasks of a run can use the same sandbox config, whose setup (a provider's
``task_init``: an image build or pull, a cloud environment) is slow and must
run once. :class:`SetupCache` keeps one job per key ("single flight"):

- A request joins the key's job if there is one, in progress or succeeded.
  Only a new job takes a permit from the cache's limiter, inside its own
  coroutine; whoever waits for a job holds no permit.
- When a permit frees, a waiting job that is needed now (:meth:`ensure`, or
  :meth:`need`) goes before one that was only prefetched. A running job is
  never pre-empted.
- A failure is given to the job's current waiters, then forgotten: the job is
  removed, so the next request for the key starts a fresh one.
- Nothing a waiter does cancels a job: a waiter that is cancelled just stops
  waiting. Leaving the cache cancels the jobs still in progress.
- An optional timeout turns a hung setup into an ordinary failure.

The cache is loop-confined, like the rest of the scheduler (see
``inspect_ai._eval.run``): it is used only on the run's event loop thread,
and its bookkeeping does not await.

A ``KeyboardInterrupt`` or ``SystemExit`` raised by a setup is not a failure
of it: it is re-raised in the job's waiters (so it reaches the run where they
wait), or, if it had none, when the cache is left. The run's cancellation is
not given to waiters. A ``CancelledError`` raised by a setup while the run is
not cancelled is a failure (a ``RuntimeError``).
"""

import math
from contextlib import AsyncExitStack, nullcontext
from contextvars import copy_context
from types import TracebackType
from typing import Any, Awaitable, Callable, Generic, Hashable, Iterable, TypeVar

import anyio
from anyio.abc import TaskGroup

from inspect_ai._util._async import unwrap_exception_group

K = TypeVar("K", bound=Hashable)

SetupDone = Callable[[BaseException | None], None]
"""Told when a prefetched job ends: ``None`` if it succeeded, else what it raised."""


class _Job(Generic[K]):
    def __init__(self, key: K, needed: bool) -> None:
        self.key = key
        self.needed = needed
        self.done = anyio.Event()
        self.succeeded = False
        self.error: BaseException | None = None
        self.on_done: list[SetupDone] = []
        self.waiters = 0
        """Coroutines waiting in :meth:`SetupCache.ensure`."""
        self.granted = anyio.Event()


class _Permits:
    """A counting limiter that grants needed jobs before prefetched ones.

    A job asks for its permit when it is created, so jobs are granted in the
    order they were created (within a priority), however their tasks are
    scheduled.
    """

    def __init__(self, total: int) -> None:
        self._free = total
        self._waiting: list[_Job[Any]] = []

    def request(self, job: _Job[Any]) -> None:
        if self._free > 0:
            self._free -= 1
            job.granted.set()
        else:
            self._waiting.append(job)

    def done(self, job: _Job[Any]) -> None:
        """Give back the job's permit, or its place in the queue for one."""
        if job in self._waiting:
            self._waiting.remove(job)
        elif self._waiting:
            waiting = next((j for j in self._waiting if j.needed), self._waiting[0])
            self._waiting.remove(waiting)
            waiting.granted.set()
        else:
            self._free += 1


class SetupCache(Generic[K]):
    """One shared setup job per key (see the module docstring).

    Use as an async context manager around everything that requests setups;
    the jobs run in its task group.
    """

    def __init__(
        self,
        setup: Callable[[K], Awaitable[None]],
        *,
        max_setups: int = 1,
        timeout: float | None = None,
    ) -> None:
        """Create a cache.

        Args:
            setup: Sets up one key. Runs at most once at a time per key, and
                again only after a failure.
            max_setups: How many setups run at once.
            timeout: Seconds after which a setup fails with ``TimeoutError``.
        """
        self._setup = setup
        self._permits = _Permits(max_setups)
        self._timeout = timeout
        self._jobs: dict[K, _Job[K]] = {}
        self._exit_stack = AsyncExitStack()
        self._tg: TaskGroup | None = None
        self._fatal: BaseException | None = None
        self._context = copy_context()

    async def __aenter__(self) -> "SetupCache[K]":
        self._tg = await self._exit_stack.enter_async_context(anyio.create_task_group())
        # jobs start from here, not from whichever task first requested them
        self._context = copy_context()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        assert self._tg is not None
        # the run is closing: setups still in progress are no longer wanted
        # (when it is failing, the task group cancels them itself)
        if exc_type is None:
            self._tg.cancel_scope.cancel()
        self._tg = None
        # jobs raise no Exception, so a group holds only the host's own error:
        # raise it as it was raised
        with unwrap_exception_group("single"):
            suppress = await self._exit_stack.__aexit__(exc_type, exc, tb)
        if self._fatal is not None:
            raise self._fatal
        return suppress

    def done(self, keys: Iterable[K]) -> bool:
        """Whether every key has been set up."""
        return all(
            (job := self._jobs.get(key)) is not None and job.succeeded for key in keys
        )

    def prefetch(self, keys: Iterable[K], on_done: SetupDone) -> None:
        """Start setting up keys, without waiting.

        ``on_done`` is called, in the job's task, when each job it joined that
        had not succeeded yet ends (with its error, if it failed). It is not
        called for jobs cancelled when the cache is left.
        """
        for key in keys:
            job = self._join(key, needed=False)
            if not job.succeeded:
                job.on_done.append(on_done)

    def need(self, keys: Iterable[K]) -> None:
        """Mark the jobs of keys as needed now (see the module docstring)."""
        for key in keys:
            job = self._jobs.get(key)
            if job is not None:
                job.needed = True

    async def ensure(self, keys: Iterable[K]) -> None:
        """Set up keys (needed now) and wait until they are.

        Raises:
            BaseException: What the first job that failed raised.
        """
        jobs = [self._join(key, needed=True) for key in keys]
        for job in jobs:
            job.waiters += 1
        try:
            for job in jobs:
                await job.done.wait()
                if job.error is not None:
                    raise job.error
                if not job.succeeded:
                    raise RuntimeError("The sandbox setup was cancelled.")
        finally:
            for job in jobs:
                job.waiters -= 1

    def _join(self, key: K, needed: bool) -> _Job[K]:
        job = self._jobs.get(key)
        if job is None:
            if self._tg is None:
                raise RuntimeError("The run's sandbox setups have ended.")
            job = self._jobs[key] = _Job(key, needed)
            self._permits.request(job)
            self._context.copy().run(self._tg.start_soon, self._run, job)
        elif needed:
            job.needed = True
        return job

    async def _run(self, job: _Job[K]) -> None:
        try:
            try:
                await job.granted.wait()
                with (
                    anyio.fail_after(self._timeout)
                    if self._timeout is not None
                    else nullcontext()
                ):
                    await self._setup(job.key)
            finally:
                self._permits.done(job)
            job.succeeded = True
            for on_done in job.on_done:
                on_done(None)
        except anyio.get_cancelled_exc_class() as ex:
            if anyio.current_effective_deadline() == -math.inf:
                raise
            # raised by the setup itself (asyncio), not a cancellation of the run
            self._fail(job, RuntimeError(f"The sandbox setup raised {ex!r}."))
        except Exception as ex:
            self._fail(job, ex)
        except BaseException as ex:
            # KeyboardInterrupt, SystemExit: given to the waiters rather than
            # raised in this task (asyncio stops its event loop on these when
            # a task raises them)
            if not job.on_done and job.waiters == 0:
                self._fatal = ex
            self._fail(job, ex)
        finally:
            if not job.succeeded and self._jobs.get(job.key) is job:
                del self._jobs[job.key]
            job.on_done = []
            job.done.set()

    def _fail(self, job: _Job[K], error: BaseException) -> None:
        job.error = error
        if self._jobs.get(job.key) is job:
            del self._jobs[job.key]
        for on_done in job.on_done:
            on_done(error)
