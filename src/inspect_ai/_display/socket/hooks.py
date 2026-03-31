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

from inspect_ai._event_bus.protocol import (
    PrintMessage,
    SampleEndMessage,
    SampleStartMessage,
)
from inspect_ai._event_bus.server import SocketServer
from inspect_ai._event_bus.state import StateManager

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
        if data.summary and hasattr(data.summary, 'input'):
            input_text = str(data.summary.input)[:100] if data.summary.input else ""
            if input_text:
                await self._server.broadcast(
                    PrintMessage(message=f"  📝 Input: {input_text}")
                )

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

        if scores:
            score_str = ", ".join(f"{k}={v}" for k, v in scores.items())
            correct = any(v == "C" for v in (scores or {}).values())
            icon = "✅" if correct else "❌"
            await self._server.broadcast(
                PrintMessage(message=f"  {icon} Score: {score_str}")
            )

    async def on_model_usage(self, data: ModelUsageData) -> None:
        try:
            from inspect_ai.log._samples import _active_model_event
            model_event = _active_model_event.get()
        except Exception:
            model_event = None

        if model_event is not None and model_event.output and model_event.output.completion:
            # Show user input (last user message)
            try:
                if model_event.input:
                    for m in reversed(model_event.input):
                        role = getattr(m, 'role', None)
                        if role == 'user':
                            text = getattr(m, 'text', None) or ""
                            if not text:
                                c = getattr(m, 'content', None)
                                if isinstance(c, str):
                                    text = c
                                elif isinstance(c, list) and c:
                                    text = getattr(c[0], 'text', str(c[0]))
                            if text:
                                await self._server.broadcast(
                                    PrintMessage(message=f"  👤 → {text[:100]}")
                                )
                            break
            except Exception:
                pass

            # Show model reply
            reply = model_event.output.completion[:100]
            await self._server.broadcast(
                PrintMessage(message=f"  🤖 ← {reply}")
            )
        else:
            # Fallback: just show token counts
            await self._server.broadcast(
                PrintMessage(
                    message=f"  🤖 {data.model_name}: "
                    f"{data.usage.input_tokens}in → {data.usage.output_tokens}out"
                )
            )

    async def on_sample_scoring(self, data: SampleScoring) -> None:
        msg = PrintMessage(
            message=f"  ⚖️ Scoring..."
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
