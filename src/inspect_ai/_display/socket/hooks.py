from __future__ import annotations

import logging
from typing import Any

from inspect_ai._util.registry import RegistryInfo, registry_add
from inspect_ai.hooks._hooks import (
    Hooks,
    ModelUsageData,
    SampleEnd,
    SampleScoring,
    SampleStart,
)

from .protocol import (
    PrintMessage,
    SampleEndMessage,
    SampleStartMessage,
)
from .server import SocketServer
from .state import StateManager

logger = logging.getLogger(__name__)


class SocketHooks(Hooks):
    def __init__(self, state: StateManager, server: SocketServer) -> None:
        self._state = state
        self._server = server

    def enabled(self) -> bool:
        return True

    async def on_sample_start(self, data: SampleStart) -> None:
        task_name = ""
        model = ""
        msg = await self._state.on_sample_start(
            run_id=data.run_id,
            eval_id=data.eval_id,
            sample_id=data.sample_id,
            task_name=task_name,
            model=model,
        )
        await self._server.broadcast(msg)

    async def on_sample_end(self, data: SampleEnd) -> None:
        scores: dict[str, Any] | None = None
        if data.sample and data.sample.scores:
            scores = {}
            for scorer_name, score_obj in data.sample.scores.items():
                scores[scorer_name] = str(score_obj.value) if score_obj.value is not None else None

        msg = await self._state.on_sample_end(
            run_id=data.run_id,
            eval_id=data.eval_id,
            sample_id=data.sample_id,
            scores=scores,
        )
        await self._server.broadcast(msg)

    async def on_model_usage(self, data: ModelUsageData) -> None:
        msg = PrintMessage(
            message=f"Model usage: {data.model_name} "
            f"({data.usage.input_tokens}in/{data.usage.output_tokens}out, "
            f"{data.call_duration:.1f}s)"
        )
        await self._server.broadcast(msg)

    async def on_sample_scoring(self, data: SampleScoring) -> None:
        msg = PrintMessage(
            message=f"Scoring sample: {data.sample_id}"
        )
        await self._server.broadcast(msg)


def register_socket_hooks(state: StateManager, server: SocketServer) -> SocketHooks:
    hooks = SocketHooks(state, server)
    registry_add(
        hooks,
        RegistryInfo(
            type="hooks",
            name="socket-remote-control",
            metadata={"description": "Socket display remote control hooks"},
        ),
    )
    return hooks
