"""Timeline: hierarchical structure for visualization and scanning.

Transforms flat event streams into a semantic tree with agent-centric interpretation.

Uses inspect_ai's event_tree() to parse span structure.
"""

from __future__ import annotations

import contextlib
from bisect import bisect_left, insort
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import (
    Annotated,
    Any,
    AsyncIterator,
    Callable,
    Literal,
    Mapping,
    NamedTuple,
    Sequence,
)

from pydantic import (
    BaseModel,
    Discriminator,
    Field,
    Tag,
    ValidationInfo,
    field_serializer,
    model_validator,
)

from inspect_ai._sentinel._scope import is_agent_turn
from inspect_ai._sentinel._steps import PoolView
from inspect_ai._util.hash import mm3_hash
from inspect_ai.model import (
    ChatMessage,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.util._span import AgentSpans

from ._anchor import AnchorEvent
from ._branch import BranchEvent
from ._compaction import CompactionEvent
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
    nodes: Sequence[TimelineEvent | TimelineSpan],
) -> datetime:
    """Return the earliest start time among nodes.

    Args:
        nodes: Sequence of nodes to check.

    Returns:
        The minimum start_time, or ``datetime.max`` if empty (so empty
        spans sort last and ``min()`` callers don't crash).
    """
    return min(
        (node.start_time() for node in nodes),
        default=datetime.max.replace(tzinfo=timezone.utc),
    )


