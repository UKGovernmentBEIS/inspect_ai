from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, AsyncIterator, Callable, Coroutine, Iterator

import anyio

from inspect_ai._util._async import configured_async_backend
from inspect_ai._util.platform import running_in_notebook

from ..core.display import (
    TR,
    Display,
    Progress,
    TaskDisplay,
    TaskDisplayMetric,
    TaskProfile,
    TaskResult,
    TaskScreen,
    TaskSpec,
    TaskSuccess,
    TaskCancelled,
    TaskError,
    TaskWithResult,
)
from .cancel import CancelManager, SocketEarlyStopping
from .protocol import (
    EvalCompleteMessage,
    MetricValue,
    PrintMessage,
    TaskInfo,
)
from .server import SocketServer
from .state import StateManager

logger = logging.getLogger(__name__)


class SocketDisplay(Display):
    def __init__(self) -> None:
        self._state = StateManager()
        self._cancel_manager = CancelManager()
        self._server = SocketServer(
            state=self._state,
            on_cancel_sample=self._handle_cancel,
        )
        self._tasks: list[TaskWithResult] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def early_stopping(self) -> SocketEarlyStopping:
        return SocketEarlyStopping(self._cancel_manager)

    @property
    def socket_path(self) -> str:
        return self._server.socket_path

    async def _handle_cancel(self, sample_id: str | int) -> None:
        self._cancel_manager.cancel(sample_id)
        msg = await self._state.on_sample_cancelled(
            sample_id, reason="Cancelled by remote client"
        )
        await self._server.broadcast(msg)

    def print(self, message: str) -> None:
        msg = PrintMessage(message=message)
        self._broadcast_sync(msg)

    @contextlib.contextmanager
    def progress(self, total: int) -> Iterator[Progress]:
        yield SocketProgress(
            total=total,
            task_name="",
            model="",
            broadcast_sync=self._broadcast_sync,
        )

    def run_task_app(self, main: Callable[[], Coroutine[None, None, TR]]) -> TR:
        async def _run() -> TR:
            await self._server.start()
            from .hooks import register_socket_hooks

            register_socket_hooks(self._state, self._server)
            try:
                return await main()
            finally:
                await self._server.broadcast(EvalCompleteMessage())
                print(
                    f"\nEval complete. Socket stays open for 30s at: "
                    f"{self._server.socket_path}"
                )
                await asyncio.sleep(30)
                await self._server.stop()

        if running_in_notebook():
            from inspect_ai._util._async import run_coroutine

            return run_coroutine(_run())
        else:
            return anyio.run(_run, backend=configured_async_backend())

    @contextlib.contextmanager
    def suspend_task_app(self) -> Iterator[None]:
        yield

    @contextlib.asynccontextmanager
    async def task_screen(
        self, tasks: list[TaskSpec], parallel: bool
    ) -> AsyncIterator[TaskScreen]:
        self._tasks = []
        yield TaskScreen()

    @contextlib.contextmanager
    def task(self, profile: TaskProfile) -> Iterator[TaskDisplay]:
        task_info = TaskInfo(
            name=profile.name,
            model=str(profile.model),
            dataset=profile.dataset,
            scorer=profile.scorer,
            samples=profile.samples,
            steps=profile.steps,
            log_location=profile.log_location,
            tags=profile.tags,
        )

        self._run_async(self._state.on_task_start(task_info))
        from .protocol import TaskStartMessage
        self._broadcast_sync(TaskStartMessage(task=task_info))

        task_with_result = TaskWithResult(profile, None)
        self._tasks.append(task_with_result)

        td = SocketTaskDisplay(
            task_with_result=task_with_result,
            state=self._state,
            server=self._server,
            broadcast_sync=self._broadcast_sync,
            run_async=self._run_async,
        )
        yield td

    def display_counter(self, caption: str, value: str) -> None:
        pass

    def _broadcast_sync(self, msg: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._server.broadcast(msg))
        except RuntimeError:
            pass

    def _run_async(self, coro: Any) -> Any:
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(coro)
            return None
        except RuntimeError:
            return asyncio.run(coro)


class SocketProgress(Progress):
    def __init__(
        self,
        total: int,
        task_name: str,
        model: str,
        broadcast_sync: Callable[[Any], None],
    ) -> None:
        self.total = total
        self.current = 0
        self._task_name = task_name
        self._model = model
        self._broadcast_sync = broadcast_sync

    def update(self, n: int = 1) -> None:
        self.current += n
        from .protocol import ProgressUpdateMessage

        self._broadcast_sync(
            ProgressUpdateMessage(
                task_name=self._task_name,
                model=self._model,
                steps_complete=self.current,
                steps_total=self.total,
            )
        )

    def complete(self) -> None:
        self.current = self.total


class SocketTaskDisplay(TaskDisplay):
    def __init__(
        self,
        task_with_result: TaskWithResult,
        state: StateManager,
        server: SocketServer,
        broadcast_sync: Callable[[Any], None],
        run_async: Callable[[Any], Any],
    ) -> None:
        self._task = task_with_result
        self._state = state
        self._server = server
        self._broadcast_sync = broadcast_sync
        self._run_async = run_async
        self._progress: SocketProgress | None = None

    @contextlib.contextmanager
    def progress(self) -> Iterator[Progress]:
        self._progress = SocketProgress(
            total=self._task.profile.steps,
            task_name=self._task.profile.name,
            model=str(self._task.profile.model),
            broadcast_sync=self._broadcast_sync,
        )
        yield self._progress

    def sample_complete(self, complete: int, total: int) -> None:
        coro = self._state.on_sample_complete(
            self._task.profile.name, str(self._task.profile.model), complete, total
        )
        self._run_async(coro)
        from .protocol import SampleCompleteMessage

        msg = SampleCompleteMessage(
            task_name=self._task.profile.name,
            model=str(self._task.profile.model),
            complete=complete,
            total=total,
        )
        self._broadcast_sync(msg)

    def update_metrics(self, scores: list[TaskDisplayMetric]) -> None:
        metrics = [
            MetricValue(
                scorer=s.scorer,
                name=s.name,
                value=s.value,
                reducer=s.reducer,
            )
            for s in scores
        ]
        coro = self._state.on_metrics_update(
            self._task.profile.name, str(self._task.profile.model), metrics
        )
        self._run_async(coro)
        from .protocol import MetricsUpdateMessage

        msg = MetricsUpdateMessage(
            task_name=self._task.profile.name,
            model=str(self._task.profile.model),
            metrics=metrics,
        )
        self._broadcast_sync(msg)

    def complete(self, result: TaskResult) -> None:
        self._task.result = result
        if isinstance(result, TaskSuccess):
            status = "success"
        elif isinstance(result, TaskCancelled):
            status = "cancelled"
        else:
            status = "error"

        error_str = None
        if isinstance(result, TaskError):
            error_str = str(result.exc_value)

        coro = self._state.on_task_complete(
            self._task.profile.name,
            str(self._task.profile.model),
            status,
            result.samples_completed,
            error_str,
        )
        self._run_async(coro)
        from .protocol import TaskCompleteMessage

        msg = TaskCompleteMessage(
            task_name=self._task.profile.name,
            model=str(self._task.profile.model),
            status=status,  # type: ignore[arg-type]
            samples_completed=result.samples_completed,
            error=error_str,
        )
        self._broadcast_sync(msg)
