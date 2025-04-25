from datetime import datetime

from inspect_ai.log import (
    InfoEvent,
    LoggerEvent,
    SpanBeginEvent,
    SpanEndEvent,
    SpanNode,
    event_sequence,
    event_tree,
)
from inspect_ai.log._message import LoggingMessage

# TODO: these tests currently failing
# test_task_grouping():
# test_complex_task_grouping
# task_order_deterministic
# test_sequence_preserves_event_order


def test_empty_input():
    """Test that empty input produces empty output"""
    events = []
    tree = event_tree(events)
    assert tree == []
    sequence = list(event_sequence(tree))
    assert sequence == []


def test_single_span():
    """Test basic tree building with a single span"""
    span_begin = SpanBeginEvent(id="span1", name="test_span")
    log_event = LoggerEvent(span_id="span1", message=logger_msg("log inside span"))
    span_end = SpanEndEvent(id="span1")

    events = [span_begin, log_event, span_end]
    tree = event_tree(events)

    # Verify tree structure
    assert len(tree) == 1
    assert isinstance(tree[0], SpanNode)
    assert tree[0].id == "span1"
    assert tree[0].begin == span_begin
    assert tree[0].end == span_end
    assert len(tree[0].children) == 1
    assert tree[0].children[0] == log_event

    # Verify flattened sequence
    sequence = list(event_sequence(tree))
    assert sequence == events


def test_nested_spans():
    """Test nested spans are properly constructed"""
    parent_begin = SpanBeginEvent(id="parent", name="parent_span")
    child_begin = SpanBeginEvent(id="child", parent_id="parent", name="child_span")
    log_in_child = LoggerEvent(span_id="child", message=logger_msg("child log"))
    child_end = SpanEndEvent(id="child")
    log_in_parent = LoggerEvent(span_id="parent", message=logger_msg("parent log"))
    parent_end = SpanEndEvent(id="parent")

    events = [
        parent_begin,
        child_begin,
        log_in_child,
        child_end,
        log_in_parent,
        parent_end,
    ]

    tree = event_tree(events)

    # Verify parent node
    assert len(tree) == 1
    parent_node = tree[0]
    assert isinstance(parent_node, SpanNode)
    assert parent_node.id == "parent"
    assert parent_node.begin == parent_begin
    assert parent_node.end == parent_end

    # Verify child node is inside parent
    assert len(parent_node.children) == 2  # child span and log event
    child_span = next(
        child for child in parent_node.children if isinstance(child, SpanNode)
    )
    assert child_span.id == "child"
    assert len(child_span.children) == 1
    assert child_span.children[0] == log_in_child

    # Verify sequence
    sequence = list(event_sequence(tree))
    assert sequence == events


def test_multiple_root_spans():
    """Test multiple root-level spans"""
    span1_begin = SpanBeginEvent(id="span1", name="span1")
    span1_end = SpanEndEvent(id="span1")
    span2_begin = SpanBeginEvent(id="span2", name="span2")
    span2_end = SpanEndEvent(id="span2")

    events = [span1_begin, span1_end, span2_begin, span2_end]
    tree = event_tree(events)

    assert len(tree) == 2
    assert tree[0].id == "span1"
    assert tree[1].id == "span2"

    sequence = list(event_sequence(tree))
    assert sequence == events


def test_events_outside_spans():
    """Test events that don't belong to any span"""
    log1 = LoggerEvent(message=logger_msg("log1"))
    span_begin = SpanBeginEvent(id="span1", name="span")
    log2 = LoggerEvent(span_id="span1", message=logger_msg("log2"))
    span_end = SpanEndEvent(id="span1")
    log3 = LoggerEvent(message=logger_msg("log3"))

    events = [log1, span_begin, log2, span_end, log3]
    tree = event_tree(events)

    assert len(tree) == 3
    assert tree[0] == log1
    assert isinstance(tree[1], SpanNode)
    assert tree[2] == log3

    sequence = list(event_sequence(tree))
    assert sequence == events


def test_missing_span_end():
    """Test handling spans without end events"""
    span_begin = SpanBeginEvent(id="span1", name="test_span")
    log_event = LoggerEvent(span_id="span1", message=logger_msg("log"))

    events = [span_begin, log_event]
    tree = event_tree(events)

    assert len(tree) == 1
    assert isinstance(tree[0], SpanNode)
    assert tree[0].end is None

    sequence = list(event_sequence(tree))
    assert len(sequence) == 2
    assert sequence[0] == span_begin
    assert sequence[1] == log_event