def _max_end_time(
    nodes: Sequence[TimelineEvent | TimelineSpan],
) -> datetime:
    """Return the latest end time among nodes (``datetime.min`` when empty)."""
    return max(
        (node.end_time() for node in nodes),
        default=datetime.min.replace(tzinfo=timezone.utc),
    )


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
    span_type: str | None = None
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
    ``type="solver"`` wrapping agent ``TimelineSpan(span_type="agent")``
    ``type="solver"`` (primitive)   Unrolled into parent
    ``type="tool"`` + ModelEvents   ``TimelineSpan(span_type="agent")``
    ToolEvent with ``agent`` field  ``TimelineSpan(span_type="agent")``
    ``type="tool"`` (no models)     Unrolled into parent
    Any other span type             Unrolled into parent
    ==============================  =======================================

    "Unrolled" means the span wrapper is removed and its child events
    dissolve into the parent's content list.

    **Phase 3 — Post-processing passes:**

    - Utility agent classification (single-turn agents with different
      system prompts)

    Args:
        events: Flat list of Events from a transcript.
        name: Optional name for timeline (defaults to "Default")
        description: Optional description for timeline (defaults to "")

    Returns:
        A Timeline with a hierarchical root TimelineSpan.
    """
    return _timeline_build(events, name=name, description=description)


def _timeline_build(
    events: list[Event],
    *,
    name: str | None = None,
    description: str | None = None,
    message_pool: Sequence[ChatMessage] | None = None,
    final_messages: Sequence[ChatMessage] | None = None,
    conversations: Mapping[str, str] | None = None,
    continuity: bool = False,
) -> Timeline:
    """`timeline_build`, also over model inputs stored as ranges of a message pool (`input_refs`), as a log stores them.

    With `continuity` (replay's log driver, inferring the turns of a log that does not record ``origin``), the continuity rule decides which calls without an origin are turns (``_Continuity``); the public `timeline_build`, which the viewer and Scout use, keeps the prompt rules (decided by Charles 2026-10-26). `final_messages` are the main agent's final messages (`EvalSample.messages`), which settle a fork at the end of the main span. `conversations` gives the conversation of each event it names, by UUID, in place of its innermost agent span (a stored timeline's spans and branches, such as Petri's rollbacks), so continuity follows each apart.
    """
    # provide defaults
    name = name or "Default"
    description = description or ""
    inputs = _Inputs(events, message_pool, conversations)

    # no events
    if not events:
        return Timeline(
            name=name,
            description=description,
            root=TimelineSpan(id="root", name="main", span_type=None),
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

            _classify_spans(agent_node, inputs, final_messages, continuity)

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
        _classify_spans(root, inputs, final_messages, continuity)

    return Timeline(name=name, description=description, root=root)


@contextlib.asynccontextmanager
async def timeline_branch(
    *, name: str, from_anchor: str, id: str | None = None
) -> AsyncIterator[None]:
    """Context manager for creating a timeline branch.

    Emits an `AnchorEvent` in the current (parent) span so the viewer can resolve `from_anchor` to a position, then opens a ``type="branch"`` span and emits a `BranchEvent` inside it.

    Args:
        name (str): Name of branch span.
        from_anchor: Anchor id at the branch point.
        id (str | None): Optional span ID. Generated if not provided.
    """
    from inspect_ai.log._transcript import transcript
    from inspect_ai.util._span import span

    transcript()._event(AnchorEvent(anchor_id=from_anchor))
    async with span(name=name, type="branch", id=id):
        transcript()._event(BranchEvent(from_anchor=from_anchor))
        yield


def _classify_spans(
    root: TimelineSpan,
    inputs: _Inputs,
    final_messages: Sequence[ChatMessage] | None = None,
    continuity: bool = False,
) -> None:
    """Run all span classification passes on a root span.

    With `continuity`, agent results are extracted first, while every model call is still in its span's content: a result can reach only a call continuity then wraps as utility, such as a summary call just after the sub-agent finished.
    """
    if continuity:
        _extract_agent_results(root, inputs)
    _wrap_utility_events(root, inputs, final_messages, continuity)
    _classify_utility_agents(root, inputs)
    if not continuity:
        _extract_agent_results(root, inputs)


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
    - Solver spans that wrap a genuine agent (e.g. an @agent run via as_solver)
    - Tool spans containing model events (tool-spawned agents)

    Primitive solver spans (system_message, generate, use_tools, ...) wrap no
    agent of their own, so they are not agent trajectories — they get unrolled
    into their parent rather than occupying a swimlane.

    Args:
        span: The EventTreeSpan to check.

    Returns:
        True if the span represents an agent trajectory.
    """
    if span.type == "agent":
        return True
    if span.type == "solver":
        return _contains_agent_span(span)
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
) -> tuple[list[TimelineEvent | TimelineSpan], list[TimelineSpan]]:
    """Process a span's children with branch awareness.

    Collects adjacent type="branch" EventTreeSpan runs and builds
    branch TimelineSpan objects from those that contain a BranchEvent.
    Branch spans without a BranchEvent are processed as normal content.

    Args:
        children: List of tree items to process.

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


# =============================================================================
# Model Inputs
# =============================================================================


class _Fingerprint(NamedTuple):
    """A message as continuity matches it: its role, a hash of its text and the tool calls it makes, by id and function.

    Message ids do not survive a scaffold's round trip, so messages are matched by role and text, as the agent bridge matches them; tool call ids do, since a provider needs them to pair results with calls, and they tell apart turns that make calls with no text (fixture ``continuity_tool_call_ids``). So, unlike the bridge and the design's role and text, a scaffold that sends a tool call back under a new id does not continue the turn that made it (``continuity_renamed_tool_call_id``).
    """

    role: str
    text_hash: str
    calls: tuple[tuple[str, str], ...]


# an input's identity hashes its messages' fingerprints as a polynomial
# modulo this prime
_MODULUS = (1 << 61) - 1
_BASE = 0x9E3779B97F4A7C15 % _MODULUS


class _Inputs:
    """Model inputs as the classification passes read them.

    An input stored as ranges of the message pool (``input_refs``) is read as a view over the pool, so no input is expanded; each message is fingerprinted once, the first time it is compared.
    """

    def __init__(
        self,
        events: Sequence[Event],
        pool: Sequence[ChatMessage] | None,
        conversations: Mapping[str, str] | None = None,
    ) -> None:
        self._events = events
        self._pool = pool
        self._conversations = conversations or {}
        self._views: dict[int, Sequence[ChatMessage]] = {}
        self._fingerprints: dict[int, _Fingerprint] = {}
        # tool call id -> (the input position its result follows the call at,
        # the number of calls made with it), from the model call making it
        self._issued: dict[str, tuple[int, int]] | None = None
        # tool call id -> the pool rows answering it
        self._tool_rows: dict[str, list[int]] | None = None
        # message fingerprint -> the pool rows holding it
        self._rows_by_fingerprint: dict[_Fingerprint, list[int]] | None = None
        # message fingerprint -> its number in an input's identity; the hash
        # of the pool's first rows, by count, and the powers of _BASE
        self._codes: dict[_Fingerprint, int] = {}
        self._prefix: list[int] | None = None
        self._powers: list[int] = [1]
        self._agent_spans: AgentSpans | None = None

    def of(self, event: ModelEvent) -> Sequence[ChatMessage]:
        if event.input_refs is None or self._pool is None:
            return event.input
        found = self._views.get(id(event))
        if found is None:
            found = self._views[id(event)] = PoolView(self._pool, event.input_refs)
        return found

    def conversation(self, event: Event) -> object:
        """The conversation an event is in: the one given for its UUID, else its innermost agent span in the span tree."""
        given = self._conversations.get(event.uuid) if event.uuid else None
        if given is not None:
            return ("given", given)
        if self._agent_spans is None:
            self._agent_spans = AgentSpans()
            for begin in self._events:
                if isinstance(begin, SpanBeginEvent):
                    self._agent_spans.add(begin)
        try:
            return self._agent_spans.agent_span(event.span_id)
        except ValueError:
            # a parent_id cycle: its calls are taken as one conversation
            return None

    @property
    def pool_size(self) -> int:
        return len(self._pool) if self._pool is not None else 0

    def row(self, row: int) -> ChatMessage:
        assert self._pool is not None
        return self._pool[row]

    def rows_with(self, fingerprint: _Fingerprint) -> list[int]:
        """The pool rows holding a message with this fingerprint, each row fingerprinted once; none without a pool."""
        if self._rows_by_fingerprint is None:
            rows: dict[_Fingerprint, list[int]] = {}
            for row, message in enumerate(self._pool or []):
                rows.setdefault(self.fingerprint(message), []).append(row)
            self._rows_by_fingerprint = rows
        return self._rows_by_fingerprint.get(fingerprint, [])

    def identity(self, input: Sequence[ChatMessage]) -> tuple[int, int]:
        """An input as a retry matches it: its length and a hash of its messages' fingerprints.

        An input stored as pool ranges is hashed a step per range, from the hashes of the pool's first rows, so the same messages stored at other rows (as the pool keeps messages that differ only in metadata) have the same identity.
        """
        hashed = 0
        if isinstance(input, PoolView):
            prefix = self._pool_prefix()
            for begin, end in input.refs:
                power = self._powers[end - begin]
                part = (prefix[end] - prefix[begin] * power) % _MODULUS
                hashed = (hashed * power + part) % _MODULUS
        else:
            for message in input:
                hashed = (hashed * _BASE + self._code(message)) % _MODULUS
        return len(input), hashed

    def _code(self, message: ChatMessage) -> int:
        fingerprint = self.fingerprint(message)
        return self._codes.setdefault(fingerprint, len(self._codes) + 1)

    def _pool_prefix(self) -> list[int]:
        if self._prefix is None:
            prefix = [0]
            for message in self._pool or []:
                prefix.append((prefix[-1] * _BASE + self._code(message)) % _MODULUS)
                self._powers.append(self._powers[-1] * _BASE % _MODULUS)
            self._prefix = prefix
        return self._prefix

    def fingerprint(self, message: ChatMessage) -> _Fingerprint:
        # keyed by identity: inputs read from a pool, or expanded from one,
        # share its message objects, which outlive the build
        found = self._fingerprints.get(id(message))
        if found is None:
            calls = message.tool_calls if message.role == "assistant" else None
            found = self._fingerprints[id(message)] = _Fingerprint(
                message.role,
                mm3_hash(message.text),
                tuple((call.id, call.function) for call in calls or []),
            )
        return found

    def tool_results(
        self, event: ModelEvent, tool_call_ids: Sequence[str] | dict[str, Any]
    ) -> list[tuple[str, str]]:
        """The non-empty results in `event`'s input of the tool calls named, the last for each.

        A result is looked for first where it follows its call, just after the output of the model call that made it; failing that, in the pool rows answering the call, else by scanning the input.
        """
        input = self.of(event)
        issued = self._issued_calls()
        found: dict[str, str] = {}
        missing: list[str] = []
        for tool_call_id in tool_call_ids:
            text: str | None = None
            at = issued.get(tool_call_id)
            if at is not None:
                start, count = at
                for position in range(start, min(start + count, len(input))):
                    message = input[position]
                    if (
                        isinstance(message, ChatMessageTool)
                        and message.tool_call_id == tool_call_id
                        and message.text
                    ):
                        text = message.text
            if text is not None:
                found[tool_call_id] = text
            else:
                missing.append(tool_call_id)
        if missing:
            found.update(self._scan_tool_results(input, missing))
        return list(found.items())

    def _scan_tool_results(
        self, input: Sequence[ChatMessage], tool_call_ids: list[str]
    ) -> dict[str, str]:
        found: dict[str, str] = {}
        if isinstance(input, PoolView):
            rows = self._pool_tool_rows()
            for tool_call_id in tool_call_ids:
                last = -1
                for row in rows.get(tool_call_id, []):
                    for (begin, end), start in zip(input.refs, input.starts):
                        if begin <= row < end and input[start + row - begin].text:
                            last = max(last, start + row - begin)
                if last >= 0:
                    found[tool_call_id] = input[last].text
            return found
        wanted = set(tool_call_ids)
        for message in input:
            if (
                isinstance(message, ChatMessageTool)
                and message.tool_call_id in wanted
                and message.text
            ):
                found[message.tool_call_id] = message.text
        return found

    def _issued_calls(self) -> dict[str, tuple[int, int]]:
        if self._issued is None:
            issued: dict[str, tuple[int, int]] = {}
            for event in self._events:
                if isinstance(event, ModelEvent) and event.output.choices:
                    calls = event.output.choices[0].message.tool_calls or []
                    for call in calls:
                        issued.setdefault(
                            call.id, (len(self.of(event)) + 1, len(calls))
                        )
            self._issued = issued
        return self._issued

    def _pool_tool_rows(self) -> dict[str, list[int]]:
        if self._tool_rows is None:
            rows: dict[str, list[int]] = {}
            for row, message in enumerate(self._pool or []):
                if isinstance(message, ChatMessageTool) and message.tool_call_id:
                    rows.setdefault(message.tool_call_id, []).append(row)
            self._tool_rows = rows
        return self._tool_rows


# =============================================================================
# Continuity
# =============================================================================


class _Call(NamedTuple):
    event: ModelEvent
    input: Sequence[ChatMessage]
    # the message the call answered with; None for a call that failed
    output: ChatMessage | None


class _RowSet:
    """A set of pool rows, counted and listed by interval in logarithmic steps: a Fenwick tree over the pool, kept sparse."""

    def __init__(self, size: int) -> None:
        self._size = size
        self._tree: dict[int, int] = {}
        self._rows: set[int] = set()

    def add(self, row: int) -> None:
        if row in self._rows:
            return
        self._rows.add(row)
        at = row + 1
        while at <= self._size:
            self._tree[at] = self._tree.get(at, 0) + 1
            at += at & -at

    def count(self, begin: int, end: int) -> int:
        """The rows in ``begin..end``."""
        return self._below(end) - self._below(begin)

    def between(self, begin: int, end: int) -> Iterator[int]:
        """The rows in ``begin..end``, ascending."""
        for k in range(self._below(begin) + 1, self._below(end) + 1):
            yield self._kth(k)

    def _below(self, end: int) -> int:
        total, at = 0, end
        while at > 0:
            total += self._tree.get(at, 0)
            at -= at & -at
        return total

    def _kth(self, k: int) -> int:
        at, step = 0, 1 << self._size.bit_length()
        while step:
            below = self._tree.get(at + step, 0)
            if at + step <= self._size and below < k:
                at += step
                k -= below
            step >>= 1
        return at


class _OpenCalls:
    """Calls a later call may continue, looked up where it would hold their output: at the position of their input's length.

    Every call stays open until the thread settles them, which it does whenever it advances or compacts.

    A later call whose input is a list (the timeline of expanded events, as the viewer and Scout read it) is looked up at each open length shorter than its input, a fingerprint each. Forks of one tip share their input, and so their length, and side calls between two turns are few; the costly case is a long run of calls none of which continues another, each with an input of a new length, whose lookups then read at most the positions their inputs hold (pinned by ``test_calls_that_continue_nothing_cost_at_most_their_inputs``).

    A later call whose input is stored as ranges of the message pool (the log driver's) is looked up range by range. A range of rows ``begin..end`` placed at position ``start`` holds, at each position ``L`` it covers, the row ``L + begin - start``, so it can continue only an open call whose length it covers, at a row holding that call's output. The pool rows holding open calls' outputs are kept in a set listed by interval, each fingerprint's rows added once, and each range walks the smaller of the open lengths it covers and those rows it covers, checking each in constant time. So the work is linear in the log as stored except where a range covers both many open lengths and many rows holding open outputs that never line up with them, pinned by ``test_a_pooled_log_s_lookups_walk_the_smaller_of_lengths_and_rows``.
    """

    def __init__(self, inputs: _Inputs) -> None:
        self._inputs = inputs
        self.calls: list[_Call] = []
        # input length -> output fingerprint -> the latest such call's index
        self._index: dict[int, dict[_Fingerprint, int]] = {}
        # the input lengths in the index, ascending
        self._lengths: list[int] = []
        # the pool rows holding an output of a call opened here, by the
        # fingerprints added; never emptied, since a row of an output no
        # longer open only adds to a range's count
        self._rows = _RowSet(inputs.pool_size)
        self._row_fingerprints: set[_Fingerprint] = set()

    def add(self, call: _Call) -> None:
        assert call.output is not None
        at = len(call.input)
        output = self._inputs.fingerprint(call.output)
        by_output = self._index.get(at)
        if by_output is None:
            by_output = self._index[at] = {}
            insort(self._lengths, at)
        by_output[output] = len(self.calls)
        if output not in self._row_fingerprints:
            self._row_fingerprints.add(output)
            for row in self._inputs.rows_with(output):
                self._rows.add(row)
        self.calls.append(call)

    def continued_by(self, call: _Call) -> _Call | None:
        """The latest open call that `call` continues."""
        best = -1
        if isinstance(call.input, PoolView):
            for (begin, end), start in zip(call.input.refs, call.input.starts):
                first = bisect_left(self._lengths, start)
                last = bisect_left(self._lengths, start + end - begin)
                if first == last:
                    continue
                rows = self._rows.count(begin, end)
                if rows == 0:
                    continue
                if last - first <= rows:
                    for at in self._lengths[first:last]:
                        best = max(best, self._open_at(at, begin + at - start))
                else:
                    for row in self._rows.between(begin, end):
                        best = max(best, self._open_at(row - begin + start, row))
        else:
            for at in self._lengths[: bisect_left(self._lengths, len(call.input))]:
                found = self._index[at].get(
                    self._inputs.fingerprint(call.input[at]), -1
                )
                best = max(best, found)
        return self.calls[best] if best >= 0 else None

    def _open_at(self, at: int, row: int) -> int:
        """The latest open call of input length `at` whose output the pool row holds, else -1."""
        by_output = self._index.get(at)
        if by_output is None:
            return -1
        return by_output.get(self._inputs.fingerprint(self._inputs.row(row)), -1)

    def clear(self) -> None:
        self.calls, self._index, self._lengths = [], {}, []


# where a summarizer's summary begins, after any analysis before it
_SUMMARY_TAG = "<summary>"


class _Continuity:
    """The continuity rule: which of a conversation's model calls in a span are its turns, by which calls carry on the others' output.

    An offline form of the agent bridge's thread tracking, for calls that do not record their ``origin``. Calls are taken in order, and the thread's tip is the last turn:

    - A call whose input continues the tip, holding the tip's output at position ``len(tip.input)``, is on the thread, a *head*. Two heads of one tip are a fork: the one a later call continues is the turn, and the others are utility.
    - A call that continues nothing is a *candidate*; if a later call continues it, the thread moves to it (a compaction the log does not show). The candidates a thread goes on without, by advancing or moving to another, are utility; those still open where the thread ends (a scaffold that keeps a window of fixed length, so no later call continues anything) get no answer, and the existing rules decide them.
    - A summary ``CompactionEvent`` resets the tip, and the call just before it is the summarizer, utility, if its output appears in the next call's input (decided by Charles 2026-10-26): Inspect's summary call continues the tip, and the next turn's input holds its summary. The calls still open end the thread as the end of the span does, so a log that records no summary call keeps its last turn. Only the last call is looked for, so each compaction reads the next input once; a summary call followed by another call before the compaction stays a turn. The output appears where a message of that input contains its text, or its text from its last ``<summary>`` tag (Inspect drops the ``<analysis>`` before it); a summary reworded on the way in is not recognized, and its call stays a turn. An edit or trim ends the thread as the end of the span does.
    - A failed call is a turn or utility as its retry, the next call in its conversation with the same input (the same messages by fingerprint, wherever the pool stores them), is; one not retried is a turn.
    - Where the thread ends (the end of the span, an edit or trim, or a move to a candidate), a lone head is its last turn, and a fork goes to the head whose output is in the span's final messages; a fork no later call or final message resolves gets no answer, and the existing rules decide its calls (a scaffold that sends one input again and again would otherwise lose all but its last call).

    So a call is utility only where the conversation went on without it, or where its output is the summary a compaction put in its place.

    A span in which no call continues another has no answer (``linked`` is False), so the existing rules decide, apart from its summarizers: the next input holding a call's output is evidence enough. Each call is looked up at the input lengths of the calls still open (``_OpenCalls``), which the thread settles whenever it advances.
    """

    def __init__(
        self, inputs: _Inputs, final_messages: Sequence[ChatMessage] | None
    ) -> None:
        self._inputs = inputs
        self._final = final_messages
        self.turns: dict[int, bool] = {}
        self.linked = False
        self._tip: _Call | None = None
        self._heads = _OpenCalls(inputs)
        self._candidates = _OpenCalls(inputs)
        # failed calls not yet retried, by their input, and each retried one
        # with its retry
        self._failed: dict[tuple[int, int], list[_Call]] = {}
        self._retried: list[tuple[_Call, _Call]] = []
        # the last call, and the heads open at each summary compaction, until
        # the next call's input shows whether the last call summarized
        self._last: _Call | None = None
        self._summarized: list[tuple[list[_Call], _Call | None]] = []
        self._summarizer_calls: list[_Call] = []

    def call(self, event: ModelEvent) -> None:
        call = _Call(event, self._inputs.of(event), _answer(event))
        if self._summarized:
            self._summarizers(call.input)
        self._last = call
        if call.output is None:
            self._failed.setdefault(self._inputs.identity(call.input), []).append(call)
            return
        if self._failed:
            for failed in self._failed.pop(self._inputs.identity(call.input), []):
                self._retried.append((failed, call))
        head = self._heads.continued_by(call)
        if head is not None:
            self._settle(head, self._heads.calls)
            self._close(self._candidates.calls)
            self._advance(head, call)
            return
        if self._tip is not None and self._continues(call, self._tip):
            self._heads.add(call)
            self.linked = True
            return
        candidate = self._candidates.continued_by(call)
        if candidate is not None:
            self._end(final=False)
            self._settle(candidate, self._candidates.calls)
            self._advance(candidate, call)
            return
        self._candidates.add(call)

    def compaction(self, event: CompactionEvent) -> None:
        if event.type == "summary":
            self._summarized.append((self._heads.calls, self._last))
        else:
            self._end(final=False)
        self._last = None
        self._tip = None
        self._heads.clear()
        self._candidates.clear()

    def finish(self) -> dict[int, bool]:
        if self._summarized:
            self._summarizers(None)
        self._end(final=True)
        for failed, retry in self._retried:
            if id(retry.event) in self.turns:
                self.turns[id(failed.event)] = self.turns[id(retry.event)]
        for waiting in self._failed.values():
            for failed in waiting:
                self.turns[id(failed.event)] = True
        if self.linked:
            return self.turns
        # no call continued another: only the summarizers, and the failed calls
        # they retried, are answered
        answered = {id(call.event) for call in self._summarizer_calls}
        answered.update(
            id(failed.event)
            for failed, retry in self._retried
            if id(retry.event) in answered
        )
        return {event: turn for event, turn in self.turns.items() if event in answered}

    def _end(self, final: bool) -> None:
        """End the thread: a lone head is its last turn, and a fork goes to the head in the final messages (with `final`). An unresolved fork, and candidates still open, get no answer: nothing showed the thread going on without them."""
        heads = self._heads.calls
        found = [h for h in heads if final and self._in_final(h)]
        if found:
            self._settle(found[-1], heads)
        elif len(heads) == 1:
            self._settle(heads[0], heads)

    def _summarizers(self, input: Sequence[ChatMessage] | None) -> None:
        """Settle the calls open at each summary compaction since the last call, given the next call's input (None at the span's end): the call before the compaction is the summarizer, utility, if its output appears in it; of the other heads, a lone head is the thread's last turn."""
        for heads, last in self._summarized:
            summarizer = None
            if last is not None and input is not None and self._summarizes(last, input):
                summarizer = last
                self._close([summarizer])
                self._summarizer_calls.append(summarizer)
            kept = [h for h in heads if h is not summarizer]
            if len(kept) == 1:
                self._settle(kept[0], kept)
        self._summarized = []

    def _summarizes(self, call: _Call, input: Sequence[ChatMessage]) -> bool:
        """Whether `call`'s output appears in `input`: a message of it holds the output's text, or its text from its last ``<summary>`` tag."""
        if call.output is None or not call.output.text:
            return False
        text = call.output.text
        texts = {self._inputs.fingerprint(call.output).text_hash}
        needles = [text]
        if (at := text.rfind(_SUMMARY_TAG)) > 0:
            needles.append(text[at:])
        for message in input:
            # an exact match by the fingerprint each message already has, else
            # the summary within a message the compaction wrapped it in
            if self._inputs.fingerprint(message).text_hash in texts:
                return True
            if any(needle in message.text for needle in needles):
                return True
        return False

    def _advance(self, turn: _Call, call: _Call) -> None:
        self.turns[id(turn.event)] = True
        self._tip = turn
        self._heads.clear()
        self._candidates.clear()
        self._heads.add(call)
        self.linked = True

    def _settle(self, turn: _Call, calls: list[_Call]) -> None:
        for call in calls:
            self.turns[id(call.event)] = call is turn

    def _close(self, calls: list[_Call]) -> None:
        for call in calls:
            self.turns[id(call.event)] = False

    def _continues(self, call: _Call, earlier: _Call) -> bool:
        at = len(earlier.input)
        return (
            earlier.output is not None
            and at < len(call.input)
            and self._inputs.fingerprint(call.input[at])
            == self._inputs.fingerprint(earlier.output)
        )

    def _in_final(self, head: _Call) -> bool:
        at = len(head.input)
        return (
            self._final is not None
            and head.output is not None
            and at < len(self._final)
            and self._inputs.fingerprint(self._final[at])
            == self._inputs.fingerprint(head.output)
        )


