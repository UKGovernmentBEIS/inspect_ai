"""Timeline: hierarchical structure for visualization and scanning.

Transforms flat event streams into a semantic tree with agent-centric interpretation.

Uses inspect_ai's event_tree() to parse span structure.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any, Callable, Literal

from pydantic import (
    BaseModel,
    Discriminator,
    Field,
    Tag,
    ValidationInfo,
    field_serializer,
    model_validator,
)

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
)

from ._event import Event
from ._model import ModelEvent
from ._span import SpanBeginEvent
from ._tool import ToolEvent
from ._tree import EventTreeSpan, event_sequence, event_tree

# Type alias for tree items returned by event_tree
TreeItem = EventTreeSpan | Event


# =============================================================================
# Node Types
# =============================================================================


def _min_start_time(
    nodes: Sequence["TimelineEvent | TimelineSpan | TimelineBranch"],
) -> datetime:
    """Return the earliest start time among nodes.

    Requires at least one node (all nodes have non-null start_time).

    Args:
        nodes: Non-empty sequence of nodes to check.

    Returns:
        The minimum start_time.
    """
    return min(node.start_time for node in nodes)


def _max_end_time(
    nodes: Sequence["TimelineEvent | TimelineSpan | TimelineBranch"],
) -> datetime:
    """Return the latest end time among nodes.

    Requires at least one node (all nodes have non-null end_time).

    Args:
        nodes: Non-empty sequence of nodes to check.

    Returns:
        The maximum end_time.
    """
    return max(node.end_time for node in nodes)


def _sum_tokens(
    nodes: Sequence["TimelineEvent | TimelineSpan | TimelineBranch"],
) -> int:
    """Sum total tokens across all nodes.

    Args:
        nodes: Sequence of nodes to sum.

    Returns:
        Total token count from all nodes.
    """
    return sum(node.total_tokens for node in nodes)


class TimelineEvent(BaseModel):
    """Wraps a single Event."""

    type: Literal["event"] = "event"
    event: Event

    @field_serializer("event")
    def _serialize_event(self, event: Event, _info: Any) -> str:
        """Serialize event as its UUID for storage."""
        return event.uuid or ""

    @model_validator(mode="before")
    @classmethod
    def _resolve_event(cls, data: Any, info: ValidationInfo) -> Any:
        """Resolve event UUID string to Event object via validation context."""
        if isinstance(data, dict):
            event_val = data.get("event")
            if isinstance(event_val, str):
                # Resolve UUID → Event via context
                ctx = info.context or {} if info else {}
                events_by_uuid = ctx.get("events_by_uuid", {})
                resolved = events_by_uuid.get(event_val)
                if resolved is not None:
                    data = {**data, "event": resolved}
            return data
        return data

    @property
    def start_time(self) -> datetime:
        """Event timestamp (required field on all events)."""
        return self.event.timestamp

    @property
    def end_time(self) -> datetime:
        """Event completion time if available, else timestamp."""
        if isinstance(self.event, (ModelEvent, ToolEvent)):
            if self.event.completed is not None:
                return self.event.completed
        return self.start_time

    @property
    def total_tokens(self) -> int:
        """Tokens from this event (ModelEvent only).

        Includes input_tokens_cache_read and input_tokens_cache_write in
        the total, as these represent actual token consumption for any LLM
        system using prompt caching. The sum of all token fields provides
        an accurate measure of total context window usage across all sources.
        """
        if isinstance(self.event, ModelEvent):
            usage = self.event.output.usage
            if usage is not None:
                input_tokens = usage.input_tokens or 0
                cache_read = usage.input_tokens_cache_read or 0
                cache_write = usage.input_tokens_cache_write or 0
                output_tokens = usage.output_tokens or 0
                return input_tokens + cache_read + cache_write + output_tokens
        return 0


def _timeline_content_discriminator(v: Any) -> str:
    """Discriminator function for TimelineSpan.content and TimelineBranch.content."""
    if isinstance(v, dict):
        return str(v.get("type", "event"))
    return str(getattr(v, "type", "event"))


# Discriminated union type for content items
TimelineContentItem = Annotated[
    Annotated[TimelineEvent, Tag("event")] | Annotated["TimelineSpan", Tag("span")],
    Discriminator(_timeline_content_discriminator),
]


class TimelineSpan(BaseModel):
    """A span of execution — agent, scorer, tool, or root."""

    type: Literal["span"] = "span"
    id: str
    name: str
    span_type: str | None
    content: list[TimelineContentItem] = Field(default_factory=list)
    branches: list["TimelineBranch"] = Field(default_factory=list)
    description: str | None = None
    utility: bool = False
    outline: "Outline | None" = None

    @property
    def start_time(self) -> datetime:
        """Earliest start time among content."""
        return _min_start_time(self.content)

    @property
    def end_time(self) -> datetime:
        """Latest end time among content."""
        return _max_end_time(self.content)

    @property
    def total_tokens(self) -> int:
        """Sum of tokens from all content."""
        return _sum_tokens(self.content)


class TimelineBranch(BaseModel):
    """A discarded alternative path from a branch point."""

    type: Literal["branch"] = "branch"
    forked_at: str
    content: list[TimelineContentItem] = Field(default_factory=list)

    @property
    def start_time(self) -> datetime:
        """Earliest start time among content."""
        return _min_start_time(self.content)

    @property
    def end_time(self) -> datetime:
        """Latest end time among content."""
        return _max_end_time(self.content)

    @property
    def total_tokens(self) -> int:
        """Sum of tokens from all content."""
        return _sum_tokens(self.content)


class OutlineNode(BaseModel):
    """A node in an agent's outline, referencing an event by UUID."""

    event: str
    children: list["OutlineNode"] = Field(default_factory=list)


