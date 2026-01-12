import pytest

from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.agent._human.commands.tool import ToolCommand, tool_result_to_str
from inspect_ai.tool import tool


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


# Test ToolCommand formatting methods
def test_format_tool_list():
    @tool
    def my_tool():
        async def execute(x: int) -> str:
            """A test tool.

            Args:
                x: An integer value.

            Returns:
                The string representation.
            """
            return str(x)

        return execute

    cmd = ToolCommand([my_tool()], state=None)
    output = cmd._format_tool_list()
    assert "my_tool" in output
    assert "A test tool" in output


def test_format_tool_help_known_tool():
    @tool
    def addition():
        async def execute(x: int, y: int) -> int:
            """Add two numbers.

            Args:
                x: First number to add.
                y: Second number to add.

            Returns:
                The sum of the two numbers.
            """
            return x + y

        return execute

    cmd = ToolCommand([addition()], state=None)
    output = cmd._format_tool_help("addition")
    assert "addition" in output
    assert "Add two numbers" in output
    assert '"x"' in output  # JSON schema
    assert '"y"' in output


def test_format_tool_help_unknown_tool():
    @tool
    def my_tool():
        async def execute(x: int) -> str:
            """A test tool.

            Args:
                x: An integer value.

            Returns:
                The string representation.
            """
            return str(x)

        return execute

    cmd = ToolCommand([my_tool()], state=None)
    output = cmd._format_tool_help("nonexistent")
    assert "Error" in output
    assert "Unknown tool" in output
    assert "my_tool" in output  # Should list available tools
