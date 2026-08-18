from pydantic import JsonValue

from inspect_ai.log._condense import WalkContext, walk_json_value, walk_tool_call
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