class Outline(BaseModel):
    """Hierarchical outline of events for an agent."""

    nodes: list[OutlineNode] = Field(default_factory=list)


class Timeline(BaseModel):
    """A named timeline view over a transcript.

    Multiple timelines allow different interpretations of the same event
    stream — e.g. a default agent-centric view alongside an alternative
    grouping or filtered view.
    """

    name: str
    description: str
    root: TimelineSpan

    def __repr__(self) -> str:
        return self.render()

    def render(self, width: int | None = None) -> str:
        """Render an ASCII swimlane diagram of the timeline.

        Args:
            width: Total width of the output in characters. Defaults to 120.

        Returns:
            Multi-line string with the ASCII diagram.
        """
        from ._timeline_repr import render_timeline

        return render_timeline(self, width=width)


# =============================================================================
# Serialization
# =============================================================================


def timeline_dump(timeline: Timeline) -> dict[str, Any]:
    """Serialize a Timeline to a dict with event UUIDs."""
    return timeline.model_dump()


def timeline_load(data: dict[str, Any], events: list[Event]) -> Timeline:
    """Deserialize a Timeline dict, resolving event UUIDs to Event objects."""
    events_by_uuid = {e.uuid: e for e in events if e.uuid}
    return Timeline.model_validate(data, context={"events_by_uuid": events_by_uuid})


# =============================================================================
# Builder
# =============================================================================


def timeline_build(events: list[Event]) -> Timeline:
    """Build a Timeline from a flat event list.

    Uses inspect_ai's event_tree() to parse span structure, then:
    1. Look for top-level spans: "init", "solvers", "scorers"
    2. If present, use them to partition events into sections
    3. If not present, treat the entire event stream as the agent

    Agent detection within the solvers section (or entire stream):
    - Explicit agent spans (type='agent') -> span_type="agent"
    - Tool spans/calls with model events -> span_type=None (tool-spawned)
    """
    if not events:
        return Timeline(
            name="Default",
            description="",
            root=TimelineSpan(id="root", name="root", span_type=None),
        )

    # Detect explicit branches globally
    has_explicit_branches = any(
        isinstance(e, SpanBeginEvent) and e.type == "branch" for e in events
    )

    # Use event_tree to get hierarchical structure
    tree = event_tree(events)

    # Find top-level spans by name
    top_spans: dict[str, EventTreeSpan] = {}
    for item in tree:
        if isinstance(item, EventTreeSpan) and item.name in (
            "init",
            "solvers",
            "scorers",
        ):
            top_spans[item.name] = item

    # Check for explicit phase spans (init, solvers, or scorers)
    has_phase_spans = (
        "init" in top_spans or "solvers" in top_spans or "scorers" in top_spans
    )

    if has_phase_spans:
        # Use spans to partition events
        init_span = top_spans.get("init")
        solvers_span = top_spans.get("solvers")
        scorers_span = top_spans.get("scorers")

        # Build init span
        init_span_obj: TimelineSpan | None = None
        if init_span:
            flat_events = event_sequence(init_span.children)
            init_content: list[TimelineEvent | TimelineSpan] = [
                TimelineEvent(event=e) for e in flat_events
            ]
            if init_content:
                init_span_obj = TimelineSpan(
                    id=init_span.id,
                    name="Init",
                    span_type="init",
                    content=init_content,
                )

        # Build agent node from solvers
        agent_node = (
            _build_agent_from_solvers_span(solvers_span, has_explicit_branches)
            if solvers_span
            else None
        )

        # Build scoring span
        scoring_span: TimelineSpan | None = None
        if scorers_span:
            flat_events = event_sequence(scorers_span.children)
            scoring_content: list[TimelineEvent | TimelineSpan] = [
                TimelineEvent(event=e) for e in flat_events
            ]
            if scoring_content:
                scoring_span = TimelineSpan(
                    id=scorers_span.id,
                    name="Scoring",
                    span_type="scorers",
                    content=scoring_content,
                )

        if agent_node is not None:
            _classify_spans(agent_node, has_explicit_branches)

            # Prepend init span to agent content
            if init_span_obj:
                prepended: list[TimelineEvent | TimelineSpan] = [init_span_obj]
                agent_node.content = prepended + agent_node.content

            # Append scoring as a child span
            if scoring_span:
                agent_node.content.append(scoring_span)

            root = agent_node
        else:
            # No solvers span — build root from init + scoring
            root_content: list[TimelineEvent | TimelineSpan] = []
            if init_span_obj:
                root_content.append(init_span_obj)
            if scoring_span:
                root_content.append(scoring_span)
            root = TimelineSpan(
                id="root",
                name="root",
                span_type=None,
                content=root_content,
            )
    else:
        # No phase spans - treat entire tree as agent
        root = _build_agent_from_tree(tree, has_explicit_branches)
        _classify_spans(root, has_explicit_branches)

    return Timeline(name="Default", description="", root=root)


