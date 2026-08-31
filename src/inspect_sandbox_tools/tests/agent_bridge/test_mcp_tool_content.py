from inspect_sandbox_tools._agent_bridge.proxy import (
    JsonValue,
    _mcp_tool_content_block,
    _mcp_tool_result_content,
)


def test_mcp_tool_result_content_wraps_legacy_text() -> None:
    assert _mcp_tool_result_content("legacy text") == [
        {"type": "text", "text": "legacy text"}
    ]


def test_mcp_tool_result_content_preserves_host_mcp_content_list() -> None:
    content: JsonValue = [
        {"type": "text", "text": "Screenshot:"},
        {
            "type": "image",
            "data": "iVBORw0KGgo=",
            "mimeType": "image/png",
        },
    ]

    assert _mcp_tool_result_content(content) == content


def test_mcp_tool_content_block_preserves_host_mcp_image() -> None:
    content: JsonValue = {
        "type": "image",
        "data": "iVBORw0KGgo=",
        "mimeType": "image/png",
    }

    assert _mcp_tool_content_block(content) == content
