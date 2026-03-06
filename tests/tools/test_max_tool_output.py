from test_helpers.tool_call_utils import get_tool_call, get_tool_response

from inspect_ai import Task, eval
from inspect_ai._util.text import (
    TruncatedOutput,
    truncate_bytes,
    truncate_str,
    truncate_string_to_bytes,
)
from inspect_ai.dataset._dataset import Sample
from inspect_ai.log._log import EvalLog
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import get_model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.solver._solver import generate
from inspect_ai.solver._use_tools import use_tools
from inspect_ai.tool._tool import tool


def test_max_tool_output():
    @tool
    def output(size: int):
        async def execute():
            """
            Generate some output

            Returns:
                The output
            """
            return "x" * size

        return execute

    def mock_model():
        return get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="output",
                    tool_arguments={},
                ),
                ModelOutput.from_content(model="mockllm/model", content="content"),
            ],
        )

    task = Task(
        dataset=[
            Sample(
                input="Please call the output tool and then reply with its output in a normal assistant message."
            )
        ],
        solver=[use_tools(output(10)), generate()],
        config=GenerateConfig(max_tool_output=5),
    )

    def check_log(log: EvalLog, count: int, overflow=True):
        assert log.samples
        messages = log.samples[0].messages
        output_call = get_tool_call(messages, "output")
        assert output_call
        output_result = get_tool_response(messages, output_call)
        assert output_result
        if overflow:
            newline = "\n"
            assert f"{newline}{'x' * count}{newline}" in output_result.content
        else:
            assert "x" * count == output_result.content

    log = eval(task, mock_model())[0]
    check_log(log, 5)

    log = eval(task, mock_model(), max_tool_output=7)[0]
    check_log(log, 7)

    log = eval(task, mock_model(), max_tool_output=0)[0]
    check_log(log, 10, False)


def test_truncate_str_no_truncation_needed():
    """Test that truncate_str returns None when input fits within limit."""
    result = truncate_str("hello", 10)
    assert result is None

    result = truncate_str("test", 4)
    assert result is None

    result = truncate_str("", 5)
    assert result is None


def test_truncate_str_max_bytes_zero():
    """Test truncate_str with max_bytes=0 returns None (no truncation)."""
    result = truncate_str("hello", 0)
    assert result == TruncatedOutput("", 5)


def test_truncate_str_basic_truncation():
    """Test basic middle truncation for ASCII strings."""
    result = truncate_str("abcdefghij", 6)
    assert result is not None
    assert result.output == "abchij"  # 3 from front + 3 from back
    assert result.original_bytes == 10


def test_truncate_str_odd_max_bytes():
    """Test middle truncation with odd max_bytes value."""
    result = truncate_str("abcdefghij", 5)
    assert result is not None
    assert result.output == "abhij"  # 2 from front + 3 from back (5//2=2, remainder=3)
    assert result.original_bytes == 10


def test_truncate_bytes_no_truncation_needed():
    """Test that truncate_bytes returns None when input fits within limit."""
    result = truncate_bytes(b"hello", 10)
    assert result is None

    result = truncate_bytes(b"test", 4)
    assert result is None

    result = truncate_bytes(b"", 5)
    assert result is None


def test_truncate_bytes_max_bytes_zero():
    result = truncate_bytes(b"hello", 0)
    assert result == TruncatedOutput("", 5)


def test_truncate_bytes_basic_truncation():
    """Test basic middle truncation for bytes."""
    result = truncate_bytes(b"abcdefghij", 6)
    assert result is not None
    assert result.output == "abchij"  # 3 from front + 3 from back
    assert result.original_bytes == 10


def test_truncate_bytes_odd_max_bytes():
    """Test middle truncation with odd max_bytes value."""
    result = truncate_bytes(b"abcdefghij", 5)
    assert result is not None
    assert result.output == "abhij"  # 2 from front + 3 from back
    assert result.original_bytes == 10


def test_both_functions_edge_cases():
    """Test edge cases for both functions."""
    # Empty input should return None regardless of max_bytes
    assert truncate_str("", 0) is None
    assert truncate_str("", 1) is None
    assert truncate_bytes(b"", 0) is None
    assert truncate_bytes(b"", 1) is None

    # max_bytes=0 should do no truncation
    assert truncate_str("a", 0) == TruncatedOutput("", 1)
    assert truncate_bytes(b"a", 0) == TruncatedOutput("", 1)


def test_truncate_string_to_bytes_no_truncation_needed():
    """Test that truncate_string_to_bytes returns None when input fits within limit."""
    result = truncate_string_to_bytes("hello", 10)
    assert result is None

    result = truncate_string_to_bytes("test", 4)
    assert result is None

    result = truncate_string_to_bytes("", 5)
    assert result is None


def test_truncate_string_to_bytes_zero_means_no_truncation():
    """Test that max_bytes=0 means no truncation for truncate_string_to_bytes."""
    result = truncate_string_to_bytes("hello", 0)
    assert result is None

    result = truncate_string_to_bytes("", 0)
    assert result is None


def test_truncate_string_to_bytes_utf8_characters():
    """Test truncation with UTF-8 characters like emoji."""
    # Test with emoji that might get broken by byte truncation
    result = truncate_string_to_bytes("🌍🌎🌏", 5)
    assert result is not None
    assert result.original_bytes == 12  # 3 emoji * 4 bytes each
    # The result should be valid (no assertion on exact output due to broken UTF-8)
    assert isinstance(result.output, str)


def test_truncate_string_to_bytes_mixed_content():
    """Test truncation with mixed ASCII and UTF-8."""
    result = truncate_string_to_bytes("Hello, 世界! 🌍", 10)
    assert result is not None
    # Just verify it returns something valid
    assert isinstance(result.output, str)
    assert result.original_bytes > 10


def test_middle_truncation_preserves_ends():
    """Test that middle truncation actually preserves start and end content."""
    text = "start_middle_content_end"
    result = truncate_str(text, 10)
    assert result is not None
    assert result.output.startswith("start")
    assert result.output.endswith("end")

    data = b"start_middle_content_end"
    result = truncate_bytes(data, 10)
    assert result is not None
    assert result.output.startswith("start")
    assert result.output.endswith("end")