def _classify_spans(root: TimelineSpan, has_explicit_branches: bool) -> None:
    """Run all span classification passes on a root span.

    Detects auto-branches (unless explicit branches exist), classifies
    auto-spawned spans, utility agents, and branch structure.
    """
    if not has_explicit_branches:
        _detect_auto_branches(root)
    _classify_auto_spans(root)
    _classify_utility_agents(root)
    _classify_branches(root, has_explicit_branches)


def _build_agent_from_solvers_span(
    solvers_span: EventTreeSpan, has_explicit_branches: bool
) -> TimelineSpan | None:
    """Build agent hierarchy from the solvers span.

    Looks for explicit agent spans (type='agent') within the solvers span.
    If found, builds the agent tree from those spans. If not found, uses
    the solvers span itself as the agent container.

    Args:
        solvers_span: The top-level solvers EventTreeSpan.
        has_explicit_branches: Whether explicit branch spans exist globally.

    Returns:
        A TimelineSpan representing the agent hierarchy, or None if empty.
    """
    if not solvers_span.children:
        return None

    # Look for agent spans within solvers
    agent_spans: list[EventTreeSpan] = []
    other_items: list[TreeItem] = []

    for child in solvers_span.children:
        if isinstance(child, EventTreeSpan) and child.type == "agent":
            agent_spans.append(child)
        else:
            other_items.append(child)

    if agent_spans:
        # Build from explicit agent spans
        if len(agent_spans) == 1:
            return _build_span_from_agent_span(
                agent_spans[0], has_explicit_branches, other_items
            )
        else:
            # Multiple agent spans - create root containing all
            children: list[TimelineEvent | TimelineSpan] = [
                _build_span_from_agent_span(span, has_explicit_branches, [])
                for span in agent_spans
            ]
            # Add any orphan events
            for item in other_items:
                children.insert(0, _tree_item_to_node(item, has_explicit_branches))
            return TimelineSpan(
                id="root",
                name="root",
                span_type="agent",
                content=children,
            )
    else:
        # No explicit agent spans - use solvers span itself as the agent container
        content, branches = _process_children(
            solvers_span.children, has_explicit_branches
        )

        return TimelineSpan(
            id=solvers_span.id,
            name=solvers_span.name,
            span_type="agent",
            content=content,
            branches=branches,
        )


def _build_span_from_agent_span(
    span: EventTreeSpan,
    has_explicit_branches: bool,
    extra_items: list[TreeItem] | None = None,
) -> TimelineSpan:
    """Build a TimelineSpan from a EventTreeSpan with type='agent'.

    Args:
        span: The agent EventTreeSpan to convert.
        has_explicit_branches: Whether explicit branch spans exist globally.
        extra_items: Additional tree items (orphan events) to include
            at the start of the span's content.

    Returns:
        A TimelineSpan with the span's children as content.
    """
    content: list[TimelineEvent | TimelineSpan] = []

    # Add any extra items first (orphan events)
    if extra_items:
        for item in extra_items:
            content.append(_tree_item_to_node(item, has_explicit_branches))

    # Process span children with branch awareness
    child_content, branches = _process_children(span.children, has_explicit_branches)
    content.extend(child_content)

    description = (span.begin.metadata or {}).get("description") if span.begin else None

    return TimelineSpan(
        id=span.id,
        name=span.name,
        span_type="agent",
        content=content,
        branches=branches,
        description=description,
    )


