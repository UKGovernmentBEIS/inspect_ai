from typing import Literal

from inspect_ai._util.text import TruncatedOutput, truncate_string_to_bytes


def test_text_truncation():
    def check(output: TruncatedOutput | None, check: Literal[True] | str | None):
        if output is None:
            assert check is None
        elif check is True:
            assert output is not None
        else:
            assert output.output == check

    check(truncate_string_to_bytes("Hello", 10), None)
    check(truncate_string_to_bytes("Hello, World", 5), "Hello")
    check(truncate_string_to_bytes("Hello, 世界! 🌍", 10), True)
    check(truncate_string_to_bytes("🌍🌎🌏", 5), "🌍�")
    # 0 means no truncation
    check(truncate_string_to_bytes("Hello World!", 0), None)
    # invalid byte
    check(truncate_string_to_bytes("Invalid \x80 byte", 15), None)
    check(truncate_string_to_bytes("Invalid \x80 byte", 7), "Invalid")
    check(truncate_string_to_bytes("Invalid \x80 byte", 12), "Invalid \x80 b")
    # emoji that's 3 bytes long
    check(truncate_string_to_bytes("☺️", 2), "�")
