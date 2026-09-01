import pytest
from pydantic import JsonValue

from inspect_ai._util.json import to_json_safe
from inspect_ai.log._condense import (
    ATTACHMENT_PROTOCOL,
    JSON_VALUE_MAX_DEPTH_EXCEEDED,
    MAX_JSON_VALUE_DEPTH,
    MAX_SAMPLE_DUMP_DEPTH,
    SampleSerializationError,
    WalkContext,
    attachment_refs_from_value,
    condense_sample,
    walk_json_value,
    walk_tool_call,
)
from inspect_ai.log._log import EvalSample
from inspect_ai.model import ChatMessageAssistant
from inspect_ai.tool._tool_call import ToolCall, ToolCallContent


def walk_context() -> WalkContext:
    return WalkContext(message_cache={}, only_core=False)


def test_walk_tool_call_preserves_empty_view_content() -> None:
    # ToolCallContent.content is a non-optional str (default ""), so an empty
    # title-only view (as produced by deepagent's lifecycle-tool viewers) must
    # round-trip as "" — nulling it would break buffer readback validation.
    call = ToolCall(
        id="x",
        function="agent_list",
        arguments={},
        view=ToolCallContent(title="agent_list", format="text"),
    )
    walked = walk_tool_call(call, lambda content: content, walk_context())
    assert walked.view is not None
    # the failure mode this guards against was content becoming None (which is
    # then serialized as null and rejected by ToolCallContent.content: str)
    assert walked.view.content == ""


def test_walk_tool_call_applies_content_fn_to_nonempty_view_content() -> None:
    call = ToolCall(
        id="x",
        function="agent",
        arguments={},
        view=ToolCallContent(title="agent", format="markdown", content="change me"),
    )
    walked = walk_tool_call(
        call,
        lambda content: "changed" if content == "change me" else content,
        walk_context(),
    )
    assert walked.view is not None
    assert walked.view.content == "changed"


def test_walk_json_value_preserves_unchanged_json_container_identity() -> None:
    nested_dict: dict[str, JsonValue] = {"text": "short"}
    nested_list: list[JsonValue] = [nested_dict]
    value: dict[str, JsonValue] = {
        "items": nested_list,
        "metadata": {"key": "value"},
    }

    walked = walk_json_value(value, lambda content: content, walk_context())

    assert walked is value
    assert isinstance(walked, dict)
    metadata = walked["metadata"]
    assert walked["items"] is nested_list
    assert nested_list[0] is nested_dict
    assert isinstance(metadata, dict)
    assert metadata is value["metadata"]


def test_walk_json_value_copies_only_changed_json_path() -> None:
    changed_dict: dict[str, JsonValue] = {"text": "change me"}
    unchanged_dict: dict[str, JsonValue] = {"text": "keep me"}
    changed_list: list[JsonValue] = [changed_dict]
    unchanged_list: list[JsonValue] = [unchanged_dict]
    value: dict[str, JsonValue] = {
        "changed": changed_list,
        "unchanged": unchanged_list,
    }

    def content_fn(content: str) -> str:
        return "changed" if content == "change me" else content

    walked = walk_json_value(value, content_fn, walk_context())

    assert walked is not value
    assert isinstance(walked, dict)
    assert walked["unchanged"] is unchanged_list
    assert walked["changed"] is not changed_list
    assert isinstance(walked["changed"], list)
    assert walked["changed"][0] is not changed_dict
    assert walked["changed"][0] == {"text": "changed"}


def test_walk_json_value_truncates_pathologically_deep_values() -> None:
    # model-emitted structures can nest arbitrarily deep; the walk must not
    # exhaust the interpreter stack, and content beyond MAX_JSON_VALUE_DEPTH
    # is replaced with a marker (pydantic-core would refuse to serialize it)
    deep: JsonValue = "leaf"
    for _ in range(10_000):
        deep = {"a": deep}

    walked = walk_json_value(deep, lambda content: content, walk_context())

    depth = 0
    while isinstance(walked, dict):
        walked = walked["a"]
        depth += 1
    assert depth == MAX_JSON_VALUE_DEPTH
    assert walked == JSON_VALUE_MAX_DEPTH_EXCEEDED


def test_walk_json_value_preserves_values_within_depth_cap() -> None:
    value: JsonValue = "leaf"
    for _ in range(MAX_JSON_VALUE_DEPTH - 1):
        value = {"a": value}

    walked = walk_json_value(value, lambda content: content, walk_context())

    assert walked is value


def test_walked_value_at_depth_cap_serializes_within_sample() -> None:
    # the cap must leave room for the nesting a value's position within the
    # sample adds: a value the walk preserves (depth <= MAX_JSON_VALUE_DEPTH)
    # must still be serializable by the log writer once wrapped in the sample's
    # own structure (here messages -> tool_calls -> arguments)
    deep: JsonValue = "leaf"
    for _ in range(MAX_JSON_VALUE_DEPTH - 1):
        deep = {"a": deep}
    sample = EvalSample(
        id="sample",
        epoch=1,
        input="question",
        target="answer",
        messages=[
            ChatMessageAssistant(
                content="calling tool",
                tool_calls=[ToolCall(id="1", function="f", arguments={"arg": deep})],
            )
        ],
    )

    condensed = condense_sample(sample)

    message = condensed.messages[0]
    assert isinstance(message, ChatMessageAssistant)
    assert message.tool_calls is not None
    assert message.tool_calls[0].arguments == {"arg": deep}
    to_json_safe(condensed, indent=None)


def test_attachment_refs_from_value_handles_pathologically_deep_values() -> None:
    deep: JsonValue = {"ref": f"{ATTACHMENT_PROTOCOL}abc123"}
    for _ in range(10_000):
        deep = {"a": [deep]}

    assert attachment_refs_from_value(deep) == {"abc123"}


def _sample_with_nested_store(depth: int) -> EvalSample:
    deep: dict[str, object] = {"a": 1}
    for _ in range(depth):
        deep = {"a": deep}
    return EvalSample(
        id="sample", epoch=1, input="question", target="answer", store={"deep": deep}
    )


def test_condense_sample_rejects_unserializable_depth() -> None:
    # content in un-walked Any-typed fields (e.g. store) nested beyond what
    # pydantic-core can serialize must be rejected by condense_sample (raising
    # inside the sample-logging path, which degrades gracefully) rather than
    # detonating later at log flush time, outside any per-sample handling
    with pytest.raises(SampleSerializationError):
        condense_sample(_sample_with_nested_store(1000))


def test_condense_sample_rejects_unserializable_frozenset_depth() -> None:
    # pydantic-core serializes frozensets recursively but the python-mode dump
    # leaves them as-is, so the depth guard must traverse them too — otherwise
    # a deep frozenset chain slips past condensation and detonates at flush
    deep: frozenset[object] = frozenset(["leaf"])
    for _ in range(1000):
        deep = frozenset([deep])
    sample = EvalSample(
        id="sample", epoch=1, input="question", target="answer", store={"deep": deep}
    )

    with pytest.raises(SampleSerializationError):
        condense_sample(sample)


def test_condense_sample_keeps_deep_but_serializable_content() -> None:
    # the depth check only selects candidates for the serialization check —
    # content nested past it that pydantic can still write must be logged
    # unchanged, so offline paths (convert / recover / log rewrite) don't start
    # failing on samples they previously handled
    sample = _sample_with_nested_store(MAX_SAMPLE_DUMP_DEPTH - 1)

    condensed = condense_sample(sample)

    assert condensed.store == sample.store