def _tree_item_to_node(
    item: TreeItem, has_explicit_branches: bool
) -> TimelineEvent | TimelineSpan:
    """Convert a tree item (EventTreeSpan or Event) to a TimelineEvent or TimelineSpan.

    Dispatches to the appropriate builder based on item type:
    - EventTreeSpan with type='agent' -> _build_span_from_agent_span
    - Other EventTreeSpan -> _build_span_from_generic_span
    - Event -> _event_to_node

    Args:
        item: A tree item from event_tree() (EventTreeSpan or Event).
        has_explicit_branches: Whether explicit branch spans exist globally.

    Returns:
        A TimelineEvent or TimelineSpan representing the item.
    """
    if isinstance(item, EventTreeSpan):
        if item.type == "agent":
            return _build_span_from_agent_span(item, has_explicit_branches)
        else:
            return _build_span_from_generic_span(item, has_explicit_branches)
    else:
        return _event_to_node(item)


def _event_to_node(event: Event) -> TimelineEvent | TimelineSpan:
    """Convert an Event to a TimelineEvent or TimelineSpan.

    Handles ToolEvents that spawn nested agents, recursively processing
    nested events to detect further agent spawning.
    """
    if isinstance(event, ToolEvent):
        agent_name = event.agent
        nested_events = event.events
        if agent_name and nested_events:
            # Recursively process nested events to handle nested tool agents
            nested_content: list[TimelineEvent | TimelineSpan] = [
                _event_to_node(e) for e in nested_events
            ]
            return TimelineSpan(
                id=f"tool-agent-{event.id}",
                name=agent_name,
                span_type=None,
                content=nested_content,
            )
    return TimelineEvent(event=event)


def _build_span_from_generic_span(
    span: EventTreeSpan, has_explicit_branches: bool
) -> TimelineSpan:
    """Build a TimelineSpan from a non-agent EventTreeSpan.

    If the span is a tool span (type="tool") containing model events,
    we treat it as a tool-spawned agent (span_type=None).
    """
    content, branches = _process_children(span.children, has_explicit_branches)

    # Determine the span_type based on span type and content
    span_type: str | None
    if span.type == "tool" and _contains_model_events(span):
        span_type = None
    else:
        span_type = span.type

    return TimelineSpan(
        id=span.id,
        name=span.name,
        span_type=span_type,
        content=content,
        branches=branches,
    )


def _contains_model_events(span: EventTreeSpan) -> bool:
    """Check if a span contains any ModelEvent (recursively).

    Args:
        span: The EventTreeSpan to search.

    Returns:
        True if any descendant is a ModelEvent, False otherwise.
    """
    for child in span.children:
        if isinstance(child, EventTreeSpan):
            if _contains_model_events(child):
                return True
        elif isinstance(child, ModelEvent):
            return True
    return False


def _build_agent_from_tree(
    tree: list[TreeItem], has_explicit_branches: bool
) -> TimelineSpan:
    """Build agent from a list of tree items when no explicit phase spans exist.

    Creates a synthetic "main" agent containing all tree items as content.

    Args:
        tree: List of tree items from event_tree().
        has_explicit_branches: Whether explicit branch spans exist globally.

    Returns:
        A TimelineSpan with id="main" containing all items.
    """
    content, branches = _process_children(tree, has_explicit_branches)

    return TimelineSpan(
        id="main",
        name="main",
        span_type="agent",
        content=content,
        branches=branches,
    )


# =============================================================================
# TimelineBranch Processing
# =============================================================================


def _process_children(
    children: list[TreeItem], has_explicit_branches: bool
) -> tuple[list[TimelineEvent | TimelineSpan], list[TimelineBranch]]:
    """Process a span's children with branch awareness.

    When explicit branches are active, collects adjacent type="branch" EventTreeSpan
    runs and builds TimelineBranch objects from them. Otherwise, standard processing.

    Args:
        children: List of tree items to process.
        has_explicit_branches: Whether explicit branch spans exist globally.

    Returns:
        Tuple of (content nodes, branch list).
    """
    if not has_explicit_branches:
        # Standard processing - no branch detection at build time
        content: list[TimelineEvent | TimelineSpan] = []
        for item in children:
            node = _tree_item_to_node(item, has_explicit_branches)
            if isinstance(node, TimelineSpan) and not node.content:
                continue
            content.append(node)
        return content, []

    # Explicit branch mode: collect branch spans and build TimelineBranch objects
    content = []
    branches: list[TimelineBranch] = []
    branch_run: list[EventTreeSpan] = []

    def _flush_branch_run(
        branch_run: list[EventTreeSpan],
        parent_content: list[TimelineEvent | TimelineSpan],
    ) -> list[TimelineBranch]:
        """Convert accumulated branch spans into TimelineBranch objects."""
        result: list[TimelineBranch] = []
        for span in branch_run:
            branch_content: list[TimelineEvent | TimelineSpan] = []
            for child in span.children:
                node = _tree_item_to_node(child, has_explicit_branches)
                if isinstance(node, TimelineSpan) and not node.content:
                    continue
                branch_content.append(node)
            branch_input = _get_branch_input(branch_content)
            forked_at = (
                _find_forked_at(parent_content, branch_input)
                if branch_input is not None
                else ""
            )
            result.append(TimelineBranch(forked_at=forked_at, content=branch_content))
        return result

    for item in children:
        if isinstance(item, EventTreeSpan) and item.type == "branch":
            branch_run.append(item)
        else:
            if branch_run:
                branches.extend(_flush_branch_run(branch_run, content))
                branch_run = []
            node = _tree_item_to_node(item, has_explicit_branches)
            if isinstance(node, TimelineSpan) and not node.content:
                continue
            content.append(node)

    if branch_run:
        branches.extend(_flush_branch_run(branch_run, content))

    return content, branches


