import re
import string
from logging import getLogger
from typing import NamedTuple

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


class TruncatedOutput(NamedTuple):
    output: str
    original_bytes: int


def truncate_string_to_bytes(input: str, max_bytes: int) -> TruncatedOutput | None:
    """Truncate a string to a maximum number of bytes.

    Args:
       input (str): String to truncate
       max_bytes (int): Maximum number of bytes

    Returns:
       Tuple of truncated string, original size if truncation occurred,
       otherwise None
    """
    # early return for empty string or max_bytes of 0
    if not input or max_bytes <= 0:
        return None

    # fast path for ASCII strings
    if input.isascii():
        if len(input) <= max_bytes:
            return None
        else:
            return TruncatedOutput(input[:max_bytes], len(input))

    # fast path for smaller strings (4 bytes/char is max for unicode)
    if len(input) * 4 <= max_bytes:
        return None

    # encode and truncate (never fail, just warn)
    try:
        encoded = input.encode("utf-8", errors="replace")
        if len(encoded) <= max_bytes:
            return None
        else:
            return TruncatedOutput(
                encoded[:max_bytes].decode("utf-8", errors="replace"), len(encoded)
            )
    except Exception as ex:
        logger.warning(f"Unexpected error occurred truncating string: {ex}")
        return None


def str_to_float(s: str) -> float:
    """Convert a str to float, including handling exponent characters.

    The Python isnumeric() function returns True for strings that include exponents
    (e.g. 5²) however the float() function doesn't handle exponents. This function
    will correctly handle these exponents when converting from str to float.

    Args:
       s (str): String to convert to float

    Returns:
       float: Converted value

    Raises:
       ValueError: If the string is not a valid numeric value.
    """
    # handle empty input
    if not s:
        raise ValueError("Input string is empty.")

    superscript_map = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
    superscript_chars = "⁰¹²³⁴⁵⁶⁷⁸⁹"

    base_part = ""
    exponent_part = ""
    for idx, char in enumerate(s):
        if char in superscript_chars:
            base_part = s[:idx]
            exponent_part = s[idx:]
            break
    else:
        base_part = s

    # handle empty base (e.g., '²')
    base = float(base_part) if base_part else 1.0

    # handle exponent part
    if exponent_part:
        exponent_str = exponent_part.translate(superscript_map)
        exponent = int(exponent_str)
    else:
        exponent = 1  # Default exponent is 1 if no superscript is present

    return base**exponent
