import logging

from inspect_ai._util.constants import PKG_NAME
from inspect_ai.model._call_tools import parse_tool_call
from inspect_ai.tool import ToolInfo, ToolParam, ToolParams

testing_tool = ToolInfo(
    name="testing_tool",
    description="This is a testing tool.",
    parameters=ToolParams(
        properties={
            "param1": ToolParam(
                type="string",
                description="This is parameter1",
            )
        },
        required=["param1"],
    ),
)
testing_tool_bool = ToolInfo(
    name="testing_tool",
    description="This is a testing tool, with a boolean parameter.",
    parameters=ToolParams(
        properties={
            "param1": ToolParam(
                type="boolean",
                description="This is parameter1",
            )
        },
        required=["param1"],
    ),
)


def test_parse_tool_call_with_a_dict():
    tool_call = parse_tool_call(
        "id", "testing_tool", '{"param1": "I am a dictionary!"}', [testing_tool]
    )

    assert "param1" in tool_call.arguments
    assert tool_call.arguments["param1"] == "I am a dictionary!"


def test_parse_string_tool_call_without_a_dict():
    tool_call = parse_tool_call(
        "id", "testing_tool", "I am not a dictionary!", [testing_tool]
    )

    assert "param1" in tool_call.arguments
    # When passed a non-dictonary input, for tools with a single argument, the tool should try to set that argument to the value of the input string.
    assert tool_call.arguments["param1"] == "I am not a dictionary!"


def test_parse_bool_tool_call_without_a_dict():
    # Tests if the parser correctly handles boolean values.

    tool_call = parse_tool_call("id", "testing_tool", "True", [testing_tool_bool])

    assert "param1" in tool_call.arguments
    assert tool_call.arguments["param1"]


def test_parse_single_quotes_in_string_tool_call_without_a_dict():
    # Tests if the parser correctly handles a string with a single quote, when they haven't been given as part of a JSON.

    tool_call = parse_tool_call("id", "testing_tool", "'", [testing_tool])

    assert "param1" in tool_call.arguments
    assert tool_call.arguments["param1"] == "'"


def test_parse_empty_arguments_with_trailing_quotes():
    # models calling a tool with an empty or all-optional schema sometimes emit
    # the empty body plus loose quotes; the object is complete, so recover it
    tool_call = parse_tool_call("id", "testing_tool", '{}""', [testing_tool])

    assert tool_call.arguments == {}
    assert tool_call.parse_error is None


def test_parse_arguments_with_trailing_quotes():
    tool_call = parse_tool_call(
        "id", "testing_tool", '{"param1": "value"}"', [testing_tool]
    )

    assert tool_call.arguments == {"param1": "value"}
    assert tool_call.parse_error is None


def test_parse_recovered_arguments_logs_arguments(caplog):
    # init_logger() sets propagate=False on the inspect_ai logger once any
    # earlier test triggers it, which would otherwise make caplog's root
    # handler miss this record
    logger = logging.getLogger(PKG_NAME)
    prev_propagate = logger.propagate
    logger.propagate = True
    try:
        with caplog.at_level("INFO"):
            parse_tool_call(
                "id", "testing_tool", '{"param1": "value"}""', [testing_tool]
            )
        assert '{"param1": "value"}""' in caplog.text
    finally:
        logger.propagate = prev_propagate


def test_parse_arguments_with_trailing_quotes_and_whitespace():
    tool_call = parse_tool_call("id", "testing_tool", '{}"\n"', [testing_tool])

    assert tool_call.arguments == {}
    assert tool_call.parse_error is None


def test_parse_error_on_trailing_single_quote():
    # only double quotes are the observed artifact; a trailing single quote
    # still surfaces as a parse error rather than being recovered
    tool_call = parse_tool_call("id", "testing_tool", "{}'", [testing_tool])

    assert tool_call.arguments == {}
    assert tool_call.parse_error is not None


def test_parse_error_on_duplicated_object():
    # trailing content that isn't just quotes may be the call the model meant,
    # so it stays an error rather than silently taking the first object
    malformed = '{"param1": "first"}{"param1": "second"}'
    tool_call = parse_tool_call("id", "testing_tool", malformed, [testing_tool])

    assert tool_call.arguments == {}
    assert tool_call.parse_error is not None


def test_parse_error_on_truncated_object():
    malformed = '{"param1": "value"'
    tool_call = parse_tool_call("id", "testing_tool", malformed, [testing_tool])

    assert tool_call.arguments == {}
    assert tool_call.parse_error is not None


def test_parse_error_preserves_small_arguments():
    malformed = '{"param1": "value",}invalid'
    tool_call = parse_tool_call("id", "testing_tool", malformed, [testing_tool])

    assert tool_call.arguments == {}
    assert tool_call.parse_error is not None
    assert malformed in tool_call.parse_error


def test_parse_error_truncates_oversized_arguments():
    # oversized malformed arguments are middle-truncated in the parse error
    # (which is echoed back to the model as the tool result)
    malformed = '{"param1": "' + ("x" * 2_000_000) + '",}invalid'
    tool_call = parse_tool_call("id", "testing_tool", malformed, [testing_tool])

    assert tool_call.arguments == {}
    assert tool_call.parse_error is not None
    assert len(tool_call.parse_error) < 20 * 1024
    assert "middle-truncated" in tool_call.parse_error
    # middle truncation preserves the head and tail
    assert tool_call.parse_error.count('{"param1": "x') == 1
    assert '",}invalid' in tool_call.parse_error
