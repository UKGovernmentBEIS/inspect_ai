import re
import string
from logging import getLogger

logger = getLogger(__name__)


def strip_punctuation(s: str) -> str:
    return s.strip(string.whitespace + string.punctuation)


def strip_numeric_punctuation(s: str) -> str:
    # strip $, €, £, and ,
    stripped = re.sub(r"[$,£,€]", "", s)
    # strip . if it's followed by a space, the end of the string,
    # or a non-digit character
    stripped = re.sub(r"\.(?=\s|$|\D)", "", stripped)
    return stripped


def truncate_string_to_bytes(input: str, max_bytes: int) -> str:
    # early return for empty string or max_bytes of 0
    if not input or max_bytes <= 0:
        return ""

    # fast path for ASCII strings
    if input.isascii():
        return input if len(input) <= max_bytes else input[:max_bytes]

    # fast path for smaller strings (4 bytes/char is max for unicode)
    if len(input) * 4 <= max_bytes:
        return input

    # encode and truncate (never fail, just warn)
    try:
        encoded = input.encode("utf-8", errors="replace")
        if len(encoded) <= max_bytes:
            return input
        else:
            return encoded[:max_bytes].decode("utf-8", errors="replace")
    except Exception as ex:
        logger.warning(f"Unexpected error occurred truncating string: {ex}")
        return input