def _answer(event: ModelEvent) -> ChatMessage | None:
    if event.error is not None or event.pending or not event.output.choices:
        return None
    return event.output.choices[0].message


def _continuity(
    agent: TimelineSpan,
    inputs: _Inputs,
    final_messages: Sequence[ChatMessage] | None,
) -> dict[int, bool]:
    """Whether each of the span's calls with no recorded origin is a turn by continuity, by `id()` of its event.

    The rule runs over each conversation in the span apart (a span can hold more than one, where the timeline unrolls a solver beside an agent), and a conversation in which no call continues another has no answers but its summarizers', so the existing rules decide its other calls.
    """
    threads: dict[object, _Continuity] = {}

    def thread(event: Event) -> _Continuity:
        conversation = inputs.conversation(event)
        found = threads.get(conversation)
        if found is None:
            found = threads[conversation] = _Continuity(inputs, final_messages)
        return found

    for item in agent.content:
        if not isinstance(item, TimelineEvent):
            continue
        if isinstance(item.event, ModelEvent):
            if item.event.origin is None and not _is_warmup_call(item.event, inputs):
                thread(item.event).call(item.event)
        elif isinstance(item.event, CompactionEvent):
            thread(item.event).compaction(item.event)
    turns: dict[int, bool] = {}
    for found in threads.values():
        turns.update(found.finish())
    return turns


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


