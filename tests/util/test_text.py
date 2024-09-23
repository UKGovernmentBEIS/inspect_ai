from inspect_ai._util.text import truncate_string_to_bytes


def check_truncate(input_string: str, max_bytes: int):
    result = truncate_string_to_bytes(input_string, max_bytes)
    assert len(result.encode("utf-8")) <= max_bytes


def test_truncate_string():
    check_truncate("Hello, world!", 5)
    check_truncate("Hello, 世界! 🌍", 10)
    check_truncate("🌍🌎🌏", 5)
    check_truncate("Invalid \x80 byte", 15)
    check_truncate("", 10)
    check_truncate("A" * 1000, 10)
    check_truncate("\ud800", 3)  # Unpaired surrogate
    check_truncate("☺️", 2)  # Emoji that's 3 bytes long
    check_truncate("�", 1)  # Replacement character
    check_truncate("abc", 0)  # Zero max_bytes
