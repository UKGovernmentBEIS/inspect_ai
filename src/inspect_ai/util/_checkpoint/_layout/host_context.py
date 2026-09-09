"""On-disk schema for the host context written at each checkpoint fire.

A sample working dir holds seven JSON files that restic snapshots each
cycle:

- ``events.json`` — condensed transcript events.
- ``events_data.json`` — ``EventsData`` (messages, calls dedup pools).
- ``attachments.json`` — hash → original-content pool.
- ``store.json`` — Store key/value.
- ``agent_state.json`` — agent-defined property bag (optional; written
  only when the agent has registered at least one ``track()`` callback).
- ``assistant_internal.json`` — provider-smuggled wire content (optional;
  written only when a provider has recorded something — see
  ``inspect_ai.model._assistant_internal``).
- ``sample_runtime.json`` — sample-root limit usage and related in-memory
  runtime (always written on fire; absence on read means a pre-this-file
  checkpoint and usage stays reset-to-0).

This module owns the on-disk schema: filename constants, the
serialization format, and the read shape. Keeping the schema centralized
prevents drift between fire-time and resume-time code.

Capture-side invariant: the host writes only regular files into the
context dir — the JSON files above (``write_text_atomic`` /
``write_transcript_files``) plus the checkpointer's transcript-store
sqlite file and its journal side files — never symlinks. (Nested
directories occur only in lineages that earlier versions restored into a
non-empty ``context/`` on in-run requeue; see the bounds comment in
``hydrate``.) An honest snapshot therefore never contains anything but
regular files and directories. The restored files come from an untrusted
repo, so the resume-side checks — the snapshot listing check in
``restore_repo`` and the ``lstat`` regular-file check in :func:`read` —
reject anything else, and never fire on legitimate data.
"""

from __future__ import annotations

import json
import os
import stat
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
ASSISTANT_INTERNAL = "assistant_internal.json"
SAMPLE_RUNTIME = "sample_runtime.json"


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

    assistant_internal: JsonValue | None = None
    """Dump of provider-smuggled wire content (thinking blocks, tool call
    params) from ``dump_sample_assistant_internal()``. ``None`` skips
    writing ``assistant_internal.json``; on read, ``None`` is returned
    when the file is absent (no provider recorded anything, or the
    checkpoint predates this file)."""

    sample_runtime: JsonValue | None = None
    """Dump of sample-root limit usage and related runtime from
    ``dump_sample_runtime()``. Always written on fire. On read, ``None``
    is returned when the file is absent (checkpoint predates this
    file) — restore is then a no-op."""


def read(working_dir: str) -> HostContext:
    """Read all host-context files from ``working_dir``.

    Every file is read via :func:`_read_optional`; a symlink or other
    non-regular entry at any of the schema's filenames raises rather than
    being read through.

    Synchronous (caller wraps in ``anyio.to_thread.run_sync`` if needed).
    """
    p = Path(working_dir)
    condensed_events: list[Event] = validate_events_json(_read_required(p / EVENTS))
    raw_data = json.loads(_read_required(p / EVENTS_DATA))
    msg_pool: list[ChatMessage] = validate_chat_messages(raw_data.get("messages", []))
    call_pool: list[JsonValue] = raw_data.get("calls", [])
    attachments: dict[str, str] = json.loads(_read_required(p / ATTACHMENTS))
    store_data: dict[str, Any] = json.loads(_read_required(p / STORE))
    agent_state_text = _read_optional(p / AGENT_STATE)
    agent_state: dict[str, Any] | None = (
        json.loads(agent_state_text) if agent_state_text is not None else None
    )
    assistant_internal_text = _read_optional(p / ASSISTANT_INTERNAL)
    assistant_internal: JsonValue | None = (
        json.loads(assistant_internal_text)
        if assistant_internal_text is not None
        else None
    )
    sample_runtime_text = _read_optional(p / SAMPLE_RUNTIME)
    sample_runtime: JsonValue | None = (
        json.loads(sample_runtime_text) if sample_runtime_text is not None else None
    )
    return HostContext(
        condensed_events=condensed_events,
        msg_pool=msg_pool,
        call_pool=call_pool,
        attachments=attachments,
        store=store_data,
        agent_state=agent_state,
        assistant_internal=assistant_internal,
        sample_runtime=sample_runtime,
    )


def _read_required(path: Path) -> str:
    """Read a schema file that must exist; missing raises ``FileNotFoundError``."""
    text = _read_optional(path)
    if text is None:
        raise FileNotFoundError(f"host context file missing: {path}")
    return text


def _read_optional(path: Path) -> str | None:
    """Read a schema file that must be a regular file; ``None`` if absent.

    ``lstat`` sees a symlink as itself (dangling or not), so a symlink, a
    directory, a FIFO or any other non-regular entry at ``path`` raises
    ``RuntimeError`` instead of being read through. The threat is repo
    content, not a writer racing the read, so a stat-then-read is enough.
    """
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(mode):
        raise RuntimeError(
            f"host context file is a symlink; refusing to follow it: {path}"
        )
    if not stat.S_ISREG(mode):
        raise RuntimeError(
            f"host context file is not a regular file ({stat.filemode(mode)}): {path}"
        )
    return path.read_text(encoding="utf-8")
