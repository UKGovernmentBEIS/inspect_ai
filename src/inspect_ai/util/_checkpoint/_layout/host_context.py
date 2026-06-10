"""On-disk schema for the host context written at each checkpoint fire.

A sample working dir holds five JSON files that restic snapshots each
cycle:

- ``events.json`` — condensed transcript events.
- ``events_data.json`` — ``EventsData`` (messages, calls dedup pools).
- ``attachments.json`` — hash → original-content pool.
- ``store.json`` — Store key/value.
- ``agent_state.json`` — agent-defined property bag (optional; written
  only when the agent has registered at least one ``track()`` callback).

This module owns the on-disk schema: filename constants, the
serialization format, and the read shape. Keeping the schema centralized
prevents drift between fire-time and resume-time code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from inspect_ai.event._event import Event
from inspect_ai.event._validate import validate_chat_messages, validate_events_json
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
