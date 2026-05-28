"""On-disk schema for the host context written at each checkpoint fire.

A sample working dir holds five JSON files that restic snapshots each
cycle (see ``design/plans/checkpointing-working.md`` §5):

- ``events.json`` — condensed transcript events.
- ``events_data.json`` — ``EventsData`` (messages, calls dedup pools).
- ``attachments.json`` — hash → original-content pool.
- ``store.json`` — Store key/value.
- ``agent_state.json`` — agent-defined property bag (optional; written
  only when the agent has registered at least one ``track()`` callback).

This module owns the on-disk schema: filename constants, the
serialization format, and the read/write pair. Write and read live
together so a typo in either is caught immediately and the schema
can't drift between fire-time (``checkpointer_impl._write_host_context``)
and resume-time (``hydrate._load_and_push_host_state``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
from pydantic import JsonValue
from pydantic_core import to_jsonable_python

from inspect_ai.event._event import Event
from inspect_ai.event._validate import validate_chat_messages, validate_events_json
from inspect_ai.log import EventsData
from inspect_ai.model._chat_message import ChatMessage

EVENTS = "events.json"
EVENTS_DATA = "events_data.json"
ATTACHMENTS = "attachments.json"
STORE = "store.json"
AGENT_STATE = "agent_state.json"


@dataclass
class HostContext:
    """One fire's worth of host-side state, serialized into the working dir."""

    condensed_events: list[Event]
    msg_pool: list[ChatMessage]
    call_pool: list[JsonValue]
    attachments: dict[str, str]
    store: dict[str, Any]
    agent_state: dict[str, Any] | None = None
    """``None`` skips writing ``agent_state.json`` entirely; absence on
    disk signals "the agent never opted in via ``track()``." On read,
    ``None`` is returned when the file is absent."""


async def write(working_dir: str, ctx: HostContext) -> None:
    """Write all host-context files to ``working_dir``, overwriting in place."""
    sample_dir = anyio.Path(working_dir)
    await _write_json(sample_dir / EVENTS, ctx.condensed_events)
    await _write_json(
        sample_dir / EVENTS_DATA,
        EventsData(messages=ctx.msg_pool, calls=ctx.call_pool),
    )
    await _write_json(sample_dir / ATTACHMENTS, ctx.attachments)
    await _write_json(sample_dir / STORE, ctx.store)
    if ctx.agent_state is not None:
        await _write_json(sample_dir / AGENT_STATE, ctx.agent_state)


async def _write_json(path: anyio.Path, obj: object) -> None:
    """Serialize ``obj`` to JSON and write to ``path`` (overwriting)."""
    await path.write_text(_json_dump(obj))


def read(working_dir: str) -> HostContext:
    """Read all host-context files from ``working_dir``.

    Synchronous (caller wraps in ``anyio.to_thread.run_sync`` if needed).
    """
    p = Path(working_dir)
    condensed_events: list[Event] = validate_events_json((p / EVENTS).read_text())
    raw_data = json.loads((p / EVENTS_DATA).read_text())
    msg_pool: list[ChatMessage] = validate_chat_messages(raw_data.get("messages", []))
    call_pool: list[JsonValue] = raw_data.get("calls", [])
    attachments: dict[str, str] = json.loads((p / ATTACHMENTS).read_text())
    store_data: dict[str, Any] = json.loads((p / STORE).read_text())
    agent_state_path = p / AGENT_STATE
    agent_state: dict[str, Any] | None = (
        json.loads(agent_state_path.read_text()) if agent_state_path.is_file() else None
    )
    return HostContext(
        condensed_events=condensed_events,
        msg_pool=msg_pool,
        call_pool=call_pool,
        attachments=attachments,
        store=store_data,
        agent_state=agent_state,
    )


def _json_dump(obj: object) -> str:
    """Serialize ``obj`` to JSON, excluding ``None`` fields, with a trailing newline."""
    return (
        json.dumps(to_jsonable_python(obj, exclude_none=True, fallback=lambda _: None))
        + "\n"
    )