def _extract_agent_results(parent: TimelineSpan, inputs: _Inputs) -> None:
    """Extract agent_result for each agent sub-span.

    Three sources (checked in order):
    1. Tool-spawned agents: result already set during _event_to_node
    2. Span-based agents (static flow): sibling ToolEvent with agent_span_id == span.id
    3. Bridge flow: a later sibling ModelEvent's input has the ChatMessageTool answering the call the span is named for (``agent-{tool_call_id}``)

    One pass over the content: each span waiting on the bridge flow is answered by the first later model event whose input holds its result, looked up rather than scanned for (``_Inputs.tool_results``).
    """
    content = parent.content
    agent_tool_events: dict[str, ToolEvent] = {}
    for sibling in content:
        if (
            isinstance(sibling, TimelineEvent)
            and isinstance(sibling.event, ToolEvent)
            and sibling.event.agent_span_id is not None
        ):
            agent_tool_events.setdefault(sibling.event.agent_span_id, sibling.event)

    # tool call id -> the spans waiting on the bridge flow for its result
    waiting: dict[str, list[TimelineSpan]] = {}
    for item in content:
        if isinstance(item, TimelineEvent):
            if waiting and isinstance(item.event, ModelEvent):
                for tool_call_id, text in inputs.tool_results(item.event, waiting):
                    for span in waiting.pop(tool_call_id):
                        span.agent_result = text
            continue

        # Skip if already set (e.g. from tool-spawned agent construction)
        if item.span_type == "agent" and item.agent_result is None:
            # Flow 1: sibling ToolEvent with agent_span_id matching this span
            tool_event = agent_tool_events.get(item.id)
            if tool_event is not None:
                result_text = _extract_tool_event_result(tool_event.result)
                if result_text:
                    item.agent_result = result_text

            # Flow 2: the bridge flow's span id is "agent-{tool_call_id}"
            if (
                item.agent_result is None
                and len(item.id) > 6
                and item.id.startswith("agent-")
            ):
                waiting.setdefault(item.id[6:], []).append(item)

        # Recurse into child spans
        _extract_agent_results(item, inputs)


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


