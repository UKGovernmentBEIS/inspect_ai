from inspect_ai._util.text import truncate_string_to_bytes


def check_truncate(input_string: str, max_bytes: int):
    result = truncate_string_to_bytes(input_string, max_bytes)
    print(result)
    assert max_bytes == 0 or len(result.encode("utf-8")) <= max_bytes


def test_truncate_string():
    check_truncate("Hello, world!", 5)
    check_truncate("Hello, 世界! 🌍", 10)
    check_truncate("Invalid \x80 byte", 15)
    check_truncate("", 10)
    check_truncate("A" * 1000, 10)
    check_truncate("abc", 0)  # Zero max_bytes
