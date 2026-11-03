"""One shared setup job per sandbox config, for one eval run.

Many tasks of a run can use the same sandbox config, whose setup (a provider's
``task_init``: an image build or pull, a cloud environment) is slow and must
run once. :class:`SetupCache` keeps one job per key: a request joins the key's
job if there is one (waiting, running, succeeded or failed) and adds one
otherwise. A worker runs the jobs one at a time, while there are any: in the
order they were requested, except that a job someone waits for now
(:meth:`SetupCache.ensure`, a task's retry) goes ahead of those requested
ahead of need. A failed job is kept, so later requests for its key fail at
once; only a task's retry sets a failed key up again, at most once per
attempt number (see :meth:`SetupCache.request_for_retry`). A waiting job nobody needs any
more (its task was cancelled before it started) is dropped; a job that has
started always runs on. Leaving the cache cancels the job in progress and
drops those still waiting.

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

    def __init__(self, key: K, attempt: int) -> None:
        self.key = key
        self.attempt = attempt
        """The task attempt it was added for: 1, or the retry that set its key
        up again after a failure."""
        self.done = anyio.Event()
        self.failure: SetupFailure | None = None

    @property
    def succeeded(self) -> bool:
        return self.done.is_set() and self.failure is None


class SetupCache(Generic[K]):
    """One shared setup job per key (see the module docstring).

    Use as an async context manager around everything that requests setups.
    """

    def __init__(
        self, setup: Callable[[K], Awaitable[None]], *, on_done: Callable[[], None]
    ) -> None:
        """Create the cache.

        Args:
            setup: Sets up one key.
            on_done: Called as each job ends (succeeded or failed).
        """
        self._setup = setup
        self._on_done = on_done
        self._jobs: dict[K, SetupJob[K]] = {}
        self._waiting: deque[SetupJob[K]] = deque()
        self._working = False
        self._ensuring: list[SetupJob[K]] = []
        """The jobs an :meth:`ensure` call is waiting for."""
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

    def request(self, keys: Iterable[K]) -> list[SetupJob[K]]:
        """The jobs of ``keys``, adding those it lacks, for queued tasks."""
        return [self._job_for(key, attempt=1) for key in keys]

    def request_for_retry(self, keys: Iterable[K], attempt: int) -> list[SetupJob[K]]:
        """The jobs of ``keys`` for a task's retry, ahead of the jobs waiting.

        ``attempt`` is the retry's attempt number. A key whose job failed for
        an earlier attempt gets a new job for this one; every other job is
        joined, including a failed one that another task's retry added for
        this attempt or a later one. So however many tasks share a broken
        key, it is set up at most once per attempt number: 1 + retries times.
        """
        jobs = [self._job_for(key, attempt) for key in keys]
        self._move_ahead(jobs)
        return jobs

    def has_jobs(self, keys: Iterable[K]) -> bool:
        """Whether every key has a job (waiting, running, succeeded or failed), so requesting them adds none."""
        return all(key in self._jobs for key in keys)

    async def ensure(self, keys: Iterable[K]) -> None:
        """Set up ``keys``, ahead of the jobs waiting, and wait until they are.

        Raises:
            BaseException: What the first failed job raised.
        """
        jobs = self.request(keys)
        self._move_ahead(jobs)
        self._ensuring.extend(jobs)
        try:
            for job in jobs:
                await job.done.wait()
                if job.failure is not None:
                    job.failure.raise_again()
        finally:
            for job in jobs:
                self._ensuring.remove(job)

    def drop_waiting(self, keep: Iterable[K]) -> None:
        """Drop the jobs still waiting whose keys are not in ``keep``.

        For the setups of a queued task that will now never start (it was
        cancelled): they would create resources nobody uses. A job an
        :meth:`ensure` call waits for is kept, and so is every job that has
        started: interrupting a ``task_init`` can leave resources that
        nothing cleans up.
        """
        kept = set(keep) | {job.key for job in self._ensuring}
        for job in [job for job in self._waiting if job.key not in kept]:
            self._waiting.remove(job)
            del self._jobs[job.key]

    def _job_for(self, key: K, attempt: int) -> SetupJob[K]:
        """The key's job, or a new one if it has none or failed for an earlier attempt."""
        job = self._jobs.get(key)
        if job is not None and not (job.failure is not None and job.attempt < attempt):
            return job
        if self._tg is None:
            raise RuntimeError("The setup cache has been left.")
        job = self._jobs[key] = SetupJob(key, attempt)
        self._waiting.append(job)
        if not self._working:
            self._working = True
            self._context.copy().run(self._tg.start_soon, self._work)
        return job

    def _move_ahead(self, jobs: list[SetupJob[K]]) -> None:
        """Move those of ``jobs`` still waiting ahead of the other jobs waiting.

        For a caller that needs them now (a retry, a running task's
        ``SampleSource`` adding samples with a new config, the seed before the
        run starts); other jobs are for queued tasks, which can wait.
        """
        waiting = [job for job in jobs if job in self._waiting]
        for job in waiting:
            self._waiting.remove(job)
        self._waiting.extendleft(reversed(waiting))

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
            self._on_done()
        self._working = False

    def _fail(self, job: SetupJob[K], error: BaseException) -> None:
        job.failure = SetupFailure.of(error)