def test_span_end_without_begin():
    """Test handling span end events with no matching begin"""
    span_end = SpanEndEvent(id="nonexistent")
    log_event = LoggerEvent(message=logger_msg("log"))

    events = [span_end, log_event]
    tree = event_tree(events)

    # The span_end should be ignored (no node created for it)
    assert len(tree) == 1
    assert tree[0] == log_event

    sequence = list(event_sequence(tree))
    assert sequence == [log_event]


def test_task_order_deterministic():
    """Test that task ordering is deterministic based on first appearance"""
    span_begin = SpanBeginEvent(id="span", name="span")

    # Create events with different task IDs in mixed order
    log1 = LoggerEvent(span_id="span", task_id=3, message=logger_msg("task 3 first"))
    log2 = LoggerEvent(span_id="span", task_id=1, message=logger_msg("task 1 first"))
    log3 = LoggerEvent(span_id="span", task_id=3, message=logger_msg("task 3 second"))
    log4 = LoggerEvent(span_id="span", task_id=2, message=logger_msg("task 2 first"))
    log5 = LoggerEvent(span_id="span", task_id=1, message=logger_msg("task 1 second"))

    span_end = SpanEndEvent(id="span")

    events = [span_begin, log1, log2, log3, log4, log5, span_end]
    tree = event_tree(events)

    # The order should be tasks grouped by first appearance: 3, 1, 2
    span_node = tree[0]
    children = span_node.children

    # Expected groups: task 3 (log1, log3), task 1 (log2, log5), task 2 (log4)
    assert children[0].task_id == 3
    assert children[1].task_id == 3
    assert children[2].task_id == 1
    assert children[3].task_id == 1
    assert children[4].task_id == 2

    # Run again with different initial order
    events2 = [span_begin, log2, log4, log1, log3, log5, span_end]
    tree2 = event_tree(events2)

    span_node2 = tree2[0]
    children2 = span_node2.children

    # Expected groups: task 1 (log2, log5), task 2 (log4), task 3 (log1, log3)
    assert children2[0].task_id == 1
    assert children2[1].task_id == 1
    assert children2[2].task_id == 2
    assert children2[3].task_id == 3
    assert children2[4].task_id == 3


def test_sequence_preserves_events():
    """Test that all events from the tree are present in the sequence"""
    # Create a complex event structure
    root_begin = SpanBeginEvent(id="root", name="root")
    log1 = LoggerEvent(span_id="root", message=logger_msg("log1"))
    span1_begin = SpanBeginEvent(id="span1", parent_id="root", name="span1")
    log2 = LoggerEvent(span_id="span1", message=logger_msg("log2"))
    info1 = InfoEvent(span_id="span1", source="test", data={"key": "value"})
    span1_end = SpanEndEvent(id="span1")
    log3 = LoggerEvent(span_id="root", message=logger_msg("log3"))
    root_end = SpanEndEvent(id="root")

    events = [root_begin, log1, span1_begin, log2, info1, span1_end, log3, root_end]

    tree = event_tree(events)
    sequence = list(event_sequence(tree))

    # Check all events are present
    assert len(sequence) == len(events)

    # Check that each original event appears in the sequence
    for original_event in events:
        assert original_event in sequence


def test_sequence_preserves_event_order():
    """Test that the event sequence preserves the logical order of events"""
    # Create events with a specific logical order
    span1_begin = SpanBeginEvent(id="span1", name="span1")
    span2_begin = SpanBeginEvent(id="span2", parent_id="span1", name="span2")
    log1 = LoggerEvent(span_id="span2", message=logger_msg("log1"))
    span2_end = SpanEndEvent(id="span2")
    log2 = LoggerEvent(span_id="span1", message=logger_msg("log2"))
    span1_end = SpanEndEvent(id="span1")

    # Test with original order
    events = [span1_begin, span2_begin, log1, span2_end, log2, span1_end]

    tree = event_tree(events)
    sequence = list(event_sequence(tree))

    # Check order is preserved
    assert sequence == events

    # Test with alternate valid order that should result in the same tree
    events_alt = [span1_begin, log2, span2_begin, log1, span2_end, span1_end]

    tree_alt = event_tree(events_alt)
    sequence_alt = list(event_sequence(tree_alt))

    # The resulting sequence should have the span containment logic preserved
    # span1_begin, span2_begin, log1, span2_end, log2, span1_end
    assert sequence_alt[0] == span1_begin
    assert sequence_alt[1] == span2_begin
    assert sequence_alt[2] == log1
    assert sequence_alt[3] == span2_end
    assert sequence_alt[4] == log2
    assert sequence_alt[5] == span1_end


def logger_msg(msg: str) -> LoggingMessage:
    return LoggingMessage(
        level="info", message="msg", created=datetime.now().timestamp()
    )