def _get_system_prompt_for_event(event: ModelEvent, inputs: _Inputs) -> str | None:
    """Extract and normalize the system prompt from a single ModelEvent.

    Args:
        event: The ModelEvent to inspect.
        inputs: The model inputs.

    Returns:
        The normalized system prompt text, or None if no system message is
        found or the prompt is empty after normalization (e.g. it consisted
        only of the billing header). Returning None rather than "" keeps
        empty prompts out of primary-trajectory comparisons and prompt
        inheritance.
    """
    for msg in inputs.of(event):
        if isinstance(msg, ChatMessageSystem):
            if isinstance(msg.content, str):
                raw = msg.content
            else:
                parts = [c.text for c in msg.content if hasattr(c, "text")]
                raw = "\n".join(parts)
            normalized = _normalize_system_prompt(raw)
            return normalized if normalized else None
    return None


def _has_tool_calls(event: ModelEvent) -> bool:
    """Check whether a ModelEvent's output contains tool calls."""
    if event.output.choices:
        msg = event.output.choices[0].message
        if msg.tool_calls:
            return True
    return False


def _wrap_utility_events(
    agent: TimelineSpan,
    inputs: _Inputs,
    final_messages: Sequence[ChatMessage] | None = None,
    continuity: bool = False,
) -> None:
    """Wrap foreign-prompt model calls as synthetic utility spans.

    Within bridge-based agent spans (e.g. Claude Code), short extraction
    model calls use a different system prompt and produce no tool calls.
    This function detects them and wraps each one in a ``TimelineSpan``
    with ``utility=True`` so downstream code treats them as utility agents.

    The primary trajectory is identified by the system prompt of the first
    tool-calling ModelEvent. When a span contains no tool-calling model
    events there is no agentic loop to distinguish helpers from — plain
    workflows of ``generate()`` calls routinely mix system prompts — so
    foreign-prompt wrapping is skipped entirely (warmup calls are still
    wrapped; they are identified independently of prompts).

    A call whose recorded ``origin`` is not ``"agent"`` is utility and never
    sets the primary prompt. A call recorded as ``"agent"`` goes through the
    rules above, as a call with no ``origin`` does, since a bridged agent's
    warm-ups and helper calls are recorded as ``"agent"``.

    With `continuity` (replay's log driver only), where calls record no
    ``origin`` and one of a conversation's calls continues another, the
    continuity rule decides which of its calls are turns in place of the
    prompt rules (``_Continuity``); warm-ups stay utility.

    Operates recursively on the entire span tree.

    Args:
        agent: The span node to process (mutated in place).
        inputs: The model inputs.
        final_messages: The span's final messages, which settle a fork at its end.
        continuity: Whether to apply the continuity rule.
    """
    # The primary prompt comes only from a tool-calling ModelEvent: without
    # an agentic loop there is no primary trajectory (see docstring).
    primary_prompt: str | None = None
    for item in agent.content:
        if isinstance(item, TimelineEvent) and isinstance(item.event, ModelEvent):
            if _has_tool_calls(item.event) and _may_be_turn(item.event):
                primary_prompt = _get_system_prompt_for_event(item.event, inputs)
                break

    def utility_wrapper(item: TimelineEvent, index: int) -> TimelineSpan:
        # Fall back to a position-derived id for uuid-less (legacy) events so
        # ids stay unique and deterministic across rebuilds.
        wrapper = TimelineSpan(
            id=f"utility-{item.event.uuid or f'{agent.id}-{index}'}",
            name="utility",
            span_type="agent",
            content=[item],
        )
        wrapper.utility = True
        return wrapper

    turns = _continuity(agent, inputs, final_messages) if continuity else {}

    # --- Scan and wrap utility candidates ---
    original_spans = [item for item in agent.content if isinstance(item, TimelineSpan)]
    new_content: list[TimelineEvent | TimelineSpan] = []
    for index, item in enumerate(agent.content):
        if isinstance(item, TimelineEvent) and isinstance(item.event, ModelEvent):
            if not _may_be_turn(item.event):
                new_content.append(utility_wrapper(item, index))
                continue

            # Warmup/cache-priming call (max_tokens=1)
            if _is_warmup_call(item.event, inputs):
                new_content.append(utility_wrapper(item, index))
                continue

            turn = turns.get(id(item.event))
            if turn is not None:
                if not turn:
                    new_content.append(utility_wrapper(item, index))
                    continue
            elif primary_prompt is not None and not _has_tool_calls(item.event):
                evt_prompt = _get_system_prompt_for_event(item.event, inputs)
                if evt_prompt is not None and evt_prompt != primary_prompt:
                    new_content.append(utility_wrapper(item, index))
                    continue
        new_content.append(item)

    agent.content = new_content

    # Recurse into the span's original children only — not the synthetic
    # wrappers created above: a wrapper holds a single already-processed
    # event, and re-entering it would wrap a warmup call again, forever.
    # Branches are trajectories like any span: process their own direct
    # events too (mirrors the TS port), which also covers their children.
    for item in original_spans:
        _wrap_utility_events(item, inputs, continuity=continuity)
    for branch in agent.branches:
        _wrap_utility_events(branch, inputs, continuity=continuity)


