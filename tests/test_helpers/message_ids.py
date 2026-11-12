"""Check a logged sample against the message id contract.

An id names one message with one content: no id carries two versions of what a
message shows, and a message a model call sends again unchanged keeps its id
(including an edit Inspect makes the same way on every call). Written
independently of the id code it checks.
"""

import json
from collections import defaultdict
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator, Sequence
from unittest.mock import patch

from inspect_ai.event import ModelEvent, ToolEvent
from inspect_ai.log import EvalSample
from inspect_ai.model import ChatMessage, ChatMessageAssistant, ChatMessageTool
from inspect_ai.model._message_ids import content_hash, edit_id
from inspect_ai.tool._tool_call import ToolCall

if TYPE_CHECKING:
    from inspect_ai.agent._bridge.types import AgentBridge, _HandedCall


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
                    "summary": part.get("summary"),
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
            [call.id, call.type, call.function, _json_value(call.arguments)]
            for call in message.tool_calls or []
        ]
    if isinstance(message, ChatMessageTool):
        view["result"] = [
            message.tool_call_id,
            [message.error.type, message.error.message] if message.error else None,
        ]
    return json.dumps(view, sort_keys=True, default=str)


def _json_value(value: Any) -> Any:
    """`value` as JSON shows it, where 5.0 and 5 are the same number."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _json_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_value(v) for v in value]
    return value


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
    for where, message in sample_messages(sample):
        if message.id is None:
            continue
        versions[message.id].setdefault(shown(message), where)
    for id, by_content in versions.items():
        if len(by_content) > 1:
            violations.append(
                f"id {id} has {len(by_content)} contents at {list(by_content.values())}"
            )

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
        # past the prefix, a content sent once by both calls is the same message
        before_ids = _unique_ids_by_content(previous.input)
        after_ids = _unique_ids_by_content(current.input)
        for content, before_id in before_ids.items():
            after_id = after_ids.get(content)
            if after_id is not None and after_id != before_id:
                violations.append(
                    f"unchanged input went from id {before_id} to {after_id}"
                )
    return violations


def _unique_ids_by_content(messages: list[ChatMessage]) -> dict[str, str | None]:
    ids: dict[str, list[str | None]] = defaultdict(list)
    for message in messages:
        ids[shown(message)].append(message.id)
    return {content: found[0] for content, found in ids.items() if len(found) == 1}


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


def edited_id(source_id: str | None, edited: ChatMessage) -> str:
    """The id Inspect gives an edit of message `source_id` with `edited`'s content.

    Unlike the checks above, this uses the production id code.
    """
    assert source_id is not None
    return edit_id(source_id, content_hash(edited))


@contextmanager
def recording_placements() -> Iterator[list[set[str]]]:
    """Record, per bridged request, the ids the agent bridge gave by placement.

    Placement is where the bridge claims certainty; other messages get ids by
    content, which equal messages may share. Unlike the checks above, this
    hooks the production bridge.
    """
    from inspect_ai.agent._bridge.types import AgentBridge

    placements: list[set[str]] = []
    align = AgentBridge._align_with_tracked
    assign = AgentBridge._assign_message_ids
    placed: dict[int, dict[int, str]] = {}

    def recording_align(self: AgentBridge, contents: list[str]) -> dict[int, str]:
        placed[id(self)] = align(self, contents)
        return placed[id(self)]

    def recording_assign(
        self: AgentBridge, messages: list[ChatMessage], *args: Any, **kwargs: Any
    ) -> None:
        assign(self, messages, *args, **kwargs)
        placements.append({messages[i].id or "" for i in placed.pop(id(self), {})})

    with (
        patch.object(AgentBridge, "_align_with_tracked", recording_align),
        patch.object(AgentBridge, "_assign_message_ids", recording_assign),
    ):
        yield placements


def handed_calls(
    bridge: "AgentBridge", reply_id: str, calls: Sequence[ToolCall]
) -> list["_HandedCall"]:
    """The calls of a reply as `bridge` records them when it hands the reply out.

    For tests that track a reply's generation before registering executions of
    its calls. The bridge registers them first (`AgentBridge._handed_calls`)
    and unlinks a reply whose id it already knows, so calling that afterwards
    would unlink every such reply.
    """
    from inspect_ai.agent._bridge.types import _HandedCall, _HandedReply

    reply = _HandedReply(reply_id, len(calls), bridge._requests)
    return [_HandedCall(reply, position) for position in range(len(calls))]
