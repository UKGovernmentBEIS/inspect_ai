from __future__ import annotations

import asyncio
import sys
from typing import Any

from inspect_ai.model import ChatMessageUser
from inspect_ai.solver import Solver, TaskState, solver

from .input_manager import InputManager

_bus_server: Any = None
_bus_input_manager: InputManager | None = None


def set_bus(server: Any, input_manager: InputManager) -> None:
    global _bus_server, _bus_input_manager
    _bus_server = server
    _bus_input_manager = input_manager


@solver
def ask_human(prompt: str = "Waiting for human input...") -> Solver:
    async def _solve(state: TaskState, generate: Any) -> TaskState:
        if _bus_input_manager is None or _bus_server is None:
            print(f"\n[ask_human] {prompt}")
            response = input("> ")
            state.messages.append(ChatMessageUser(content=response))
            return state

        from .protocol import InputRequestedMessage

        pending = _bus_input_manager.create_request(prompt)
        msg = InputRequestedMessage(
            request_id=pending.request_id,
            prompt=prompt,
            sample_id=str(state.sample_id) if state.sample_id else None,
        )
        await _bus_server.broadcast(msg)

        await pending.event.wait()

        response_text = pending.response or ""
        _bus_input_manager.remove(pending.request_id)

        state.messages.append(ChatMessageUser(content=f"[Human]: {response_text}"))
        return state

    return _solve