def _may_be_turn(event: ModelEvent) -> bool:
    """An agent turn by its recorded origin, or a call that records none."""
    return event.origin is None or is_agent_turn(event.origin)


def _is_warmup_call(event: ModelEvent, inputs: _Inputs) -> bool:
    """Detect cache-priming warmup calls (max_tokens=1, single-word user prompt)."""
    if event.config.max_tokens is None or event.config.max_tokens > 1:
        return False
    # Check that the last user message is a single word
    for msg in reversed(inputs.of(event)):
        if isinstance(msg, ChatMessageUser):
            if isinstance(msg.content, str):
                return len(msg.content.split()) <= 1
            return False
    return False


# =============================================================================
# Utility Agent Classification
# =============================================================================


def _get_system_prompt(agent: TimelineSpan, inputs: _Inputs) -> str | None:
    """Extract the system prompt from the first ModelEvent in agent's direct content.

    Args:
        agent: The span node to extract the system prompt from.
        inputs: The model inputs.

    Returns:
        The normalized system prompt text (see ``_get_system_prompt_for_event``),
        or None if the span has no ModelEvent or it carries no system message.
    """
    for item in agent.content:
        if isinstance(item, TimelineEvent) and isinstance(item.event, ModelEvent):
            return _get_system_prompt_for_event(item.event, inputs)
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


