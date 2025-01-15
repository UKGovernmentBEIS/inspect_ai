from inspect_ai.model._call_tools import truncate_tool_output


def test_tool_truncate():
    long_tool_output = "TEST\n" * 100_000
    truncated_output = truncate_tool_output(
        tool_name="test", output=long_tool_output, max_output=1000
    )

    # Output should not contain leading/trailing whitespace on any line.
    assert all(line.strip() == line for line in truncated_output.output.split("\n"))