def _find_forked_at(
    agent_content: list[TimelineEvent | TimelineSpan],
    branch_input: list[ChatMessage],
) -> str:
    """Determine the fork point by matching the last shared input message.

    Examines the last message in branch_input and matches it back to an event
    in the parent's content.

    Args:
        agent_content: The parent agent's content list.
        branch_input: The shared input messages of the branching ModelEvent.

    Returns:
        UUID of the event at the fork point, or "" if at the beginning.
    """
    if not branch_input:
        return ""

    last_msg = branch_input[-1]

    if isinstance(last_msg, ChatMessageTool):
        # Match tool_call_id to a ToolEvent.id
        tool_call_id = last_msg.tool_call_id
        if tool_call_id:
            for item in agent_content:
                if (
                    isinstance(item, TimelineEvent)
                    and isinstance(item.event, ToolEvent)
                    and item.event.id == tool_call_id
                ):
                    return item.event.uuid or ""
        return ""

    if isinstance(last_msg, ChatMessageAssistant):
        # Match message id to ModelEvent.output.message.id
        msg_id = last_msg.id
        if msg_id:
            for item in agent_content:
                if isinstance(item, TimelineEvent) and isinstance(
                    item.event, ModelEvent
                ):
                    output = item.event.output
                    if output.choices:
                        out_msg = output.choices[0].message
                        if out_msg.id == msg_id:
                            return item.event.uuid or ""
        # Fallback: compare content
        msg_content = last_msg.content
        if msg_content:
            for item in agent_content:
                if isinstance(item, TimelineEvent) and isinstance(
                    item.event, ModelEvent
                ):
                    output = item.event.output
                    if output.choices:
                        out_msg = output.choices[0].message
                        if out_msg.content == msg_content:
                            return item.event.uuid or ""
        return ""

    # ChatMessageUser / ChatMessageSystem - fork at beginning
    return ""


def _get_branch_input(
    content: list[TimelineEvent | TimelineSpan],
) -> list[ChatMessage] | None:
    """Extract the input from the first ModelEvent in branch content.

    Args:
        content: The branch's content nodes.

    Returns:
        The input message list, or None if no ModelEvent found.
    """
    for item in content:
        if isinstance(item, TimelineEvent) and isinstance(item.event, ModelEvent):
            return list(item.event.input)
    return None


# =============================================================================
# TimelineBranch Auto-Detection
# =============================================================================


def _message_fingerprint(msg: ChatMessage, cache: dict[int, str] | None = None) -> str:
    """Compute a fingerprint for a single ChatMessage.

    Serializes role + content, ignoring auto-generated fields like id, source,
    metadata.

    Args:
        msg: The chat message to fingerprint.
        cache: Optional cache keyed by object id for repeated calls on the
            same message objects.

    Returns:
        SHA-256 hex digest of the message content.
    """
    if cache is not None:
        cached = cache.get(id(msg))
        if cached is not None:
            return cached

    role = msg.role
    content = msg.content
    if isinstance(content, str):
        serialized = content
    else:
        # Content is list of Content objects
        serialized = json.dumps(
            [c.model_dump(exclude_none=True) for c in content],
            sort_keys=True,
        )
    raw = f"{role}:{serialized}"
    result = hashlib.sha256(raw.encode()).hexdigest()

    if cache is not None:
        cache[id(msg)] = result
    return result


def _input_fingerprint(
    messages: list[ChatMessage], cache: dict[int, str] | None = None
) -> str:
    """Compute a fingerprint for a sequence of input messages.

    Args:
        messages: The input message list.
        cache: Optional cache keyed by object id, shared across calls
            to avoid re-hashing the same message objects.

    Returns:
        SHA-256 hex digest of the concatenated message fingerprints.
    """
    parts = [_message_fingerprint(m, cache) for m in messages]
    combined = "|".join(parts)
    return hashlib.sha256(combined.encode()).hexdigest()


