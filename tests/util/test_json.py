from inspect_ai._util.json import to_json_str_safe


def test_json_unicode_replace():
    # data with invalid surrogate characters
    data = {
        "text": "Some text with \ud83c invalid surrogate",
        "nested": {"field": "Another \ud800 bad surrogate"},
        "list": ["item1", "item with \udfff surrogate", "item3"],
    }
    to_json_str_safe(data)
