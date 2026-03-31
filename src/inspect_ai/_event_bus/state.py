from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

import time

from .protocol import (
    MetricValue,
    MetricsUpdateMessage,
    ProgressUpdateMessage,
    SampleCancelledMessage,
    PendingInputInfo,
    SampleInfo,
    SampleCompleteMessage,
    SampleEndMessage,
    SampleStartMessage,
    ServerMessage,
    SnapshotMessage,
    TaskCompleteMessage,
    TaskInfo,
    TaskProgress,
    TaskStartMessage,
)

MAX_RECENT_EVENTS = 200


class StateManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tasks: dict[str, TaskProgress] = {}
        self._active_samples: dict[str, SampleInfo] = {}
        self._input_manager: Any = None
        self._recent_events: deque[dict[str, Any]] = deque(maxlen=MAX_RECENT_EVENTS)

    def _task_key(self, task_name: str, model: str) -> str:
        return f"{task_name}::{model}"

    async def on_task_start(self, task: TaskInfo) -> TaskStartMessage:
        async with self._lock:
            key = self._task_key(task.name, task.model)
            self._tasks[key] = TaskProgress(
                task_name=task.name,
                model=task.model,
                samples_total=task.samples,
                steps_total=task.steps,
            )
            msg = TaskStartMessage(task=task)
            self._recent_events.append(msg.model_dump())
            return msg

    async def on_sample_complete(
        self, task_name: str, model: str, complete: int, total: int
    ) -> SampleCompleteMessage:
        async with self._lock:
            key = self._task_key(task_name, model)
            if key in self._tasks:
                self._tasks[key].samples_complete = complete
                self._tasks[key].samples_total = total
            msg = SampleCompleteMessage(
                task_name=task_name, model=model, complete=complete, total=total
            )
            self._recent_events.append(msg.model_dump())
            return msg

    async def on_metrics_update(
        self, task_name: str, model: str, metrics: list[MetricValue]
    ) -> MetricsUpdateMessage:
        async with self._lock:
            key = self._task_key(task_name, model)
            if key in self._tasks:
                self._tasks[key].metrics = metrics
            msg = MetricsUpdateMessage(
                task_name=task_name, model=model, metrics=metrics
            )
            self._recent_events.append(msg.model_dump())
            return msg

    async def on_progress_update(
        self, task_name: str, model: str, steps_complete: int, steps_total: int
    ) -> ProgressUpdateMessage:
        async with self._lock:
            key = self._task_key(task_name, model)
            if key in self._tasks:
                self._tasks[key].steps_complete = steps_complete
                self._tasks[key].steps_total = steps_total
            msg = ProgressUpdateMessage(
                task_name=task_name,
                model=model,
                steps_complete=steps_complete,
                steps_total=steps_total,
            )
            return msg

    async def on_task_complete(
        self,
        task_name: str,
        model: str,
        status: str,
        samples_completed: int,
        error: str | None = None,
    ) -> TaskCompleteMessage:
        async with self._lock:
            key = self._task_key(task_name, model)
            if key in self._tasks:
                self._tasks[key].status = status  # type: ignore[assignment]
                self._tasks[key].samples_complete = samples_completed
            msg = TaskCompleteMessage(
                task_name=task_name,
                model=model,
                status=status,  # type: ignore[arg-type]
                samples_completed=samples_completed,
                error=error,
            )
            self._recent_events.append(msg.model_dump())
            return msg

    async def on_sample_start(
        self, run_id: str, eval_id: str, sample_id: str,
        task_name: str = "", model: str = "",
    ) -> SampleStartMessage:
        async with self._lock:
            self._active_samples[sample_id] = SampleInfo(
                sample_id=sample_id, task_name=task_name, model=model,
                status="running", started_at=time.time(),
            )
            msg = SampleStartMessage(
                run_id=run_id, eval_id=eval_id, sample_id=sample_id
            )
            self._recent_events.append(msg.model_dump())
            return msg

    async def on_sample_end(
        self,
        run_id: str,
        eval_id: str,
        sample_id: str,
        scores: dict[str, Any] | None = None,
    ) -> SampleEndMessage:
        async with self._lock:
            self._active_samples.pop(sample_id, None)
            msg = SampleEndMessage(
                run_id=run_id, eval_id=eval_id, sample_id=sample_id, scores=scores
            )
            self._recent_events.append(msg.model_dump())
            return msg

    async def on_sample_cancelled(
        self, sample_id: str | int, reason: str | None = None
    ) -> SampleCancelledMessage:
        async with self._lock:
            self._active_samples.pop(str(sample_id), None)
            msg = SampleCancelledMessage(sample_id=sample_id, reason=reason)
            self._recent_events.append(msg.model_dump())
            return msg

    async def snapshot(self) -> SnapshotMessage:
        async with self._lock:
            pending_inputs: list[PendingInputInfo] = []
            if self._input_manager:
                pending_inputs = [
                    PendingInputInfo(
                        request_id=p.request_id,
                        prompt=p.prompt,
                        sample_id=p.sample_id,
                    )
                    for p in self._input_manager.pending_requests()
                ]
            return SnapshotMessage(
                tasks=list(self._tasks.values()),
                active_samples=list(self._active_samples.values()),
                pending_inputs=pending_inputs,
                recent_events=list(self._recent_events),
            )
