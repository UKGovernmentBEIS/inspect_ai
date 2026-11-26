from typing import Any

from pydantic import BaseModel

from inspect_ai.agent._acp._schema_builders import (
    plan_entry,
    session_notification,
    start_tool_call,
    text_block,
    tool_diff_content,
    update_agent_message,
    update_plan,
    update_tool_call,
)


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, exclude_none=True)


def test_builders_set_discriminators() -> None:
    text = text_block("hi")
    diff = tool_diff_content("a.py", "new", "old")
    assert _dump(text) == {"type": "text", "text": "hi"}
    assert _dump(diff) == {
        "type": "diff",
        "path": "a.py",
        "newText": "new",
        "oldText": "old",
    }
    assert _dump(update_plan([plan_entry("step")])) == {
        "sessionUpdate": "plan",
        "entries": [{"content": "step", "priority": "medium", "status": "pending"}],
    }
    assert _dump(session_notification("s", update_agent_message(text))) == {
        "sessionId": "s",
        "update": {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "hi"},
        },
    }
    assert _dump(
        start_tool_call("t", "Edit", kind="edit", status="pending", content=[diff])
    ) == {
        "sessionUpdate": "tool_call",
        "toolCallId": "t",
        "title": "Edit",
        "kind": "edit",
        "status": "pending",
        "content": [_dump(diff)],
    }
    assert _dump(update_tool_call("t", status="completed")) == {
        "sessionUpdate": "tool_call_update",
        "toolCallId": "t",
        "status": "completed",
    }
