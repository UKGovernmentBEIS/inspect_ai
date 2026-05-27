"""Trackio Tracking hook for Inspect AI.

Logs each evaluation sample to Trackio as a `trackio.Trace` — the full
conversation messages, the target, and the scores attached as metadata —
so you can inspect any sample directly on the Trackio dashboard.

Trackio (https://github.com/gradio-app/trackio) is a lightweight,
local-first experiment tracker with a wandb-compatible API and a
first-class Trace primitive that maps cleanly onto an Inspect EvalSample.

To enable, set ``TRACKIO_PROJECT`` (and optionally ``TRACKIO_SPACE_ID``):

    export TRACKIO_PROJECT="inspect-evals"
    export TRACKIO_SPACE_ID="my-org/my-dashboard"  # optional

Then import this module before running evals (e.g. in a conftest.py or your
task file)::

    from examples.hooks.trackio_tracking import TrackioHooks  # noqa: F401

    inspect eval my_task.py
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import trackio  # type: ignore[import-not-found]

from inspect_ai.hooks import (
    Hooks,
    RunEnd,
    RunStart,
    SampleEnd,
    hooks,
)

logger = logging.getLogger(__name__)


def _content_to_text(content: Any) -> str:
    """Best-effort coercion of an Inspect ChatMessage.content to a plain string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text is not None:
                parts.append(str(text))
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or item))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def _messages_to_trace_messages(messages: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages or []:
        role = getattr(m, "role", None) or "user"
        content = _content_to_text(getattr(m, "content", None))
        out.append({"role": str(role), "content": content})
    return out


def _scores_to_metadata(scores: dict[str, Any] | None) -> dict[str, Any]:
    if not scores:
        return {}
    flat: dict[str, Any] = {}
    for name, score in scores.items():
        value = getattr(score, "value", score)
        flat[f"score/{name}"] = value
        explanation = getattr(score, "explanation", None)
        if explanation:
            flat[f"score/{name}/explanation"] = explanation
    return flat


@hooks(
    name="trackio_tracking",
    description="Log each Inspect AI sample to Trackio as a trackio.Trace.",
)
class TrackioHooks(Hooks):
    """Logs each Inspect sample as a ``trackio.Trace``.

    A run-level Trackio run is created in ``on_run_start`` (rank-0 only,
    keyed off ``TRACKIO_PROJECT``); every sample emits one Trace with the
    sample's full conversation as messages and its scores + target as
    metadata.

    Trackio's Python client is synchronous; calls are dispatched via
    ``asyncio.to_thread`` to keep Inspect's async event loop unblocked.
    """

    def __init__(self) -> None:
        self._initialized = False
        self._step = 0

    def enabled(self) -> bool:
        return os.getenv("TRACKIO_PROJECT") is not None

    async def on_run_start(self, data: RunStart) -> None:
        if self._initialized:
            return
        project = os.getenv("TRACKIO_PROJECT") or "inspect-ai"
        space_id = os.getenv("TRACKIO_SPACE_ID") or None
        kwargs: dict[str, Any] = {"project": project}
        if space_id:
            kwargs["space_id"] = space_id
        try:
            await asyncio.to_thread(trackio.init, **kwargs)
            self._initialized = True
        except Exception as e:
            logger.warning(f"trackio.init failed; subsequent logs will be no-ops: {e}")

    async def on_sample_end(self, data: SampleEnd) -> None:
        if not self._initialized:
            return
        sample = data.sample
        messages = _messages_to_trace_messages(getattr(sample, "messages", []) or [])
        if not messages and getattr(sample, "input", None):
            inp = sample.input
            if isinstance(inp, str):
                messages.append({"role": "user", "content": inp})
            else:
                messages.extend(_messages_to_trace_messages(inp))

        output = getattr(sample, "output", None)
        completion = getattr(output, "completion", None) if output else None
        if completion:
            messages.append({"role": "assistant", "content": str(completion)})

        target = getattr(sample, "target", None)
        metadata: dict[str, Any] = {
            "sample_id": str(getattr(sample, "id", "")),
            "epoch": getattr(sample, "epoch", None),
            "target": target,
            "eval_id": data.eval_id,
            "run_id": data.run_id,
        }
        metadata.update(_scores_to_metadata(getattr(sample, "scores", None)))

        step = self._step
        self._step += 1

        try:
            trace = trackio.Trace(messages=messages, metadata=metadata)
            await asyncio.to_thread(trackio.log, {"sample": trace}, step=step)
        except Exception as e:
            logger.warning(
                f"Failed to log Trackio trace for sample {metadata['sample_id']}: {e}"
            )

    async def on_run_end(self, data: RunEnd) -> None:
        if not self._initialized:
            return
        try:
            await asyncio.to_thread(trackio.finish)
        except Exception as e:
            logger.warning(f"trackio.finish raised: {e}")
        self._initialized = False
