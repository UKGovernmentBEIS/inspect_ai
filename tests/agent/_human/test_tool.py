import pytest

from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.agent._human.commands.tool import tool_result_to_str


# Test tool_result_to_str() with various ToolResult types
def test_tool_result_to_str_string():
    assert tool_result_to_str("hello") == "hello"


def test_tool_result_to_str_int():
    assert tool_result_to_str(42) == "42"


def test_tool_result_to_str_float():
    assert tool_result_to_str(3.14) == "3.14"


def test_tool_result_to_str_bool():
    assert tool_result_to_str(True) == "True"


def test_tool_result_to_str_content_text():
    assert tool_result_to_str(ContentText(text="hello")) == "hello"


def test_tool_result_to_str_list_content_text():
    result = tool_result_to_str([ContentText(text="a"), ContentText(text="b")])
    assert result == "a\nb"


def test_tool_result_to_str_empty_list():
    assert tool_result_to_str([]) == ""


def test_tool_result_to_str_content_image_raises():
    with pytest.raises(NotImplementedError):
        tool_result_to_str(ContentImage(image="base64data"))


def test_tool_result_to_str_list_with_image_raises():
    with pytest.raises(NotImplementedError):
        tool_result_to_str([ContentText(text="a"), ContentImage(image="base64data")])
