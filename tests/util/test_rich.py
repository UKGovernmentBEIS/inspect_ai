from inspect_ai._util.rich import format_traceback


def test_format_traceback():
    try:
        raise ValueError("test error message")
    except ValueError as ex:
        text, ansi = format_traceback(type(ex), ex, ex.__traceback__)

    assert text is not None
    assert ansi is not None
    assert "ValueError" in text
    assert "test error message" in text
    assert "ValueError" in ansi
