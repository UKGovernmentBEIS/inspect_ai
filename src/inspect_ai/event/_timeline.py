"""Timeline: hierarchical structure for visualization and scanning.

Transforms flat event streams into a semantic tree with agent-centric interpretation.

Uses inspect_ai's event_tree() to parse span structure.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Annotated, Any, AsyncIterator, Callable, Literal, Sequence

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
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)

from ._branch import BranchEvent
from ._event import Event
from ._model import ModelEvent
from ._tool import ToolEvent
from ._tree import EventTreeSpan, event_sequence, event_tree

# Type alias for tree items returned by event_tree
TreeItem = EventTreeSpan | Event


# =============================================================================
# Node Types
# =============================================================================


def _min_start_time(
    nodes: Sequence[TimelineEvent | TimelineSpan],
) -> datetime:
    """Return the earliest start time among nodes.

    Args:
        nodes: Sequence of nodes to check.

    Returns:
        The minimum start_time, or ``datetime.max`` if empty (so empty
        spans sort last and ``min()`` callers don't crash).
    """
    return min((node.start_time() for node in nodes), default=datetime.max)


def _max_end_time(
    nodes: Sequence[TimelineEvent | TimelineSpan],
) -> datetime:
    """Return the latest end time among nodes.

    Requires at least one node (all nodes have non-null end_time).

    Args:
        nodes: Non-empty sequence of nodes to check.

    Returns:
        The maximum end_time.
    """
    return max(node.end_time() for node in nodes)


def _sum_tokens(
    nodes: Sequence[TimelineEvent | TimelineSpan],
) -> int:
    """Sum total tokens across all nodes.

    Args:
        nodes: Sequence of nodes to sum.

    Returns:
        Total token count from all nodes.
    """
    return sum(node.total_tokens() for node in nodes)


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

    def start_time(self) -> datetime:
        """Event timestamp (required field on all events)."""
        return self.event.timestamp

    def end_time(self) -> datetime:
        """Event completion time if available, else timestamp."""
        if isinstance(self.event, (ModelEvent, ToolEvent)):
            if self.event.completed is not None:
                return self.event.completed
        return self.start_time()

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

    def idle_time(self) -> float:
        """Seconds of idle time (always 0 for a single event)."""
        return 0.0


_IDLE_THRESHOLD_SECS = 300.0  # 5 minutes


def _compute_idle_time(
    content: Sequence[TimelineEvent | TimelineSpan],
    start_time: datetime,
    end_time: datetime,
) -> float:
    """Compute idle time using gap-based detection between children.

    Any gap > 5 min between consecutive children (sorted by start_time)
    is counted as idle. Children's own idle_time is summed recursively.

    Args:
        content: Child nodes of the span.
        start_time: Span start time.
        end_time: Span end time.

    Returns:
        Idle time in seconds (>= 0).
    """
    if not content:
        return 0.0

    sorted_children = sorted(content, key=lambda c: c.start_time())
    idle = sum(child.idle_time() for child in sorted_children)

    # Gap: span start → first child
    gap = (sorted_children[0].start_time() - start_time).total_seconds()
    if gap > _IDLE_THRESHOLD_SECS:
        idle += gap

    # Gaps between consecutive children
    for i in range(1, len(sorted_children)):
        gap = (
            sorted_children[i].start_time() - sorted_children[i - 1].end_time()
        ).total_seconds()
        if gap > _IDLE_THRESHOLD_SECS:
            idle += gap

    # Gap: last child → span end
    gap = (end_time - sorted_children[-1].end_time()).total_seconds()
    if gap > _IDLE_THRESHOLD_SECS:
        idle += gap

    return max(0.0, idle)


def _timeline_content_discriminator(v: Any) -> str:
    """Discriminator function for TimelineSpan.content and TimelineSpan.content."""
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
    branches: list["TimelineSpan"] = Field(default_factory=list)
    branched_from: str | None = Field(default=None)
    description: str | None = None
    utility: bool = False
    tool_invoked: bool = False
    """True if this agent span was invoked as a tool (via task/as_tool/handoff).

    Tool-invoked subagents are explicit user-intended sub-trajectories and
    are never classified as `utility` regardless of turn count or prompt
    differences. The `_classify_utility_agents` heuristic targets internal
    helper model calls, not explicit subagent invocations.
    """
    agent_result: str | None = None
    outline: "Outline | None" = None

    @model_validator(mode="after")
    def _lowercase_name(self) -> "TimelineSpan":
        self.name = self.name.lower()
        return self

    def _content_and_branches(
        self,
    ) -> list[TimelineEvent | TimelineSpan]:
        items: list[TimelineEvent | TimelineSpan] = list(self.content)
        items.extend(self.branches)
        return items

    def start_time(self, include_branches: bool = True) -> datetime:
        """Earliest start time among content (and optionally branches).

        Args:
            include_branches: Include branches in time calcluation.
        """
        items = self._content_and_branches() if include_branches else self.content
        return _min_start_time(items)

    def end_time(self, include_branches: bool = True) -> datetime:
        """Latest end time among content (and optionally branches).

        Args:
            include_branches: Include branches in time calcluation.
        """
        items = self._content_and_branches() if include_branches else self.content
        return _max_end_time(items)

    def total_tokens(self, include_branches: bool = True) -> int:
        """Sum of tokens from content (and optionally branches).

        Args:
            include_branches: Include branches in token calcluation.
        """
        items = self._content_and_branches() if include_branches else self.content
        return _sum_tokens(items)

    def idle_time(self, include_branches: bool = True) -> float:
        """Seconds of idle time within this span (and optionally branches).

        Args:
            include_branches: Include branches in time calcluation.
        """
        items = self._content_and_branches() if include_branches else self.content
        return _compute_idle_time(
            items, self.start_time(include_branches), self.end_time(include_branches)
        )


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
    """Serialize a Timeline to a JSON-compatible dict.

    Converts a Timeline into a plain dictionary suitable for JSON
    serialization. Event objects within the timeline are replaced by
    their UUIDs, keeping the serialized form compact and
    self-referencing.

    Args:
        timeline: The Timeline to serialize.

    Returns:
        A dict representation of the timeline, with events stored
        as UUID strings rather than full Event objects.
    """
    return timeline.model_dump()


def timeline_load(data: dict[str, Any], events: list[Event]) -> Timeline:
    """Deserialize a Timeline from a dict produced by `timeline_dump`.

    Reconstructs a full Timeline by resolving the UUID strings stored
    in `data` back to their corresponding Event objects from `events`.

    Args:
        data: A dict previously produced by `timeline_dump`.
        events: The flat list of Event objects whose UUIDs appear in
            `data`. Events without a UUID are ignored.

    Returns:
        A fully hydrated Timeline with Event references restored.
    """
    events_by_uuid = {e.uuid: e for e in events if e.uuid}
    return Timeline.model_validate(data, context={"events_by_uuid": events_by_uuid})


# =============================================================================
# Builder
# =============================================================================


def timeline_build(
    events: list[Event], *, name: str | None = None, description: str | None = None
) -> Timeline:
    """Build a Timeline from a flat event list.

    Transforms a flat event stream into a hierarchical ``Timeline`` tree
    with agent-centric interpretation. The pipeline has two phases:

    **Phase 1 — Structure extraction:**

    Uses ``event_tree()`` to parse span_begin/span_end events into a tree,
    then looks for top-level phase spans ("init", "solvers", "scorers"):

    - If present, partitions events into init (setup), agent (solvers),
      and scoring sections.
    - If absent, treats the entire event stream as the agent.

    **Phase 2 — Agent classification:**

    Within the agent section, spans are classified as agents or unrolled:

    ==============================  =======================================
    Span type                       Result
    ==============================  =======================================
    ``type="agent"``                ``TimelineSpan(span_type="agent")``
    ``type="solver"``               ``TimelineSpan(span_type="agent")``
    ``type="tool"`` + ModelEvents   ``TimelineSpan(span_type="agent")``
    ToolEvent with ``agent`` field  ``TimelineSpan(span_type="agent")``
    ``type="tool"`` (no models)     Unrolled into parent
    Any other span type             Unrolled into parent
    ==============================  =======================================

    "Unrolled" means the span wrapper is removed and its child events
    dissolve into the parent's content list.

    **Phase 3 — Post-processing passes:**

    - Auto-branch detection (re-rolled ModelEvents with identical inputs)
    - Utility agent classification (single-turn agents with different
      system prompts)
    - Recursive branch classification

    Args:
        events: Flat list of Events from a transcript.
        name: Optional name for timeline (defaults to "Default")
        description: Optional description for timeline (defaults to "")

    Returns:
        A Timeline with a hierarchical root TimelineSpan.
    """
    # provide defaults
    name = name or "Default"
    description = description or ""

    # no events
    if not events:
        return Timeline(
            name=name,
            description=description,
            root=TimelineSpan(id="root", name="main", span_type=None),
        )

    # Build branch span_id → from_span mapping for relocation
    from_spans = _build_from_spans(events)

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
                    name="init",
                    span_type="init",
                    content=init_content,
                )

        # Build agent node from solvers
        agent_node = (
            _build_agent_from_solvers_span(solvers_span) if solvers_span else None
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
                    name="scoring",
                    span_type="scorers",
                    content=scoring_content,
                )

        if agent_node is not None:
            agent_node.name = "main"

            _classify_spans(agent_node, from_spans)

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
                name="main",
                span_type=None,
                content=root_content,
            )
    else:
        # No phase spans - treat entire tree as agent
        root = _build_agent_from_tree(tree)
        _classify_spans(root, from_spans)

    return Timeline(name=name, description=description, root=root)


@contextlib.asynccontextmanager
async def timeline_branch(
    *, name: str, from_span: str, from_anchor: str, id: str | None = None
) -> AsyncIterator[None]:
    """Context manager for creating a timeline branch.

    Args:
        name (str): Name of branch span.
        from_span: Span where the branch originated.
        from_anchor: Anchor id at the branch point.
        id (str | None): Optional span ID. Generated if not provided.
    """
    from inspect_ai.event._branch import BranchEvent
    from inspect_ai.log._transcript import transcript
    from inspect_ai.util._span import span

    async with span(name=name, type="branch", id=id):
        transcript()._event(BranchEvent(from_span=from_span, from_anchor=from_anchor))
        yield


def _classify_spans(root: TimelineSpan, from_spans: dict[str, str]) -> None:
    """Run all span classification passes on a root span.

    Classifies utility agents, branch structure, and relocates branches.
    """
    _wrap_utility_events(root)
    _classify_utility_agents(root)
    _classify_branches(root)
    _relocate_branches(root, from_spans)
    _extract_agent_results(root)


def _unwrap_solver_span(span: EventTreeSpan) -> EventTreeSpan:
    """Unwrap a solver span that merely wraps a single agent child.

    If a solver-type span contains exactly one agent-type child span
    (and no other spans), replace it with that child. Repeats until
    no more unwrapping is possible.
    """
    while span.type == "solver":
        agent_children = [
            child
            for child in span.children
            if isinstance(child, EventTreeSpan) and child.type == "agent"
        ]
        if len(agent_children) != 1:
            break
        span = agent_children[0]
    return span


def _build_agent_from_solvers_span(
    solvers_span: EventTreeSpan,
) -> TimelineSpan | None:
    """Build agent hierarchy from the solvers span.

    Looks for explicit agent spans (type='agent') within the solvers span.
    If found, builds the agent tree from those spans. If not found, uses
    the solvers span itself as the agent container.

    Args:
        solvers_span: The top-level solvers EventTreeSpan.

    Returns:
        A TimelineSpan representing the agent hierarchy, or None if empty.
    """
    if not solvers_span.children:
        return None

    # Look for agent spans within solvers
    agent_spans: list[EventTreeSpan] = []
    other_items: list[TreeItem] = []

    for child in solvers_span.children:
        if isinstance(child, EventTreeSpan) and _is_agent_span(child):
            agent_spans.append(child)
        else:
            other_items.append(child)

    if agent_spans:
        # Build from explicit agent spans
        if len(agent_spans) == 1:
            # Unwrap solver spans that merely wrap a single agent child
            target = _unwrap_solver_span(agent_spans[0])
            return _build_span_from_agent_span(target, other_items)
        else:
            # Multiple agent spans - create root containing all
            children: list[TimelineEvent | TimelineSpan] = [
                _build_span_from_agent_span(span, []) for span in agent_spans
            ]
            # Add any orphan events
            for item in other_items:
                if isinstance(item, EventTreeSpan) and not _is_agent_span(item):
                    orphan_content: list[TimelineEvent | TimelineSpan] = []
                    _unroll_span(item, orphan_content)
                    for orphan in reversed(orphan_content):
                        children.insert(0, orphan)
                else:
                    children.insert(0, _tree_item_to_node(item))
            return TimelineSpan(
                id="root",
                name="main",
                span_type="agent",
                content=children,
            )
    else:
        # No explicit agent spans - use solvers span itself as the agent container
        content, branches = _process_children(solvers_span.children)

        return TimelineSpan(
            id=solvers_span.id,
            name=solvers_span.name,
            span_type="agent",
            content=content,
            branches=branches,
        )


def _build_span_from_agent_span(
    span: EventTreeSpan,
    extra_items: list[TreeItem] | None = None,
) -> TimelineSpan:
    """Build a TimelineSpan from a EventTreeSpan with type='agent'.

    Args:
        span: The agent EventTreeSpan to convert.
        extra_items: Additional tree items (orphan events) to include
            at the start of the span's content.

    Returns:
        A TimelineSpan with the span's children as content.
    """
    content: list[TimelineEvent | TimelineSpan] = []

    # Add any extra items first (orphan events)
    if extra_items:
        for item in extra_items:
            if isinstance(item, EventTreeSpan) and not _is_agent_span(item):
                _unroll_span(item, content)
            else:
                content.append(_tree_item_to_node(item))

    # Process span children with branch awareness
    child_content, branches = _process_children(span.children)
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


def _is_agent_span(span: EventTreeSpan) -> bool:
    """Check if an EventTreeSpan represents an agent trajectory.

    Agent spans are:
    - Explicit agent spans (type="agent")
    - Solver spans (type="solver")
    - Tool spans containing model events (tool-spawned agents)

    Args:
        span: The EventTreeSpan to check.

    Returns:
        True if the span represents an agent trajectory.
    """
    if span.type in ("agent", "solver"):
        return True
    if (
        span.type == "tool"
        and _contains_model_events(span)
        and not _contains_agent_span(span)
    ):
        return True
    return False


def _tree_item_to_node(
    item: TreeItem,
) -> TimelineEvent | TimelineSpan:
    """Convert a tree item (EventTreeSpan or Event) to a TimelineEvent or TimelineSpan.

    Dispatches to the appropriate builder based on item type:
    - EventTreeSpan with type='agent' or 'solver' -> _build_span_from_agent_span
    - Other EventTreeSpan (e.g., tool span with models) -> _build_span_from_generic_span
    - Event -> _event_to_node

    Args:
        item: A tree item from event_tree() (EventTreeSpan or Event).

    Returns:
        A TimelineEvent or TimelineSpan representing the item.
    """
    if isinstance(item, EventTreeSpan):
        if item.type in ("agent", "solver"):
            return _build_span_from_agent_span(item)
        else:
            return _build_span_from_generic_span(item)
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
            agent_result = _extract_tool_event_result(event.result)
            return TimelineSpan(
                id=f"tool-agent-{event.id}",
                name=agent_name,
                span_type="agent",
                content=nested_content,
                agent_result=agent_result,
                tool_invoked=True,
            )
    return TimelineEvent(event=event)


def _build_span_from_generic_span(
    span: EventTreeSpan,
) -> TimelineSpan:
    """Build a TimelineSpan from a non-agent EventTreeSpan.

    If the span is a tool span (type="tool") containing model events,
    we treat it as a tool-spawned agent (span_type="agent").
    """
    content, branches = _process_children(span.children)

    # Determine the span_type based on span type and content. A tool span
    # that recursively contains model events is treated as a tool-spawned
    # agent (e.g. bridge-style tools that emit raw model events). But if
    # the tool already wraps an explicit agent span, leave the
    # classification alone — the inner agent span represents the agent.
    span_type: str | None
    if (
        span.type == "tool"
        and _contains_model_events(span)
        and not _contains_agent_span(span)
    ):
        span_type = "agent"
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


def _contains_agent_span(span: EventTreeSpan) -> bool:
    """Check if a span has any descendant span with type='agent'.

    Used to suppress tool→agent classification when the tool already
    wraps an explicit agent span (which will represent the agent itself).
    """
    for child in span.children:
        if isinstance(child, EventTreeSpan):
            if child.type == "agent" or _contains_agent_span(child):
                return True
    return False


def _build_agent_from_tree(
    tree: list[TreeItem],
) -> TimelineSpan:
    """Build agent from a list of tree items when no explicit phase spans exist.

    Creates a synthetic "main" agent containing all tree items as content.

    Args:
        tree: List of tree items from event_tree().

    Returns:
        A TimelineSpan with id="main" containing all items.
    """
    content, branches = _process_children(tree)

    return TimelineSpan(
        id="main",
        name="main",
        span_type="agent",
        content=content,
        branches=branches,
    )


# =============================================================================
# TimelineSpan Processing
# =============================================================================


def _unroll_span(
    span: EventTreeSpan,
    into: list[TimelineEvent | TimelineSpan],
) -> None:
    """Dissolve a non-agent span, emitting its begin/end as regular events.

    Recursively unrolls nested non-agent spans while preserving any
    nested agent spans as TimelineSpan nodes.

    Args:
        span: The non-agent EventTreeSpan to unroll.
        into: The content list to append results to.
    """
    # Emit span begin event
    into.append(TimelineEvent(event=span.begin))

    # An agent span discovered as a direct child of a tool span being
    # unrolled was invoked as a tool (task/as_tool/handoff). Mark it so
    # _classify_utility_agents leaves it alone — tool-invoked subagents
    # are explicit user intent, not internal helper calls.
    parent_is_tool = span.type == "tool"

    # Process children: recurse into non-agent spans, keep agent spans
    for child in span.children:
        if isinstance(child, EventTreeSpan):
            if _is_agent_span(child):
                node = _tree_item_to_node(child)
                if isinstance(node, TimelineSpan) and not node.content:
                    pass  # skip empty agent spans
                else:
                    if parent_is_tool and isinstance(node, TimelineSpan):
                        node.tool_invoked = True
                    into.append(node)
            else:
                _unroll_span(child, into)
        else:
            into.append(_event_to_node(child))

    # Emit span end event
    if span.end:
        into.append(TimelineEvent(event=span.end))


def _process_children(
    children: list[TreeItem],
    from_spans: dict[str, str] | None = None,
) -> tuple[list[TimelineEvent | TimelineSpan], list[TimelineSpan]]:
    """Process a span's children with branch awareness.

    Collects adjacent type="branch" EventTreeSpan runs and builds
    branch TimelineSpan objects from those that contain a BranchEvent.
    Branch spans without a BranchEvent are processed as normal content.

    Args:
        children: List of tree items to process.
        from_spans: Optional dict to accumulate branch span_id → from_span
            mappings for later relocation.

    Returns:
        Tuple of (content nodes, branch list).
    """
    content: list[TimelineEvent | TimelineSpan] = []
    branches: list[TimelineSpan] = []
    branch_run: list[EventTreeSpan] = []

    def _flush_branch_run(
        branch_run: list[EventTreeSpan],
        parent_content: list[TimelineEvent | TimelineSpan],
    ) -> list[TimelineSpan]:
        """Convert accumulated branch spans into branch TimelineSpan objects.

        Branch spans that contain a BranchEvent are converted to TimelineSpan
        with span_type="branch". Those without a BranchEvent have their
        content merged into parent_content.
        """
        result: list[TimelineSpan] = []
        for span in branch_run:
            branch_event = _find_branch_event(span)
            if branch_event is None:
                # No BranchEvent — process as normal content
                _process_span_as_content(span, parent_content)
                continue
            branch_content: list[TimelineEvent | TimelineSpan] = []
            for child in span.children:
                if isinstance(child, EventTreeSpan) and not _is_agent_span(child):
                    _unroll_span(child, branch_content)
                else:
                    node = _tree_item_to_node(child)
                    if isinstance(node, TimelineSpan) and not node.content:
                        continue
                    branch_content.append(node)
            if not branch_content:
                continue
            if from_spans is not None:
                from_spans[span.id] = branch_event.from_span
            result.append(
                TimelineSpan(
                    id=span.id,
                    name=span.name or "branch",
                    span_type="branch",
                    branched_from=branch_event.from_anchor,
                    content=branch_content,
                )
            )
        return result

    for item in children:
        if isinstance(item, EventTreeSpan) and item.type == "branch":
            branch_run.append(item)
        else:
            if branch_run:
                branches.extend(_flush_branch_run(branch_run, content))
                branch_run = []
            if isinstance(item, EventTreeSpan) and not _is_agent_span(item):
                # Unroll: dissolve non-agent span wrapper into parent
                _unroll_span(item, content)
            else:
                node = _tree_item_to_node(item)
                if isinstance(node, TimelineSpan) and not node.content:
                    continue
                content.append(node)

    if branch_run:
        branches.extend(_flush_branch_run(branch_run, content))

    return content, branches


def _find_branch_event(span: EventTreeSpan) -> BranchEvent | None:
    """Find a BranchEvent in a branch span's direct children.

    Args:
        span: The branch EventTreeSpan to search.

    Returns:
        The BranchEvent if found, None otherwise.
    """
    for child in span.children:
        if isinstance(child, BranchEvent):
            return child
    return None


def _process_span_as_content(
    span: EventTreeSpan,
    into: list[TimelineEvent | TimelineSpan],
) -> None:
    """Process a branch span as normal content when it has no BranchEvent.

    Args:
        span: The branch span to process.
        into: The content list to append results to.
    """
    for child in span.children:
        if isinstance(child, EventTreeSpan) and not _is_agent_span(child):
            _unroll_span(child, into)
        else:
            node = _tree_item_to_node(child)
            if isinstance(node, TimelineSpan) and not node.content:
                continue
            into.append(node)


def _classify_branches(agent: TimelineSpan) -> None:
    """Recursively classify branches in the agent tree.

    Recurses into child spans in both content and branches.

    Args:
        agent: The span node to process.
    """
    # Recurse into child spans in content
    for item in agent.content:
        if isinstance(item, TimelineSpan):
            _classify_branches(item)

    # Recurse into spans within branches
    for branch in agent.branches:
        for item in branch.content:
            if isinstance(item, TimelineSpan):
                _classify_branches(item)


# =============================================================================
# Branch Relocation
# =============================================================================


def _build_from_spans(events: Sequence[Event]) -> dict[str, str]:
    """Build branch span_id → from_span mapping from BranchEvents.

    Each BranchEvent's span_id identifies the branch span it belongs to,
    and from_span identifies the span it was forked from.

    Args:
        events: Flat list of Events from a transcript.

    Returns:
        Dict mapping branch span_id to the from_span value.
    """
    from_spans: dict[str, str] = {}
    for e in events:
        if isinstance(e, BranchEvent) and e.span_id:
            from_spans[e.span_id] = e.from_span
    return from_spans


def _collect_spans(span: TimelineSpan, span_map: dict[str, TimelineSpan]) -> None:
    """Recursively collect all TimelineSpans into a span_id → span map."""
    span_map[span.id] = span
    for item in span.content:
        if isinstance(item, TimelineSpan):
            _collect_spans(item, span_map)
    for branch in span.branches:
        _collect_spans(branch, span_map)


def _relocate_branches(root: TimelineSpan, from_spans: dict[str, str]) -> None:
    """Relocate branches to the span identified by from_span.

    After initial discovery, all branches from the same _process_children
    call are flat siblings. If a branch's from_span points to a span
    inside a sibling branch, move it there.

    Args:
        root: The root TimelineSpan to process.
        from_spans: Mapping of branch span_id → from_span (target span_id).
    """
    if not from_spans:
        return

    # Build span_id → TimelineSpan map from entire tree
    span_map: dict[str, TimelineSpan] = {}
    _collect_spans(root, span_map)

    # Relocate branches depth-first
    _do_relocate(root, span_map, from_spans)


def _do_relocate(
    span: TimelineSpan,
    span_map: dict[str, TimelineSpan],
    from_spans: dict[str, str],
) -> None:
    """Recursively relocate branches in a span and its children."""
    # Recurse into child spans first (depth-first)
    for item in span.content:
        if isinstance(item, TimelineSpan):
            _do_relocate(item, span_map, from_spans)
    for branch in span.branches:
        _do_relocate(branch, span_map, from_spans)

    # Check each branch's from_span and relocate if needed
    remaining: list[TimelineSpan] = []
    for branch in span.branches:
        target_id = from_spans.get(branch.id)
        target_span = span_map.get(target_id) if target_id else None
        if target_span is not None and target_span is not span:
            # Move branch to the target span
            target_span.branches.append(branch)
        else:
            remaining.append(branch)
    span.branches = remaining


# =============================================================================
# Agent Result Extraction
# =============================================================================


def _extract_tool_event_result(result: Any) -> str | None:
    """Extract a string result from a ToolEvent result field."""
    if isinstance(result, str) and result:
        return result
    if isinstance(result, list):
        parts: list[str] = []
        for item in result:
            if isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
            elif hasattr(item, "text"):
                parts.append(item.text)
        return "\n".join(parts) if parts else None
    return None


def _extract_agent_results(parent: TimelineSpan) -> None:
    """Extract agent_result for each agent sub-span.

    Three sources (checked in order):
    1. Tool-spawned agents: result already set during _event_to_node
    2. Span-based agents (static flow): sibling ToolEvent with agent_span_id == span.id
    3. Bridge flow: next ModelEvent's input has ChatMessageTool with function == span.name
    """
    content = parent.content
    for i, item in enumerate(content):
        if not isinstance(item, TimelineSpan):
            continue
        if item.span_type != "agent":
            # Recurse into non-agent spans
            _extract_agent_results(item)
            continue

        # Skip if already set (e.g. from tool-spawned agent construction)
        if item.agent_result is not None:
            _extract_agent_results(item)
            continue

        # Flow 1: sibling ToolEvent with agent_span_id matching this span
        for sibling in content:
            if (
                isinstance(sibling, TimelineEvent)
                and isinstance(sibling.event, ToolEvent)
                and sibling.event.agent_span_id == item.id
            ):
                result_text = _extract_tool_event_result(sibling.event.result)
                if result_text:
                    item.agent_result = result_text
                break

        # Flow 2: next model event's input has ChatMessageTool with matching tool_call_id
        # The span ID follows the pattern "agent-{tool_call_id}" in bridge flow.
        tool_call_id = item.id[6:] if item.id.startswith("agent-") else None

        if item.agent_result is None and tool_call_id:
            for j in range(i + 1, len(content)):
                next_item = content[j]
                if not isinstance(next_item, TimelineEvent):
                    continue
                if isinstance(next_item.event, ModelEvent):
                    for msg in next_item.event.input:
                        if (
                            isinstance(msg, ChatMessageTool)
                            and msg.tool_call_id == tool_call_id
                        ):
                            if msg.text:
                                item.agent_result = msg.text
                    if item.agent_result is not None:
                        break

        # Recurse into child spans
        _extract_agent_results(item)


# =============================================================================
# Utility Event Wrapping (bridge-based agents)
# =============================================================================


def _normalize_system_prompt(prompt: str) -> str:
    """Strip the per-call billing header from a system prompt.

    Claude Code prepends a line like ``x-anthropic-billing-header: ...``
    with a varying ``cch=`` hash.  Removing it lets us compare prompts
    across calls.

    Args:
        prompt: Raw system prompt text.

    Returns:
        The prompt with the first line removed when it starts with
        ``x-anthropic-billing-header:``, otherwise unchanged.
    """
    if prompt.startswith("x-anthropic-billing-header:"):
        # Strip the first line (including the newline)
        idx = prompt.find("\n")
        if idx != -1:
            return prompt[idx + 1 :]
        return ""  # prompt was only the header line
    return prompt


def _get_system_prompt_for_event(event: ModelEvent) -> str | None:
    """Extract and normalize the system prompt from a single ModelEvent.

    Args:
        event: The ModelEvent to inspect.

    Returns:
        The normalized system prompt text, or None if no system message found.
    """
    for msg in event.input:
        if isinstance(msg, ChatMessageSystem):
            if isinstance(msg.content, str):
                return _normalize_system_prompt(msg.content)
            parts = [c.text for c in msg.content if hasattr(c, "text")]
            raw = "\n".join(parts) if parts else None
            return _normalize_system_prompt(raw) if raw else None
    return None


def _has_tool_calls(event: ModelEvent) -> bool:
    """Check whether a ModelEvent's output contains tool calls."""
    if event.output.choices:
        msg = event.output.choices[0].message
        if msg.tool_calls:
            return True
    return False


def _wrap_utility_events(agent: TimelineSpan) -> None:
    """Wrap foreign-prompt model calls as synthetic utility spans.

    Within bridge-based agent spans (e.g. Claude Code), short extraction
    model calls use a different system prompt and produce no tool calls.
    This function detects them and wraps each one in a ``TimelineSpan``
    with ``utility=True`` so downstream code treats them as utility agents.

    Operates recursively on the entire span tree.

    Args:
        agent: The span node to process (mutated in place).
    """
    # --- Determine the primary system prompt for this span ---
    primary_prompt: str | None = None

    # Prefer the prompt of the first ModelEvent that has tool calls
    for item in agent.content:
        if isinstance(item, TimelineEvent) and isinstance(item.event, ModelEvent):
            if _has_tool_calls(item.event):
                primary_prompt = _get_system_prompt_for_event(item.event)
                break

    # Fall back to the first ModelEvent's prompt
    if primary_prompt is None:
        for item in agent.content:
            if isinstance(item, TimelineEvent) and isinstance(item.event, ModelEvent):
                primary_prompt = _get_system_prompt_for_event(item.event)
                break

    # No ModelEvents at all → nothing to wrap
    if primary_prompt is None:
        # Still recurse into child spans
        for item in agent.content:
            if isinstance(item, TimelineSpan):
                _wrap_utility_events(item)
        for branch in agent.branches:
            for item in branch.content:
                if isinstance(item, TimelineSpan):
                    _wrap_utility_events(item)
        return

    # --- Scan and wrap utility candidates ---
    new_content: list[TimelineEvent | TimelineSpan] = []
    for item in agent.content:
        if isinstance(item, TimelineEvent) and isinstance(item.event, ModelEvent):
            # Warmup/cache-priming call (max_tokens=1)
            if _is_warmup_call(item.event):
                wrapper = TimelineSpan(
                    id=f"utility-{item.event.uuid or id(item)}",
                    name="utility",
                    span_type="agent",
                    content=[item],
                )
                wrapper.utility = True
                new_content.append(wrapper)
                continue

            evt_prompt = _get_system_prompt_for_event(item.event)
            if (
                evt_prompt is not None
                and evt_prompt != primary_prompt
                and not _has_tool_calls(item.event)
            ):
                # Wrap in a synthetic utility span
                wrapper = TimelineSpan(
                    id=f"utility-{item.event.uuid or id(item)}",
                    name="utility",
                    span_type="agent",
                    content=[item],
                )
                wrapper.utility = True
                new_content.append(wrapper)
                continue
        new_content.append(item)

    agent.content = new_content

    # --- Recurse into child spans and branches ---
    for item in agent.content:
        if isinstance(item, TimelineSpan):
            _wrap_utility_events(item)
    for branch in agent.branches:
        for item in branch.content:
            if isinstance(item, TimelineSpan):
                _wrap_utility_events(item)


def _is_warmup_call(event: ModelEvent) -> bool:
    """Detect cache-priming warmup calls (max_tokens=1, single-word user prompt)."""
    if event.config.max_tokens is None or event.config.max_tokens > 1:
        return False
    # Check that the last user message is a single word
    for msg in reversed(event.input):
        if isinstance(msg, ChatMessageUser):
            if isinstance(msg.content, str):
                return len(msg.content.split()) <= 1
            return False
    return False


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

    # Classify this node (root agent is never utility). Tool-invoked
    # subagents (task/as_tool/handoff) are explicit user-intended
    # sub-trajectories — never utility — even if single-turn. Foreign-prompt
    # helper model calls are handled separately by _wrap_utility_events.
    if (
        parent_system_prompt is not None
        and agent_system_prompt is not None
        and not node.tool_invoked
    ):
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
