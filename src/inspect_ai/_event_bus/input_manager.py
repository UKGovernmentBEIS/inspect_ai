from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class PendingInput:
    request_id: str
    prompt: str
    sample_id: str | None
    event: asyncio.Event = field(default_factory=asyncio.Event)
    response: str | None = None


class InputManager:
    def __init__(self) -> None:
        self._pending: dict[str, PendingInput] = {}

    def create_request(
        self, prompt: str, sample_id: str | None = None
    ) -> PendingInput:
        request_id = str(uuid4())[:8]
        pending = PendingInput(
            request_id=request_id, prompt=prompt, sample_id=sample_id
        )
        self._pending[request_id] = pending
        return pending

    def resolve(self, request_id: str, text: str) -> bool:
        pending = self._pending.get(request_id)
        if pending is None:
            return False
        pending.response = text
        pending.event.set()
        return True

    def remove(self, request_id: str) -> None:
        self._pending.pop(request_id, None)

    def pending_requests(self) -> list[PendingInput]:
        return list(self._pending.values())
