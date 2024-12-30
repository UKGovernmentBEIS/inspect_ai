import time
from typing import TypeVar

from pydantic import BaseModel, Field, JsonValue

from inspect_ai.scorer._metric import Score
from inspect_ai.util._store_model import StoreModel

VT = TypeVar("VT")


class IntermediateScore(BaseModel):
    time: float
    scores: list[Score]


class HumanAgentState(StoreModel):
    instructions: str
    answer: str | None = Field(default=None)

    intermediate_scores: list[IntermediateScore] = Field(default_factory=list)
    session_logs: dict[str, str] = Field(default_factory=dict)

    _running: bool = Field(default=True)
    _started_running: float = Field(default=0.0)
    _accumulated_time: float = Field(default=0.0)

    @property
    def running(self) -> bool:
        return self._running

    @running.setter
    def running(self, running: bool) -> None:
        # if we are flipping to running mode then update started running
        if not self.running and running:
            self._started_running = time.time()

        # if we are exiting running mode then update accumulated time
        if self.running and not running:
            self._accumulated_time = self.time

        # update running
        self._running = running

    @property
    def time(self) -> float:
        running_time = time.time() - self._started_running
        return self._accumulated_time + running_time

    @property
    def status(self) -> dict[str, JsonValue]:
        return dict(running=self.running, time=self.time)

    @property
    def completed(self) -> bool:
        return self.answer is not None
