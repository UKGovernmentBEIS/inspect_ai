"""One shared setup job per sandbox config, for one eval run.

Many tasks of a run can use the same sandbox config, whose setup (a provider's
``task_init``: an image build or pull, a cloud environment) is slow and must
run once. :class:`SetupCache` keeps one job per key: a request joins the key's
job if there is one (waiting, running or succeeded) and adds one otherwise. A
worker runs the jobs one at a time, while there are any: in the order they
were requested, except that a job someone waits for now (:meth:`SetupCache.ensure`)
goes ahead of those requested ahead of need. A failed job is forgotten, so
the next request for its key adds a new one.
Leaving the cache cancels the job in progress and drops those still waiting.

The cache is used only from the run's event loop, and its bookkeeping does
not await, so it needs no lock.
"""

from collections import deque
from contextvars import Context, copy_context
from types import TracebackType
from typing import (
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

        One failure can reach several tasks, each raising the same exception
        object; starting from the setup's traceback keeps one task's frames
        out of another's log.
        """
        raise self.error.with_traceback(self.traceback)


class SetupJob(Generic[K]):
    """The setup of one key."""

    def __init__(self, key: K) -> None:
        self.key = key
        self.done = anyio.Event()
        self.failure: SetupFailure | None = None
        self.on_done: list[Callable[[], None]] = []

    @property
    def succeeded(self) -> bool:
        return self.done.is_set() and self.failure is None


class SetupCache(Generic[K]):
    """One shared setup job per key (see the module docstring).

    Use as an async context manager around everything that requests setups.
    """

    def __init__(self, setup: Callable[[K], Awaitable[None]]) -> None:
        self._setup = setup
        self._jobs: dict[K, SetupJob[K]] = {}
        self._waiting: deque[SetupJob[K]] = deque()
        self._working = False
        self._tg: TaskGroup | None = None
        self._context: Context
        """The context the worker starts from (taken on entry), not that of
        whichever task first requested a job."""
        self.fatal: BaseException | None = None
        """A ``KeyboardInterrupt`` or ``SystemExit`` a setup raised. The worker
        does not raise it (asyncio would stop its event loop): the run's
        scheduling loop and the waiters of its job do."""

    async def __aenter__(self) -> "SetupCache[K]":
        self._tg = anyio.create_task_group()
        await self._tg.__aenter__()
        self._context = copy_context()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        assert self._tg is not None
        tg, self._tg = self._tg, None
        tg.cancel_scope.cancel()
        # the worker raises nothing, so a group holds only the host's error
        with unwrap_exception_group("single"):
            try:
                return await tg.__aexit__(exc_type, exc, tb)
            except anyio.get_cancelled_exc_class():
                # a cancellation of the run that cancelled the worker: the
                # host left the cache normally (it absorbed the cancellation,
                # Ctrl-C), so leaving does not raise it again
                if exc_type is not None:
                    raise
                return None

    def request(
        self, keys: Iterable[K], on_done: Callable[[], None]
    ) -> list[SetupJob[K]]:
        """The jobs of ``keys``, adding those it lacks; ``on_done`` is called as each unfinished one ends."""
        jobs = [self._job(key) for key in keys]
        for job in jobs:
            if not job.done.is_set():
                job.on_done.append(on_done)
        return jobs

    def has_jobs(self, keys: Iterable[K]) -> bool:
        """Whether every key has a job (waiting, running or succeeded), so requesting them adds none."""
        return all(key in self._jobs for key in keys)

    async def ensure(self, keys: Iterable[K]) -> None:
        """Set up ``keys``, ahead of the jobs waiting, and wait until they are.

        For a caller that needs them now: a running task whose
        ``SampleSource`` adds samples with a new config, or the seed before the
        run starts. Jobs :meth:`request` added are for queued tasks, which can
        wait.

        Raises:
            BaseException: What the first failed job raised.
        """
        jobs = [self._job(key) for key in keys]
        waiting = [job for job in jobs if job in self._waiting]
        for job in waiting:
            self._waiting.remove(job)
        self._waiting.extendleft(reversed(waiting))
        for job in jobs:
            await job.done.wait()
            if job.failure is not None:
                job.failure.raise_again()

    def _job(self, key: K) -> SetupJob[K]:
        job = self._jobs.get(key)
        if job is None:
            if self._tg is None:
                raise RuntimeError("The setup cache has been left.")
            job = self._jobs[key] = SetupJob(key)
            self._waiting.append(job)
            if not self._working:
                self._working = True
                self._context.copy().run(self._tg.start_soon, self._work)
        return job

    async def _work(self) -> None:
        while self._waiting:
            job = self._waiting.popleft()
            try:
                await self._setup(job.key)
            except anyio.get_cancelled_exc_class() as ex:
                if run_cancelled():
                    raise
                # provider code can raise one itself on asyncio
                self._fail(
                    job, RuntimeError(f"The setup of {job.key!r} raised {ex!r}.")
                )
            except Exception as ex:
                self._fail(job, ex)
            except BaseException as ex:
                self.fatal = ex
                self._fail(job, ex)
            job.done.set()
            for on_done in job.on_done:
                on_done()
            job.on_done = []
        self._working = False

    def _fail(self, job: SetupJob[K], error: BaseException) -> None:
        job.failure = SetupFailure.of(error)
        del self._jobs[job.key]
