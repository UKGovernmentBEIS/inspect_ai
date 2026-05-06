from inspect_ai._util.text import truncate, truncate_lines


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


def test_truncate_lines_no_truncation():
    text = "line1\nline2\nline3"
    result, additional = truncate_lines(text, max_lines=10)
    assert result == text
    assert additional is None


def test_truncate_lines_truncates():
    text = "\n".join(f"line{i}" for i in range(1, 11))  # 10 lines
    result, additional = truncate_lines(text, max_lines=3)
    assert result == "line1\nline2\nline3"
    assert additional == 7


def test_truncate_lines_exact_limit():
    text = "line1\nline2\nline3"
    result, additional = truncate_lines(text, max_lines=3)
    assert result == text
    assert additional is None


def test_truncate_lines_character_limit():
    # very long single line should hit the character limit and get truncated
    text = "a" * 20000
    result, additional = truncate_lines(text, max_lines=100, max_characters=100)
    assert len(result) == 100
    assert result.endswith("...")
    # the character truncation produces a single line so no line truncation
    assert additional is None


def test_truncate_lines_no_padding():
    # short text should not be padded out to max_characters
    text = "hello"
    result, additional = truncate_lines(text, max_lines=10, max_characters=1000)
    assert result == "hello"
    assert additional is None
