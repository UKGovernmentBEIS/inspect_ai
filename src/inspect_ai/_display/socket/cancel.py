from __future__ import annotations

from typing import TYPE_CHECKING

from inspect_ai.util._early_stopping import EarlyStop, EarlyStopping

if TYPE_CHECKING:
    from inspect_ai.dataset._dataset import Sample
    from inspect_ai.log._log import EvalSpec
    from inspect_ai.scorer._metric import SampleScore

from pydantic import JsonValue


class CancelManager:
    def __init__(self) -> None:
        self._cancelled: set[str | int] = set()

    def cancel(self, sample_id: str | int) -> None:
        self._cancelled.add(sample_id)

    def is_cancelled(self, sample_id: str | int) -> bool:
        return sample_id in self._cancelled


class SocketEarlyStopping(EarlyStopping):
    def __init__(self, cancel_manager: CancelManager) -> None:
        self._cancel_manager = cancel_manager
        self._name = "socket-remote-control"

    async def start_task(
        self, task: "EvalSpec", samples: list["Sample"], epochs: int
    ) -> str:
        return self._name

    async def schedule_sample(self, id: str | int, epoch: int) -> EarlyStop | None:
        if self._cancel_manager.is_cancelled(id):
            return EarlyStop(id=id, epoch=epoch, reason="Cancelled by remote client")
        return None

    async def complete_sample(
        self,
        id: str | int,
        epoch: int,
        scores: dict[str, "SampleScore"],
    ) -> None:
        pass

    async def complete_task(self) -> dict[str, JsonValue]:
        return {"cancelled_samples": list(self._cancel_manager._cancelled)}
