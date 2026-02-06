import pytest

from inspect_ai.model._model_call import as_error_response


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param(
            {"error": {"message": "test", "code": 400}},
            {"error": {"message": "test", "code": 400}},
            id="dict_returned_as_is",
        ),
        pytest.param(
            '{"error": {"message": "test"}}',
            {"error": {"message": "test"}},
            id="valid_json_string_parsed",
        ),
        pytest.param(
            "plain text error",
            {"body": "plain text error"},
            id="invalid_json_string_wrapped",
        ),
        pytest.param(
            None,
            {"body": None},
            id="none_wrapped",
        ),
        pytest.param(
            '["error1", "error2"]',
            {"body": ["error1", "error2"]},
            id="json_array_wrapped",
        ),
        pytest.param(
            {},
            {},
            id="empty_dict",
        ),
        pytest.param(
            "",
            {"body": ""},
            id="empty_string",
        ),
        pytest.param(
            123,
            {"body": 123},
            id="integer_wrapped",
        ),
        pytest.param(
            '{"error": {"nested": {"deep": "value"}}}',
            {"error": {"nested": {"deep": "value"}}},
            id="nested_json_dict_parsed",
        ),
        pytest.param(
            True,
            {"body": True},
            id="boolean_wrapped",
        ),
        pytest.param(
            3.14,
            {"body": 3.14},
            id="float_wrapped",
        ),
    ],
)
def test_as_error_response(body: object, expected: dict) -> None:
    assert as_error_response(body) == expected
