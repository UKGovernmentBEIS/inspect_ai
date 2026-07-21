"""Frozen legacy outline pipeline — the parity oracle (epatey#23).

Bug-for-bug Python port of the viewer's outline row derivation, frozen at
ts-mono ``9096073512b0`` from:

- ``packages/inspect-components/src/transcript/timeline/hooks/useEventNodes.ts``
- ``.../timeline/retryGrouping.ts``
- ``.../transform/fixups.ts`` / ``treeify.ts`` / ``transform.ts`` / ``flatten.ts``
- ``.../outline/TranscriptOutline.tsx`` (``outlineNodeList``)
- ``.../outline/tree-visitors.ts``

The port preserves the legacy pipeline's quirks deliberately (the oracle
freezes what the skeleton-fed outline must reproduce): tool events with no
preceding model are silently dropped by ``makeTurns``; ``injectScorersSpan``
wraps only the first scorer span (and only when its ``span_id`` is set);
``skipThisNode`` reduces direct-child depth by 2 but deeper descendants by 1.

Stages skipped, with rationale:

- ``correctRetryTimestamps`` — repairs display timestamps only; nothing on
  the outline path sorts by timestamp, so row structure is unaffected.
- ``attachSourceSpans`` — scout-only (``sourceSpans`` is undefined in
  inspect; see ``EventNodeSpan`` docs in ``types.ts``).
- ``processPendingEvents`` streaming branch — at-rest logs only, so pending
  events are filtered (``filterPending=true``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal, NamedTuple

from inspect_ai.event._event import Event
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._span import SpanBeginEvent
from inspect_ai.event._tool import ToolEvent

SANDBOX_SIGNAL_NAME = "53787D8A-D3FC-426D-B383-9F880B70E4AA"
"""``kSandboxSignalName`` (fixups.ts)."""

_SCORERS_SPAN_ID = "C5A831026F2C"
"""``kScorersSpanId`` (treeify.ts)."""

_COLLAPSIBLE_EVENT_TYPES = ("step", "span_begin", "tool", "subtask")
"""``kCollapsibleEventTypes`` (types.ts)."""

CollapseState = Literal["default", "expanded", "collapsed"] | frozenset[str]
"""Harness-level collapse state: a preset, or a set of span identities
(span ids; legacy steps use the skeleton convention ``step-<begin index>``)."""


@dataclass
class _Ev:
    """Uniform event record.

    Pydantic events are flattened once, synthetics constructed directly —
    mirroring the TS pipeline, which reads plain JSON.
    """

    event: str
    index: int | None
    """Sequence index in the original event list (None for synthetics)."""
    name: str | None = None
    type: str | None = None
    action: str | None = None
    id: str | None = None
    parent_id: str | None = None
    span_id: str | None = None
    uuid: str | None = None
    pending: bool = False
    agent: str | None = None
    failed: bool | None = None
    # retry-grouping identity (model events)
    error: str | None = None
    model: str | None = None
    input_len: int = 0
    tool_names: tuple[str, ...] = ()
    tool_choice: str | None = None
    # synthesized turn/turns/scoring rows
    count: int | None = None
    anchor: int | None = None


def _to_ev(event: Event, index: int) -> _Ev:
    ev = _Ev(
        event=event.event,
        index=index,
        span_id=event.span_id,
        uuid=event.uuid,
        pending=bool(event.pending),
        name=getattr(event, "name", None),
        type=getattr(event, "type", None),
        action=getattr(event, "action", None),
    )
    if isinstance(event, SpanBeginEvent):
        ev.id = event.id
        ev.parent_id = event.parent_id
    if isinstance(event, ToolEvent):
        ev.agent = event.agent
        ev.failed = event.failed
    if isinstance(event, ModelEvent):
        ev.error = event.error
        ev.model = event.model
        ev.input_len = len(event.input)
        ev.tool_names = tuple(tool.name for tool in event.tools)
        choice = event.tool_choice
        ev.tool_choice = choice if isinstance(choice, str) else choice.name
    return ev


@dataclass
class _Node:
    """``EventNode`` (types.ts)."""

    id: str
    event: _Ev
    depth: int
    children: list[_Node] = field(default_factory=list)


# -- retryGrouping.ts --


def _same_call(failed: _Ev, success: _Ev) -> bool:
    return (
        failed.model == success.model
        and failed.input_len == success.input_len
        and failed.tool_names == success.tool_names
        and failed.tool_choice == success.tool_choice
    )


def _group_retry_attempts(events: list[_Ev]) -> list[_Ev]:
    pending_failed: dict[str, list[tuple[_Ev, int]]] = {}
    drop: set[int] = set()
    for i, ev in enumerate(events):
        if ev.event != "model":
            continue
        key = ev.span_id or ""
        if ev.error is not None:
            pending_failed.setdefault(key, []).append((ev, i))
            continue
        run = pending_failed.pop(key, [])
        drop.update(i for failed, i in run if _same_call(failed, ev))
    return [ev for i, ev in enumerate(events) if i not in drop]


# -- fixups.ts --


def _collapse_sample_init(events: list[_Ev]) -> list[_Ev]:
    if any(ev.event in ("span_begin", "span_end") for ev in events):
        return events
    if any(ev.event == "step" and ev.name == "init" for ev in events):
        return events
    init_index = next(
        (i for i, ev in enumerate(events) if ev.event == "sample_init"), None
    )
    if init_index is None:
        return events

    def step(action: str) -> _Ev:
        return _Ev(
            event="step",
            index=None,
            action=action,
            name="sample_init",
            span_id=events[init_index].span_id,
            anchor=events[init_index].index,
        )

    fixed = list(events)
    fixed.insert(init_index, step("begin"))
    fixed.insert(init_index + 2, step("end"))
    return fixed


def _group_sandbox_events(events: list[_Ev]) -> list[_Ev]:
    use_spans = any(ev.event == "span_begin" for ev in events)

    def wrapper(kind: str) -> _Ev:
        if use_spans:
            return _Ev(
                event=f"span_{kind}",
                index=None,
                name=SANDBOX_SIGNAL_NAME,
                id=f"{SANDBOX_SIGNAL_NAME}-{kind}",
                span_id=SANDBOX_SIGNAL_NAME,
            )
        return _Ev(event="step", index=None, action=kind, name=SANDBOX_SIGNAL_NAME)

    result: list[_Ev] = []
    pending: list[_Ev] = []

    def flush() -> None:
        if pending:
            result.append(wrapper("begin"))
            result.extend(pending)
            result.append(wrapper("end"))
            pending.clear()

    for ev in events:
        if ev.event == "sandbox":
            pending.append(ev)
        else:
            flush()
            result.append(ev)
    flush()
    return result


def _fixup_event_stream(events: list[_Ev]) -> list[_Ev]:
    events = [ev for ev in events if not ev.pending]
    return _group_sandbox_events(_collapse_sample_init(events))


# -- treeify.ts --


def _inject_scorers_span(events: list[_Ev]) -> list[_Ev]:
    results: list[_Ev] = []
    collected: list[_Ev] = []
    has_collected = False
    collecting: str | None = None

    def flush() -> list[_Ev]:
        nonlocal has_collected
        if not collected:
            return []
        begin = _Ev(
            event="span_begin",
            index=None,
            name="scorers",
            id="E617087FA405",
            span_id=_SCORERS_SPAN_ID,
            type="scorers",
        )
        reparented = [
            replace(
                ev,
                parent_id=(ev.parent_id or _SCORERS_SPAN_ID)
                if ev.event == "span_begin"
                else None,
            )
            for ev in collected
        ]
        end = _Ev(
            event="span_end", index=None, id="C39922B09481", span_id=_SCORERS_SPAN_ID
        )
        collected.clear()
        has_collected = True
        return [begin, *reparented, end]

    for ev in events:
        if ev.event == "span_begin" and ev.type == "scorers":
            return events
        if ev.event == "span_begin" and ev.type == "scorer" and not has_collected:
            collecting = ev.span_id
        if collecting:
            if ev.event == "span_end" and ev.span_id == collecting:
                collecting = None
                results.extend(flush())
                results.append(ev)
            else:
                collected.append(ev)
        else:
            results.append(ev)
    return results


class _NodeFactory:
    def __init__(self, depth: int) -> None:
        self.root_nodes: list[_Node] = []
        self._depth = depth
        self._child_counts: dict[int | None, int] = {}
        self._paths: dict[int, str] = {}

    def create(self, event: _Ev, parent: _Node | None) -> _Node:
        parent_key = id(parent) if parent is not None else None
        next_index = self._child_counts.get(parent_key, 0)
        self._child_counts[parent_key] = next_index + 1
        parent_path = self._paths.get(id(parent)) if parent is not None else None
        path = (
            f"{parent_path}.{next_index}"
            if parent_path is not None
            else str(next_index)
        )
        node = _Node(
            id=event.uuid or f"event_node_{path}",
            event=event,
            depth=parent.depth + 1 if parent else self._depth,
        )
        self._paths[id(node)] = path
        if parent:
            parent.children.append(node)
        else:
            self.root_nodes.append(node)
        return node


def _treeify_with_spans(events: list[_Ev], depth: int) -> list[_Node]:
    factory = _NodeFactory(depth)
    span_nodes: dict[str, _Node] = {}
    for ev in events:
        if ev.event == "span_end":
            continue
        if ev.event == "step" and ev.action != "begin":
            continue
        if ev.event == "span_begin":
            parent = span_nodes.get(ev.parent_id) if ev.parent_id else None
        else:
            parent = span_nodes.get(ev.span_id) if ev.span_id else None
        node = factory.create(ev, parent)
        if ev.event == "span_begin" and ev.id is not None:
            span_nodes[ev.id] = node
    return factory.root_nodes


def _treeify_with_steps(events: list[_Ev], depth: int) -> list[_Node]:
    factory = _NodeFactory(depth)
    stack: list[_Node] = []
    for ev in events:
        parent = stack[-1] if stack else None
        if ev.event == "step":
            if ev.action == "begin":
                stack.append(factory.create(ev, parent))
            elif stack:
                stack.pop()
        elif ev.event == "span_begin":
            stack.append(factory.create(ev, parent))
        elif ev.event == "span_end":
            if stack:
                stack.pop()
        else:
            factory.create(ev, parent)
    return factory.root_nodes


def _treeify_events(events: list[_Ev], depth: int) -> list[_Node]:
    use_spans = any(ev.event == "span_begin" for ev in events)
    events = _inject_scorers_span(events)
    if use_spans:
        return _transform_tree(_treeify_with_spans(events, depth))
    return _treeify_with_steps(events, depth)


# -- transform.ts --


def _reduce_depth(nodes: list[_Node], depth: int = 1) -> list[_Node]:
    for node in nodes:
        if node.children:
            node.children = _reduce_depth(node.children, 1)
        node.depth -= depth
    return nodes


def _set_depth(nodes: list[_Node], depth: int) -> list[_Node]:
    for node in nodes:
        if node.children:
            node.children = _set_depth(node.children, depth + 1)
        node.depth = depth
    return nodes


def _elevate_child_node(node: _Node, child_event_type: str) -> _Node | None:
    target_index = next(
        (i for i, c in enumerate(node.children) if c.event.event == child_event_type),
        None,
    )
    if target_index is None:
        return None
    target = replace(node.children[target_index])
    remaining = [c for i, c in enumerate(node.children) if i != target_index]
    target.depth = node.depth
    target.children = _set_depth(remaining, node.depth + 1)
    return target


def _skip_first_child_node(node: _Node) -> _Node:
    agent_span = node.children.pop(0)
    node.children[0:0] = _reduce_depth(agent_span.children)
    return node


def _skip_this_node(node: _Node) -> _Node:
    new_node = replace(node.children[0])
    new_node.depth = node.depth
    new_node.children = _reduce_depth(list(new_node.children), 2)
    return new_node


def _discard_node(node: _Node) -> list[_Node]:
    return _reduce_depth(node.children, 1)


def _is_agent_or_solver_span(node: _Node) -> bool:
    return node.event.event == "span_begin" and node.event.type in ("solver", "agent")


def _unqualified(name: str | None) -> str | None:
    if name is None:
        return None
    _, _, tail = name.partition("/")
    return tail or name


def _is_same_name_span_child(parent: _Node, child: _Node) -> bool:
    return (
        _is_agent_or_solver_span(child)
        and parent.event.event == "span_begin"
        and _unqualified(parent.event.name) == _unqualified(child.event.name)
    )


def _matches_agent_solver(node: _Node, with_store: bool) -> bool:
    length = 3 if with_store else 2
    return (
        node.event.event == "span_begin"
        and node.event.type == "solver"
        and len(node.children) == length
        and node.children[0].event.event == "span_begin"
        and node.children[0].event.type == "agent"
        and node.children[1].event.event == "state"
        and (not with_store or node.children[2].event.event == "store")
    )


def _matches_handoff(node: _Node) -> bool:
    if not (node.event.event == "span_begin" and node.event.type == "handoff"):
        return False
    if len(node.children) == 1:
        child = node.children[0]
        return child.event.event == "tool" and bool(child.event.agent)
    return (
        len(node.children) == 2
        and node.children[0].event.event == "tool"
        and node.children[1].event.event == "store"
        and len(node.children[0].children) == 2
        and node.children[0].children[0].event.event == "span_begin"
        and node.children[0].children[0].event.type == "agent"
    )


def _collapse_same_name_spans(node: _Node) -> _Node:
    node.children = [
        grandchild
        for child in node.children
        for grandchild in (
            _reduce_depth(child.children, 1)
            if _is_same_name_span_child(node, child)
            else [child]
        )
    ]
    return node


_Transformer = tuple[Callable[[_Node], bool], Callable[[_Node], "_Node | list[_Node]"]]

_TRANSFORMERS: list[_Transformer] = [
    # unwrap_main
    (
        lambda n: n.event.event == "span_begin" and n.event.type == "main",
        lambda n: [_set_child_depth(c, n.depth) for c in n.children],
    ),
    # unwrap_tools / unwrap_subtasks
    (
        lambda n: n.event.event == "span_begin" and n.event.type == "tool",
        lambda n: _elevate_child_node(n, "tool") or n,
    ),
    (
        lambda n: n.event.event == "span_begin" and n.event.type == "subtask",
        lambda n: _elevate_child_node(n, "subtask") or n,
    ),
    # unwrap_agent_solver (without and with store)
    (lambda n: _matches_agent_solver(n, with_store=False), _skip_first_child_node),
    (lambda n: _matches_agent_solver(n, with_store=True), _skip_first_child_node),
    # unwrap_handoff
    (_matches_handoff, _skip_this_node),
    # collapse_same_name_spans
    (
        lambda n: _is_agent_or_solver_span(n)
        and any(_is_same_name_span_child(n, c) for c in n.children),
        _collapse_same_name_spans,
    ),
    # discard_solvers_span / discard_checkpoint_span
    (
        lambda n: n.event.event == "span_begin" and n.event.type == "solvers",
        _discard_node,
    ),
    (
        lambda n: n.event.event == "span_begin" and n.event.type == "checkpoint",
        _discard_node,
    ),
]


def _set_child_depth(node: _Node, depth: int) -> _Node:
    node.depth = depth
    return node


def _transform_tree(roots: list[_Node]) -> list[_Node]:
    def visit(node: _Node) -> list[_Node]:
        node.children = [n for child in node.children for n in visit(child)]
        current = [node]
        for matches, process in _TRANSFORMERS:
            next_nodes: list[_Node] = []
            for cur in current:
                if matches(cur):
                    result = process(cur)
                    next_nodes.extend(result if isinstance(result, list) else [result])
                else:
                    next_nodes.append(cur)
            current = next_nodes
        return current

    return [n for root in roots for n in visit(root)]


# -- useEventNodes.ts --


def _filter_empty(nodes: list[_Node]) -> list[_Node]:
    kept: list[_Node] = []
    for node in nodes:
        if node.children:
            node.children = _filter_empty(node.children)
        if node.event.event == "span_begin" and node.event.type in (
            "fork_nav",
            "empty_branch",
        ):
            kept.append(node)
        elif node.event.event not in ("span_begin", "step") or node.children:
            kept.append(node)
    return kept


def _matches_collapse_filter(ev: _Ev) -> bool:
    if ev.type == "solver" and ev.name == "system_message":
        return True
    if ev.event in ("step", "span_begin") and ev.name in (
        SANDBOX_SIGNAL_NAME,
        "init",
        "sample_init",
    ):
        return True
    if ev.event == "tool" and not ev.agent and not ev.failed:
        return True
    return ev.event == "subtask"


def _default_collapsed_ids(nodes: list[_Node]) -> dict[str, bool]:
    collapsed: dict[str, bool] = {}

    def walk(nodes: list[_Node]) -> None:
        for node in nodes:
            if (
                node.event.event in _COLLAPSIBLE_EVENT_TYPES
                and _matches_collapse_filter(node.event)
            ):
                collapsed[node.id] = True
            walk(node.children)

    walk(nodes)
    return collapsed


# -- flatten.ts + tree-visitors.ts --

_Visitor = Callable[[_Node], list[_Node]]


def _remove_node_visitor(event: str) -> _Visitor:
    return lambda node: [] if node.event.event == event else [node]


def _remove_step_span_name_visitor(name: str) -> _Visitor:
    return (
        lambda node: []
        if node.event.event in ("step", "span_begin") and node.event.name == name
        else [node]
    )


def _no_scorer_children() -> _Visitor:
    in_scorers = False
    in_scorer = False
    current_depth = -1

    def visit(node: _Node) -> list[_Node]:
        nonlocal in_scorers, in_scorer, current_depth
        if node.event.event == "span_begin" and node.event.type == "scorers":
            in_scorers = True
            return [node]
        if node.event.event in ("step", "span_begin") and node.event.type == "scorer":
            in_scorer = True
            current_depth = node.depth
            return [node]
        if in_scorers and in_scorer and node.depth == current_depth + 1:
            return []
        return [node]

    return visit


def _flat_tree(
    nodes: list[_Node],
    collapsed: Mapping[str, bool] | None,
    visitors: Sequence[_Visitor] | None = None,
) -> list[_Node]:
    result: list[_Node] = []
    for node in nodes:
        if visitors:
            pending = [replace(node)]
            for visitor in visitors:
                pending = [n for p in pending for n in visitor(p)]
            for p in pending:
                p.children = _flat_tree(p.children, collapsed, visitors)
                result.append(p)
                if collapsed is None or not collapsed.get(p.id):
                    result.extend(p.children)
        else:
            result.append(node)
            children = _flat_tree(node.children, collapsed, visitors)
            if collapsed is None or not collapsed.get(node.id):
                result.extend(children)
    return result


def _make_turns(nodes: list[_Node]) -> list[_Node]:
    results: list[_Node] = []
    model_node: _Node | None = None
    tool_nodes: list[_Node] = []
    turn_count = 1

    def make_turn() -> None:
        nonlocal model_node, turn_count
        if model_node is not None:
            turn = _Node(
                id=model_node.id,
                event=_Ev(
                    event="span_begin",
                    index=None,
                    type="turn",
                    name=f"turn {turn_count}",
                    span_id=model_node.event.span_id,
                    anchor=model_node.event.index,
                ),
                depth=model_node.depth,
                children=[model_node, *tool_nodes],
            )
            turn_count += 1
            results.append(turn)
        model_node = None
        tool_nodes.clear()

    for node in nodes:
        if node.event.event == "model":
            make_turn()
            model_node = node
        elif node.event.event == "tool":
            tool_nodes.append(node)
        elif model_node is not None and node.event.event in ("logger", "info"):
            tool_nodes.append(node)
        else:
            make_turn()
            results.append(node)
    make_turn()
    return results


def _collapse_turns(nodes: list[_Node]) -> list[_Node]:
    results: list[_Node] = []
    collecting: list[_Node] = []

    def collect() -> None:
        if collecting:
            first = collecting[0]
            count = len(collecting)
            results.append(
                _Node(
                    id=first.id,
                    event=replace(
                        first.event,
                        name=f"{count} {'turn' if count == 1 else 'turns'}",
                        type="turns",
                        count=count,
                    ),
                    depth=first.depth,
                )
            )
            collecting.clear()

    for node in nodes:
        if node.event.event == "span_begin" and node.event.type == "turn":
            if collecting and collecting[0].depth != node.depth:
                collect()
            collecting.append(node)
        else:
            collect()
            results.append(node)
    collect()
    return results


def _collapse_scoring(nodes: list[_Node]) -> list[_Node]:
    results: list[_Node] = []
    collecting: list[_Node] = []

    def collect() -> None:
        if collecting:
            first = collecting[0]
            results.append(
                _Node(
                    id=first.id,
                    event=replace(
                        first.event,
                        name="scoring",
                        type="scorings",
                        count=len(collecting),
                        anchor=first.event.index,
                    ),
                    depth=first.depth,
                )
            )
            collecting.clear()

    for node in nodes:
        if node.event.event == "score":
            collecting.append(node)
        else:
            collect()
            results.append(node)
    collect()
    return results


# -- public API --


class OutlineRow(NamedTuple):
    """One canonical outline row from the frozen legacy pipeline."""

    kind: Literal["span", "turns", "scoring", "event"]
    depth: int
    name: str | None
    type: str | None
    anchor: int | None
    """Sequence index of the row's anchor event (None only for synthetic
    rows whose subtree holds no indexed events)."""
    total: int | None
    """Merged item count (turns / scoring rows)."""


def _first_index(node: _Node) -> int | None:
    if node.event.index is not None:
        return node.event.index
    if node.event.anchor is not None:
        return node.event.anchor
    return next(
        (index for c in node.children if (index := _first_index(c)) is not None), None
    )


def _to_row(node: _Node) -> OutlineRow:
    ev = node.event
    if ev.type == "turns":
        return OutlineRow("turns", node.depth, None, None, ev.anchor, ev.count)
    if ev.type == "scorings":
        return OutlineRow("scoring", node.depth, None, None, ev.anchor, ev.count)
    if ev.event in ("span_begin", "step"):
        return OutlineRow(
            "span", node.depth, ev.name, ev.type, _first_index(node), None
        )
    return OutlineRow("event", node.depth, ev.name, ev.event, ev.index, None)


def _span_identity(node: _Node) -> str | None:
    """Collapse identity shared with the candidate side.

    Spans use their span id; legacy steps use the skeleton convention
    ``step-<begin index>``; elevated tool/subtask event nodes answer to
    their enclosing span's id via ``span_id`` (the skeleton keeps the span
    row that legacy replaced with the event).
    """
    ev = node.event
    if ev.event == "span_begin":
        return ev.id
    if ev.event == "step":
        return f"step-{ev.index}" if ev.index is not None else None
    if ev.event in ("tool", "subtask"):
        return ev.span_id
    return None


def oracle_outline_rows(
    events: Sequence[Event], collapse: CollapseState = "default"
) -> list[OutlineRow]:
    """Outline rows per the frozen legacy pipeline.

    Args:
        events: Complete event sequence for a sample.
        collapse: ``"default"`` (the viewer's default-collapse policy),
            ``"expanded"``, ``"collapsed"`` (every span identity collapsed),
            or an explicit set of collapsed span identities.
    """
    evs = _group_retry_attempts([_to_ev(ev, i) for i, ev in enumerate(events)])
    tree = _filter_empty(_treeify_events(_fixup_event_stream(evs), 0))

    collapsed: Mapping[str, bool]
    if collapse == "default":
        collapsed = _default_collapsed_ids(tree)
    else:
        if collapse == "expanded":
            identities: frozenset[str] = frozenset()
        elif collapse == "collapsed":
            all_ids: set[str] = set()

            def walk(nodes: list[_Node]) -> None:
                for node in nodes:
                    identity = _span_identity(node)
                    if identity is not None:
                        all_ids.add(identity)
                    walk(node.children)

            walk(tree)
            identities = frozenset(all_ids)
        else:
            identities = collapse

        by_id: dict[str, bool] = {}

        def mark(nodes: list[_Node]) -> None:
            for node in nodes:
                if _span_identity(node) in identities:
                    by_id[node.id] = True
                mark(node.children)

        mark(tree)
        collapsed = by_id

    flat = _flat_tree(
        tree,
        collapsed,
        [
            _remove_node_visitor("logger"),
            _remove_node_visitor("info"),
            _remove_node_visitor("state"),
            _remove_node_visitor("store"),
            _remove_node_visitor("approval"),
            _remove_node_visitor("input"),
            _remove_node_visitor("sandbox"),
            _remove_step_span_name_visitor(SANDBOX_SIGNAL_NAME),
            _no_scorer_children(),
        ],
    )
    return [
        _to_row(node) for node in _collapse_scoring(_collapse_turns(_make_turns(flat)))
    ]
