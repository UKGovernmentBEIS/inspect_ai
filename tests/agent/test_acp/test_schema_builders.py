import ast
from pathlib import Path
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

_REPO_ROOT = Path(__file__).parents[3]


def _imports_acp_helpers(path: Path) -> bool:
    return any(
        (isinstance(node, ast.ImportFrom) and node.module == "acp.helpers")
        or (
            isinstance(node, ast.ImportFrom)
            and node.module == "acp"
            and any(alias.name == "helpers" for alias in node.names)
        )
        or (
            isinstance(node, ast.Import)
            and any(alias.name == "acp.helpers" for alias in node.names)
        )
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
    )


def test_no_acp_helpers_imports() -> None:
    """agent-client-protocol 1.0 removed `acp.helpers`."""
    files = [
        path
        for root in ("src/inspect_ai", "tests")
        for path in (_REPO_ROOT / root).rglob("*.py")
    ]
    assert files
    offenders = [
        str(path.relative_to(_REPO_ROOT))
        for path in files
        if _imports_acp_helpers(path)
    ]
    assert offenders == []


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
