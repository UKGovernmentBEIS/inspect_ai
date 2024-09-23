import re
import string


def strip_punctuation(s: str) -> str:
    return s.strip(string.whitespace + string.punctuation)


def strip_numeric_punctuation(s: str) -> str:
    # strip $, €, £, and ,
    stripped = re.sub(r"[$,£,€]", "", s)
    # strip . if it's followed by a space, the end of the string,
    # or a non-digit character
    stripped = re.sub(r"\.(?=\s|$|\D)", "", stripped)
    return stripped


def truncate_string_to_bytes(input_string: str, max_bytes: int) -> str:
    encoded = input_string.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return input_string
    truncated = encoded[:max_bytes]

    # Ensure we're not cutting in the middle of a multi-byte character
    while truncated:
        try:
            return truncated.decode("utf-8", errors="replace")
        except Exception:
            truncated = truncated[:-1]

    # If the string is empty after truncation, return an empty string
    return ""
