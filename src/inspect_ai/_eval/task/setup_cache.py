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
- A failure is forgotten and given to the job's current waiters: the job is
  removed, so the next request for the key starts a fresh one.
- Nothing a waiter does cancels a job: a waiter that is cancelled just stops
  waiting. When the cache is left normally, jobs still waiting for a permit
  are dropped and jobs in progress run to the end (cutting a setup short can
  leave what it made behind, with no cleanup). Only the run's cancellation
  (:meth:`cancel_running`, or leaving the cache with an error) cuts a setup
  short.
- An optional timeout turns a hung setup into an ordinary failure.

The cache is used only from the run's event loop, and its bookkeeping does
not await, so it needs no lock.

A ``KeyboardInterrupt`` or ``SystemExit`` raised by a setup is not a failure
of it: it is re-raised in the job's waiters (so it reaches the run where they
wait), and again when the cache is left, unless the run is already raising
it. The run's cancellation is not given to waiters. A ``CancelledError``
raised by a setup while the run is not cancelled is a failure (a
``RuntimeError``).
"""

from contextlib import AsyncExitStack, nullcontext
from contextvars import copy_context
from types import TracebackType
from typing import (
    Any,
    Awaitable,
    Callable,
    Generic,
    Hashable,
    Iterable,
    NamedTuple,
    NoReturn,
    TypeVar,
)

import anyio
from anyio.abc import TaskGroup

from inspect_ai._util._async import run_cancelled, unwrap_exception_group

K = TypeVar("K", bound=Hashable)


class SetupFailure(NamedTuple):
    """What a failed setup raised, with the traceback it was raised with."""

    error: BaseException
    traceback: TracebackType | None

    @staticmethod
    def of(error: BaseException) -> "SetupFailure":
        return SetupFailure(error, error.__traceback__)

    def raise_again(self) -> NoReturn:
        """Raise the error from its own traceback.

        One failure can reach several waiters, each raising the same
        exception object; starting from the setup's traceback keeps one
        waiter's frames out of another's report.
        """
        raise self.error.with_traceback(self.traceback)


SetupDone = Callable[[SetupFailure | None], None]
"""Told when a prefetched job ends: ``None`` if it succeeded."""


class _Job(Generic[K]):
    def __init__(self, key: K, needed: bool) -> None:
        self.key = key
        self.needed = needed
        self.done = anyio.Event()
        self.succeeded = False
        self.failure: SetupFailure | None = None
        self.on_done: list[SetupDone] = []
        self.granted = anyio.Event()
        self.scope = anyio.CancelScope()


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

    def drop_waiting(self) -> None:
        """Let the jobs waiting for a permit go without one (see ``closed``)."""
        waiting, self._waiting = self._waiting, []
        for job in waiting:
            job.granted.set()

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
        self._closed = False
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
        # jobs not yet started are no longer wanted; on a normal exit those in
        # progress run to the end (when the run is failing, the task group
        # cancels them)
        self._closed = True
        self._permits.drop_waiting()
        self._tg = None
        # jobs raise no Exception, so a group holds only the host's own error:
        # raise it as it was raised
        with unwrap_exception_group("single"):
            suppress = await self._exit_stack.__aexit__(exc_type, exc, tb)
        fatal = self._fatal
        if fatal is not None and not _contains(exc, fatal):
            raise fatal
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

    def cancel_running(self) -> None:
        """Cancel the setups in progress (the run was cancelled)."""
        for job in self._jobs.values():
            job.scope.cancel()

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
            await job.done.wait()
            if job.failure is not None:
                job.failure.raise_again()
            if not job.succeeded:
                raise RuntimeError(f"The setup of {job.key!r} was cancelled.")

    def _join(self, key: K, needed: bool) -> _Job[K]:
        job = self._jobs.get(key)
        if job is None:
            if self._tg is None:
                raise RuntimeError("The setup cache has been left.")
            job = self._jobs[key] = _Job(key, needed)
            self._permits.request(job)
            self._context.copy().run(self._tg.start_soon, self._run, job)
        elif needed:
            job.needed = True
        return job

    async def _run(self, job: _Job[K]) -> None:
        try:
            await job.granted.wait()
            if self._closed:
                # dropped before it started (holds no permit)
                return
            with job.scope:
                try:
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
            if run_cancelled():
                raise
            self._fail(job, RuntimeError(f"The setup of {job.key!r} raised {ex!r}."))
        except Exception as ex:
            self._fail(job, ex)
        except BaseException as ex:
            # KeyboardInterrupt, SystemExit: given to the waiters, and raised
            # when the cache is left, rather than raised in this task (asyncio
            # stops its event loop on these when a task raises them)
            if self._fatal is None:
                self._fatal = ex
            self._fail(job, ex)
        finally:
            self._forget(job)

    def _forget(self, job: _Job[K]) -> None:
        """End a job's bookkeeping; a job that did not succeed is forgotten."""
        if not job.succeeded and self._jobs.get(job.key) is job:
            del self._jobs[job.key]
        job.on_done = []
        job.done.set()

    def _fail(self, job: _Job[K], error: BaseException) -> None:
        # forgotten before the waiters hear, so one that asks again starts a
        # fresh job
        job.failure = SetupFailure.of(error)
        if self._jobs.get(job.key) is job:
            del self._jobs[job.key]
        for on_done in job.on_done:
            on_done(job.failure)


def _contains(exc: BaseException | None, target: BaseException) -> bool:
    """Whether ``exc`` is ``target`` or an exception group holding it."""
    if exc is target:
        return True
    if isinstance(exc, BaseExceptionGroup):
        return exc.subgroup(lambda e: e is target) is not None
    return False