def _detect_auto_branches(agent: TimelineSpan) -> None:
    """Detect re-rolled ModelEvents with identical inputs and create branches.

    For each group of ModelEvents with the same input fingerprint, the last
    one stays in content and earlier ones (plus their trailing events up to
    the next re-roll) become branches.

    CompactionEvents act as hard boundaries: fingerprint grouping is done
    independently within each region separated by compaction events, so
    re-rolls are never matched across a compaction boundary.

    Mutates agent in-place.

    Args:
        agent: The span node to process.
    """
    # Cache message fingerprints by object identity to avoid rehashing
    fp_cache: dict[int, str] = {}

    # Split content into regions at compaction boundaries
    regions: list[tuple[int, int]] = []
    region_start = 0
    for i, item in enumerate(agent.content):
        if isinstance(item, TimelineEvent) and item.event.event == "compaction":
            regions.append((region_start, i))
            region_start = i + 1
    regions.append((region_start, len(agent.content)))

    # Collect branch ranges across all regions
    branch_ranges: list[tuple[int, int, list[ChatMessage]]] = []

    for r_start, r_end in regions:
        # Find ModelEvent indices and their fingerprints within this region
        model_indices: list[tuple[int, str]] = []
        for i in range(r_start, r_end):
            item = agent.content[i]
            if isinstance(item, TimelineEvent) and isinstance(item.event, ModelEvent):
                input_msgs = list(item.event.input)
                if not input_msgs:
                    continue
                fp = _input_fingerprint(input_msgs, fp_cache)
                model_indices.append((i, fp))

        # Group by fingerprint within this region
        fingerprint_groups: dict[str, list[int]] = {}
        for idx, fp in model_indices:
            fingerprint_groups.setdefault(fp, []).append(idx)

        # Only process groups with duplicates
        for _fp, indices in fingerprint_groups.items():
            if len(indices) <= 1:
                continue

            first_idx = indices[0]
            first_item = agent.content[first_idx]
            assert isinstance(first_item, TimelineEvent) and isinstance(
                first_item.event, ModelEvent
            )
            shared_input = list(first_item.event.input)

            for i, branch_start in enumerate(indices[:-1]):
                next_reroll = indices[i + 1]
                branch_ranges.append((branch_start, next_reroll, shared_input))

    if not branch_ranges:
        return

    # Sort by start index descending so we can remove from the end first
    branch_ranges.sort(key=lambda x: x[0], reverse=True)

    for start, end, shared_input in branch_ranges:
        branch_content = list(agent.content[start:end])
        forked_at = _find_forked_at(agent.content, shared_input)
        agent.branches.append(
            TimelineBranch(forked_at=forked_at, content=branch_content)
        )
        del agent.content[start:end]

    # Reverse branches so they're in original order
    agent.branches.reverse()


def _classify_branches(
    agent: TimelineSpan, has_explicit_branches: bool, *, _is_root: bool = True
) -> None:
    """Recursively detect branches in the agent tree.

    If not in explicit mode, calls _detect_auto_branches on each agent.
    Always recurses into child spans in both content and branches.

    Args:
        agent: The span node to process.
        has_explicit_branches: Whether explicit branch spans exist globally.
        _is_root: Internal flag — skips root since _classify_spans already
            ran _detect_auto_branches on it before auto-span detection.
    """
    if not has_explicit_branches and not _is_root:
        _detect_auto_branches(agent)

    # Recurse into child spans in content
    for item in agent.content:
        if isinstance(item, TimelineSpan):
            _classify_branches(item, has_explicit_branches, _is_root=False)

    # Recurse into spans within branches
    for branch in agent.branches:
        for item in branch.content:
            if isinstance(item, TimelineSpan):
                _classify_branches(item, has_explicit_branches, _is_root=False)


# =============================================================================
# Auto-Span Detection (Conversation Threading)
# =============================================================================


def _get_last_assistant_message(
    input_msgs: list[ChatMessage],
) -> ChatMessageAssistant | None:
    """Extract the last assistant message from a ModelEvent's input.

    Args:
        input_msgs: The input message list.

    Returns:
        The last assistant message, or None if not found.
    """
    for msg in reversed(input_msgs):
        if isinstance(msg, ChatMessageAssistant):
            return msg
    return None


def _get_output_fingerprint(event: ModelEvent) -> str | None:
    """Fingerprint a ModelEvent's output message.

    Python output: event.output.choices[0].message (a ChatMessage).

    Args:
        event: The ModelEvent to fingerprint.

    Returns:
        The fingerprint string, or None if no output message.
    """
    output = event.output
    if not output.choices:
        return None
    return _message_fingerprint(output.choices[0].message)


