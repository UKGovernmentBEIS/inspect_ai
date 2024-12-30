import time
from typing import TypeVar

from pydantic import BaseModel, Field, JsonValue, field_validator

from inspect_ai.scorer._metric import Score
from inspect_ai.util._store_model import StoreModel

VT = TypeVar("VT")


class IntermediateScore(BaseModel):
    time: float
    scores: list[Score]


class HumanAgentState(StoreModel):
    instructions: str
    running: bool = Field(default=True)
    started_running: float = Field(default_factory=time.time)
    accumulated_time: float = Field(default=0.0)
    intermediate_scores: list[IntermediateScore] = Field(default_factory=list)
    answer: str | None = Field(default=None)
    session_logs: dict[str, str] = Field(default_factory=dict)

    def start_running(self) -> None:
        if not self.running:
            self.started_running = time.time()
        self.running = True

    def stop_running(self) -> None:
        if self.running:
            self.accumulated_time = self.time
        self.running = False

    @property
    def time(self) -> float:
        running_time = time.time() - self.started_running if self.running else 0
        return self.accumulated_time + running_time

    @property
    def status(self) -> dict[str, JsonValue]:
        return dict(running=self.running, time=self.time)

    @property
    def completed(self) -> bool:
        return self.answer is not None
