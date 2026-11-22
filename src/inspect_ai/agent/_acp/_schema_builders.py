"""Builders for `acp.schema` models.

agent-client-protocol 1.0 removed `acp.helpers`. These functions replace the
helpers that Inspect used and keep their names, so one code path works with 0.12
and 1.0. They set each discriminator explicitly because 0.12 requires it and
1.0 sets a default.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from acp.schema import (
    AgentMessageChunk,
    AgentPlanContentUpdate,
    AgentPlanRemovedUpdate,
    AgentPlanUpdate,
    AgentThoughtChunk,
    AudioContentBlock,
    AvailableCommandsUpdate,
    ConfigOptionUpdate,
    ContentToolCallContent,
    CurrentModeUpdate,
    EmbeddedResourceContentBlock,
    FileEditToolCallContent,
    ImageContentBlock,
    PlanEntry,
    PlanEntryPriority,
    PlanEntryStatus,
    ResourceContentBlock,
    SessionInfoUpdate,
    SessionNotification,
    TerminalToolCallContent,
    TextContentBlock,
    ToolCallLocation,
    ToolCallProgress,
    ToolCallStart,
    ToolCallStatus,
    ToolKind,
    UsageUpdate,
    UserMessageChunk,
)

ContentBlock = (
    TextContentBlock
    | ImageContentBlock
    | AudioContentBlock
    | ResourceContentBlock
    | EmbeddedResourceContentBlock
)

SessionUpdate = (
    UserMessageChunk
    | AgentMessageChunk
    | AgentThoughtChunk
    | ToolCallStart
    | ToolCallProgress
    | AgentPlanUpdate
    | AgentPlanContentUpdate
    | AgentPlanRemovedUpdate
    | AvailableCommandsUpdate
    | CurrentModeUpdate
    | ConfigOptionUpdate
    | SessionInfoUpdate
    | UsageUpdate
)

ToolCallContentVariant = (
    ContentToolCallContent | FileEditToolCallContent | TerminalToolCallContent
)


def text_block(text: str) -> TextContentBlock:
    return TextContentBlock(type="text", text=text)


def tool_diff_content(
    path: str, new_text: str, old_text: str | None = None
) -> FileEditToolCallContent:
    return FileEditToolCallContent(
        type="diff", path=path, new_text=new_text, old_text=old_text
    )


def plan_entry(
    content: str,
    *,
    priority: PlanEntryPriority = "medium",
    status: PlanEntryStatus = "pending",
) -> PlanEntry:
    return PlanEntry(content=content, priority=priority, status=status)


def update_plan(entries: Iterable[PlanEntry]) -> AgentPlanUpdate:
    return AgentPlanUpdate(session_update="plan", entries=list(entries))


def update_agent_message(content: ContentBlock) -> AgentMessageChunk:
    return AgentMessageChunk(session_update="agent_message_chunk", content=content)


def session_notification(session_id: str, update: SessionUpdate) -> SessionNotification:
    return SessionNotification(session_id=session_id, update=update)


def start_tool_call(
    tool_call_id: str,
    title: str,
    *,
    kind: ToolKind | None = None,
    status: ToolCallStatus | None = None,
    content: Sequence[ToolCallContentVariant] | None = None,
    locations: Sequence[ToolCallLocation] | None = None,
    raw_input: Any = None,
    raw_output: Any = None,
) -> ToolCallStart:
    return ToolCallStart(
        session_update="tool_call",
        tool_call_id=tool_call_id,
        title=title,
        kind=kind,
        status=status,
        content=list(content) if content is not None else None,
        locations=list(locations) if locations is not None else None,
        raw_input=raw_input,
        raw_output=raw_output,
    )


def update_tool_call(
    tool_call_id: str,
    *,
    title: str | None = None,
    kind: ToolKind | None = None,
    status: ToolCallStatus | None = None,
    content: Sequence[ToolCallContentVariant] | None = None,
    locations: Sequence[ToolCallLocation] | None = None,
    raw_input: Any = None,
    raw_output: Any = None,
) -> ToolCallProgress:
    return ToolCallProgress(
        session_update="tool_call_update",
        tool_call_id=tool_call_id,
        title=title,
        kind=kind,
        status=status,
        content=list(content) if content is not None else None,
        locations=list(locations) if locations is not None else None,
        raw_input=raw_input,
        raw_output=raw_output,
    )