def _system_prompt_fingerprint(input_msgs: list[ChatMessage]) -> str:
    """Fingerprint just the system prompt from a ModelEvent's input messages.

    Args:
        input_msgs: The input message list.

    Returns:
        Fingerprint of the system message, or empty string if none.
    """
    for msg in input_msgs:
        if isinstance(msg, ChatMessageSystem):
            return _message_fingerprint(msg)
    return ""


def _detect_auto_spans_for_span(span: TimelineSpan) -> None:
    """Detect conversation threads in a single flat span and create child spans.

    Uses conversation threading: tracks which ModelEvent inputs continue a prior
    ModelEvent's output via fingerprinting. Mutates span in-place.

    Args:
        span: The span node to process.
    """
    # Guard: only flat content (no child TimelineSpans)
    for item in span.content:
        if isinstance(item, TimelineSpan):
            return

    # Guard: need at least 2 ModelEvents with output fingerprints
    # (without output messages, threading detection cannot work)
    model_with_output_count = sum(
        1
        for item in span.content
        if isinstance(item, TimelineEvent)
        and isinstance(item.event, ModelEvent)
        and _get_output_fingerprint(item.event) is not None
    )
    if model_with_output_count < 2:
        return

    # Thread detection
    threads: list[
        dict[str, Any]
    ] = []  # Each: {"items": [...], "system_prompt_fp": str}
    output_fp_to_thread: dict[str, int] = {}  # output fingerprint → thread index
    compaction_continue_thread: int | None = None  # thread to continue after compaction
    preamble: list[TimelineEvent | TimelineSpan] = []

    for item in span.content:
        if isinstance(item, TimelineEvent) and isinstance(item.event, ModelEvent):
            input_msgs = list(item.event.input)
            if input_msgs:
                last_assistant = _get_last_assistant_message(input_msgs)
                if last_assistant is not None:
                    fp = _message_fingerprint(last_assistant)
                    thread_idx = output_fp_to_thread.get(fp)
                    if thread_idx is not None:
                        # Match — append to existing thread
                        threads[thread_idx]["items"].append(item)
                        # Update output tracking
                        del output_fp_to_thread[fp]
                        new_output_fp = _get_output_fingerprint(item.event)
                        if new_output_fp:
                            output_fp_to_thread[new_output_fp] = thread_idx
                        continue

            # Check compaction continuation: same system prompt → same agent
            sys_fp = _system_prompt_fingerprint(input_msgs)
            if compaction_continue_thread is not None:
                cont_fp = threads[compaction_continue_thread]["system_prompt_fp"]
                if sys_fp == cont_fp:
                    threads[compaction_continue_thread]["items"].append(item)
                    new_output_fp = _get_output_fingerprint(item.event)
                    if new_output_fp:
                        output_fp_to_thread[new_output_fp] = compaction_continue_thread
                    compaction_continue_thread = None
                    continue
                compaction_continue_thread = None

            # New thread
            threads.append({"items": [item], "system_prompt_fp": sys_fp})
            output_fp = _get_output_fingerprint(item.event)
            if output_fp:
                output_fp_to_thread[output_fp] = len(threads) - 1
        elif isinstance(item, TimelineEvent) and item.event.event == "compaction":
            # Hard boundary: reset fingerprint tracking but preserve continuity
            output_fp_to_thread.clear()
            if threads:
                threads[-1]["items"].append(item)
                compaction_continue_thread = len(threads) - 1
            else:
                preamble.append(item)
        else:
            # Non-model event
            if threads:
                threads[-1]["items"].append(item)
            else:
                preamble.append(item)

    # Only create structure if multiple threads found
    if len(threads) <= 1:
        return

    # Name threads by prompt group (ordered by first occurrence)
    prompt_group_order: list[str] = []
    prompt_group_threads: dict[str, list[int]] = {}
    for i, thread in enumerate(threads):
        fp = thread["system_prompt_fp"]
        if fp in prompt_group_threads:
            prompt_group_threads[fp].append(i)
        else:
            prompt_group_order.append(fp)
            prompt_group_threads[fp] = [i]

    name_map: dict[int, str] = {}
    group_num = 1
    for fp in prompt_group_order:
        thread_indices = prompt_group_threads[fp]
        base_name = "Agent" if len(prompt_group_order) == 1 else f"Agent {group_num}"
        for idx in thread_indices:
            name_map[idx] = base_name
        group_num += 1

    # Build child spans
    new_content: list[TimelineEvent | TimelineSpan] = list(preamble)
    for i, thread in enumerate(threads):
        child_span = TimelineSpan(
            id=f"auto-span-{i}",
            name=name_map[i],
            span_type=None,
            content=thread["items"],
        )
        new_content.append(child_span)

    span.content = new_content


