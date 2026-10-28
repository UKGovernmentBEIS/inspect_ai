"""Check a logged sample against the message id contract.

An id names one message with one content: no id carries two versions of what a
message shows, the same edit of the same messages is always one id, and a message
a model call sends again unchanged keeps its id. Written independently of the
id code it checks.
"""

import json
from collections import defaultdict
from typing import Any

from inspect_ai.event import ModelEvent, ToolEvent
from inspect_ai.log import EvalSample
from inspect_ai.model import ChatMessage, ChatMessageAssistant, ChatMessageTool


def shown(message: ChatMessage) -> str:
    """What a message shows a consumer, without provider internals or metadata."""
    parts: list[Any] = (
        [{"type": "text", "text": message.content}]
        if isinstance(message.content, str)
        else [part.model_dump(mode="json") for part in message.content]
    )
    content = []
    for part in parts:
        if part["type"] == "text":
            content.append({"type": "text", "text": part["text"]})
        elif part["type"] == "reasoning":
            content.append(
                {
                    "type": "reasoning",
                    "reasoning": part["reasoning"],
                    "redacted": part.get("redacted", False),
                }
            )
        else:
            content.append(
                {k: v for k, v in part.items() if k != "internal" and v is not None}
            )
    view: dict[str, Any] = {"role": message.role, "content": content}
    if isinstance(message, ChatMessageAssistant):
        view["calls"] = [
            [call.id, call.function, call.arguments]
            for call in message.tool_calls or []
        ]
    if isinstance(message, ChatMessageTool):
        view["result"] = [
            message.tool_call_id,
            [message.error.type, message.error.message] if message.error else None,
        ]
    return json.dumps(view, sort_keys=True, default=str)


def sample_messages(sample: EvalSample) -> list[tuple[str, ChatMessage]]:
    """Every message in a sample, with where it is."""
    found = [(f"messages[{i}]", m) for i, m in enumerate(sample.messages)]
    found += [
        (f"output.choices[{i}]", choice.message)
        for i, choice in enumerate(sample.output.choices)
    ]
    for n, event in enumerate(sample.events):
        if isinstance(event, ModelEvent):
            found += [(f"events[{n}].input[{i}]", m) for i, m in enumerate(event.input)]
            found += [
                (f"events[{n}].output.choices[{i}]", choice.message)
                for i, choice in enumerate(event.output.choices)
            ]
    return found


def message_id_violations(sample: EvalSample) -> list[str]:
    """Where `sample` breaks the contract (resolve its attachments first)."""
    violations: list[str] = []
    versions: dict[str, dict[str, str]] = defaultdict(dict)
    edits: dict[tuple[str, str], set[str]] = defaultdict(set)
    for where, message in sample_messages(sample):
        if message.id is None:
            continue
        versions[message.id].setdefault(shown(message), where)
        sources = (message.metadata or {}).get("derived_from")
        if sources:
            edits[(json.dumps(sources), shown(message))].add(message.id)
    for id, by_content in versions.items():
        if len(by_content) > 1:
            violations.append(
                f"id {id} has {len(by_content)} contents at {list(by_content.values())}"
            )
    for (sources, _), ids in edits.items():
        if len(ids) > 1:
            violations.append(f"the same edit of {sources} has ids {sorted(ids)}")

    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    for previous, current in zip(model_events, model_events[1:]):
        if previous.span_id != current.span_id:
            continue
        for index, (before, after) in enumerate(zip(previous.input, current.input)):
            if shown(before) != shown(after):
                break
            if before.id != after.id:
                violations.append(
                    f"unchanged input {index} ({before.role}) went from id {before.id} to {after.id}"
                )
    return violations


def tool_event_producers(sample: EvalSample) -> list[int]:
    """For each tool event, how many model events produced its `call_message_id`."""
    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    return [
        sum(
            1
            for model_event in model_events
            if model_event.output.choices
            and model_event.output.message.id == event.call_message_id
        )
        for event in sample.events
        if isinstance(event, ToolEvent)
    ]


def assert_message_ids(sample: EvalSample) -> None:
    violations = message_id_violations(sample)
    assert not violations, "\n".join(violations)
