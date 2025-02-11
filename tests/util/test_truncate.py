from inspect_ai._util.text import truncate


def test_basic_truncation():
    assert truncate("Hello World!", 8) == "Hello..."
    assert truncate("Short", 8) == "Short   "


def test_custom_overflow():
    assert truncate("Hello World!", 8, overflow=">>") == "Hello >>"
    assert truncate("Testing", 5, overflow="~") == "Test~"


def test_no_padding():
    assert truncate("Hi", 8, pad=False) == "Hi"
    assert truncate("Hello World!", 8, pad=False) == "Hello..."


def test_exact_length():
    assert truncate("12345678", 8) == "12345678"
    assert truncate("1234", 4, pad=False) == "1234"