def _has_agentic_loop(span: TimelineSpan) -> bool:
    """Check whether span's direct content contains a tool-calling ModelEvent."""
    return any(
        isinstance(item, TimelineEvent)
        and isinstance(item.event, ModelEvent)
        and _has_tool_calls(item.event)
        for item in span.content
    )


def _classify_utility_agents(
    node: TimelineSpan,
    inputs: _Inputs,
    parent_system_prompt: str | None = None,
    parent_has_loop: bool = False,
) -> None:
    """Classify utility agents in the tree via post-processing.

    An agent is utility if it has a single turn (or single tool-calling turn)
    and a different system prompt than its parent. Classification only applies
    when the parent runs an agentic (tool-calling) loop: absent a loop there
    is no main trajectory for a helper to be subordinate to — plain workflows
    of ``generate()`` calls routinely mix system prompts.

    Args:
        node: The span node to classify (and recurse into).
        inputs: The model inputs.
        parent_system_prompt: The system prompt of the parent agent.
        parent_has_loop: Whether the parent has a tool-calling ModelEvent
            in its direct content.
    """
    agent_system_prompt = _get_system_prompt(node, inputs)

    # Classify this node (root agent is never utility). Tool-invoked
    # subagents (task/as_tool/handoff) are explicit user-intended
    # sub-trajectories — never utility — even if single-turn. Foreign-prompt
    # helper model calls are handled separately by _wrap_utility_events.
    if (
        parent_system_prompt is not None
        and parent_has_loop
        and agent_system_prompt is not None
        and not node.tool_invoked
    ):
        if agent_system_prompt != parent_system_prompt and _is_single_turn(node):
            node.utility = True

    # Recurse into child spans. Pure grouping spans (no direct model events)
    # inherit from the parent, mirroring the prompt inheritance.
    effective_prompt = agent_system_prompt or parent_system_prompt
    has_model_events = any(
        isinstance(item, TimelineEvent) and isinstance(item.event, ModelEvent)
        for item in node.content
    )
    effective_has_loop = (
        _has_agentic_loop(node) if has_model_events else parent_has_loop
    )
    for item in node.content:
        if isinstance(item, TimelineSpan):
            _classify_utility_agents(item, inputs, effective_prompt, effective_has_loop)


# =============================================================================
# Timeline Span Filtering
# =============================================================================


def timeline_filter(
    timeline: Timeline,
    predicate: Callable[[TimelineSpan], bool],
) -> Timeline:
    """Return a new timeline with only spans matching the predicate.

    Recursively walks span content and branches, keeping ``TimelineSpan``
    items where ``predicate(span)`` returns ``True``. Non-matching spans and
    their entire subtrees are pruned. ``TimelineEvent`` items are always kept
    because they belong to the parent span.

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
    """Recursively filter a span's content and branches."""
    filtered_content: list[TimelineEvent | TimelineSpan] = []
    for item in span.content:
        if isinstance(item, TimelineSpan):
            if predicate(item):
                filtered_content.append(_filter_span_by_predicate(item, predicate))
        else:
            filtered_content.append(item)

    filtered_branches: list[TimelineSpan] = []
    for branch in span.branches:
        if predicate(branch):
            filtered_branches.append(_filter_span_by_predicate(branch, predicate))

    return span.model_copy(
        update={"content": filtered_content, "branches": filtered_branches}
    )
