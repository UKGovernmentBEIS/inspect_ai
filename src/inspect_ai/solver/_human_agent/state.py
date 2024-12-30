import time
from typing import Any, TypeVar

from pydantic import BaseModel, JsonValue

from inspect_ai.scorer._metric import Score

from .._task_state import TaskState

VT = TypeVar("VT")


class IntermediateScore(BaseModel):
    time: float
    scores: list[Score]


class HumanAgentState:
    def __init__(self, state: TaskState) -> None:
        self._instructions = "\n\n".join(
            [message.text for message in state.messages]
        ).strip()
        self._store = state.store
        self._set(self.INTERMEDIATE_SCORES, [])
        self.running = True

    @property
    def instructions(self) -> str:
        return self._instructions

    @property
    def running(self) -> bool:
        return self._get(self.RUNNING, False)

    @running.setter
    def running(self, running: bool) -> None:
        # if we are flipping to running mode then update started running
        if not self.running and running:
            self._started_running = time.time()

        # if we are exiting running mode then update accumulated time
        if self.running and not running:
            self._accumulated_time = self.time

        # update running
        self._set(self.RUNNING, running)

    @property
    def time(self) -> float:
        running_time = time.time() - self._started_running if self.running else 0
        return self._accumulated_time + running_time

    @property
    def answer(self) -> str | None:
        return self._get(self.ANSWER, None)

    @answer.setter
    def answer(self, answer: str | None) -> None:
        self._set(self.ANSWER, answer)
        self._set(self.COMPLETED, True)

    @property
    def intermediate_scores(self) -> list[IntermediateScore]:
        return self._get(self.INTERMEDIATE_SCORES, [])

    @property
    def session_logs(self) -> dict[str, str] | None:
        return self._get(self.SESSION_LOGS, None)

    @session_logs.setter
    def session_logs(self, session_logs: dict[str, str] | None) -> None:
        self._set(self.SESSION_LOGS, session_logs)

    @property
    def completed(self) -> bool:
        return self._get(self.COMPLETED, False)

    @property
    def status(self) -> dict[str, JsonValue]:
        return dict(running=self.running, time=self.time)

    @property
    def _started_running(self) -> float:
        return self._get(self.STARTED_RUNNING, 0.0)

    @_started_running.setter
    def _started_running(self, time: float) -> None:
        self._set(self.STARTED_RUNNING, time)

    @property
    def _accumulated_time(self) -> float:
        return self._get(self.ACCUMULATED_TIME, 0.0)

    @_accumulated_time.setter
    def _accumulated_time(self, time: float) -> None:
        self._set(self.ACCUMULATED_TIME, time)

    def _get(self, key: str, default: VT) -> VT:
        return self._store.get(f"{self.AGENT_STATE}:{key}", default)

    def _set(self, key: str, value: Any) -> None:
        self._store.set(f"{self.AGENT_STATE}:{key}", value)

    AGENT_STATE = "human_agent_state"
    RUNNING = "running"
    STARTED_RUNNING = "started_running"
    ACCUMULATED_TIME = "accumulated_time"
    ANSWER = "answer"
    INTERMEDIATE_SCORES = "intermediate_scores"
    SESSION_LOGS = "session_logs"
    COMPLETED = "completed"