def _classify_auto_spans(span: TimelineSpan) -> None:
    """Recursively detect auto-spans via conversation threading.

    Skips spans that already have child spans, recurses into children
    (including newly created ones).

    Args:
        span: The span node to process.
    """
    # Try detection on this span (only works if flat)
    _detect_auto_spans_for_span(span)

    # Recurse into any child spans (including newly created ones)
    for item in span.content:
        if isinstance(item, TimelineSpan):
            _classify_auto_spans(item)


# =============================================================================
# Utility Agent Classification
# =============================================================================


def _get_system_prompt(agent: TimelineSpan) -> str | None:
    """Extract system prompt from the first ModelEvent in agent's direct content.

    Args:
        agent: The span node to extract the system prompt from.

    Returns:
        The system prompt text, or None if no system message found.
    """
    for item in agent.content:
        if isinstance(item, TimelineEvent) and isinstance(item.event, ModelEvent):
            for msg in item.event.input:
                if isinstance(msg, ChatMessageSystem):
                    if isinstance(msg.content, str):
                        return msg.content
                    # Content is list of Content objects
                    parts = [c.text for c in msg.content if hasattr(c, "text")]
                    return "\n".join(parts) if parts else None
            return None  # ModelEvent found but no system message
    return None  # No ModelEvent found


def _is_single_turn(agent: TimelineSpan) -> bool:
    """Check if agent has a single turn or single tool-calling turn.

    A single turn is 1 ModelEvent with no ToolEvents.
    A single tool-calling turn is 2 ModelEvents with a ToolEvent between them.

    Args:
        agent: The span node to check.

    Returns:
        True if the agent matches the single-turn pattern.
    """
    # Collect direct events (not child spans) with their types
    direct_events: list[str] = []
    for item in agent.content:
        if isinstance(item, TimelineEvent):
            if isinstance(item.event, ModelEvent):
                direct_events.append("model")
            elif isinstance(item.event, ToolEvent):
                direct_events.append("tool")

    model_count = direct_events.count("model")
    tool_count = direct_events.count("tool")

    # Single turn: exactly 1 model event
    if model_count == 1:
        return True

    # Single tool-calling turn: 2 model events with tool event(s) between
    if model_count == 2 and tool_count >= 1:
        # Verify a tool event appears between the two model events
        first_model = direct_events.index("model")
        second_model = len(direct_events) - 1 - direct_events[::-1].index("model")
        between = direct_events[first_model + 1 : second_model]
        return "tool" in between

    return False


def _classify_utility_agents(
    node: TimelineSpan, parent_system_prompt: str | None = None
) -> None:
    """Classify utility agents in the tree via post-processing.

    An agent is utility if it has a single turn (or single tool-calling turn)
    and a different system prompt than its parent.

    Args:
        node: The span node to classify (and recurse into).
        parent_system_prompt: The system prompt of the parent agent.
    """
    agent_system_prompt = _get_system_prompt(node)

    # Classify this node (root agent is never utility)
    if parent_system_prompt is not None and agent_system_prompt is not None:
        if agent_system_prompt != parent_system_prompt and _is_single_turn(node):
            node.utility = True

    # Recurse into child spans
    effective_prompt = agent_system_prompt or parent_system_prompt
    for item in node.content:
        if isinstance(item, TimelineSpan):
            _classify_utility_agents(item, effective_prompt)


# =============================================================================
# Timeline Span Filtering
# =============================================================================


def timeline_filter(
    timeline: Timeline,
    predicate: Callable[[TimelineSpan], bool],
) -> Timeline:
    """Return a new timeline with only spans matching the predicate.

    Recursively walks the span tree, keeping ``TimelineSpan`` items
    where ``predicate(span)`` returns ``True``. Non-matching spans and
    their entire subtrees are pruned. ``TimelineEvent`` items are always
    kept (they belong to the parent span).

    Use this to pre-filter a timeline before passing it to
    ``timeline_messages()``.

    Args:
        timeline: The timeline to filter.
        predicate: Function that receives a ``TimelineSpan`` and returns
            ``True`` to keep it (and its subtree), ``False`` to prune it.

    Returns:
        A new ``Timeline`` with a filtered copy of the root.
    """
    return Timeline(
        name=timeline.name,
        description=timeline.description,
        root=_filter_span_by_predicate(timeline.root, predicate),
    )


def _filter_span_by_predicate(
    span: TimelineSpan,
    predicate: Callable[[TimelineSpan], bool],
) -> TimelineSpan:
    """Recursively filter a span's content, pruning non-matching child spans."""
    filtered_content: list[TimelineEvent | TimelineSpan] = []
    for item in span.content:
        if isinstance(item, TimelineSpan):
            if predicate(item):
                filtered_content.append(_filter_span_by_predicate(item, predicate))
        else:
            filtered_content.append(item)
    return span.model_copy(update={"content": filtered_content})
