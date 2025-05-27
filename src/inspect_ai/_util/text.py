import random
import re
import string
import textwrap
from logging import getLogger
from typing import List, NamedTuple

logger = getLogger(__name__)


def truncate_text(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return textwrap.shorten(text, width=max_length, placeholder="...")


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
    """Convert a str to float, handling exponent characters and Unicode fractions.

    The Python isnumeric() function returns True for strings that include exponents
    (e.g. 5²) and Unicode fractions (e.g. ½, ¾), however the float() function doesn't
    handle these characters. This function correctly handles both exponents and
    Unicode fractions when converting from str to float.

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

    # Define common Unicode fractions and their float values
    fraction_map = {
        "½": 0.5,
        "⅓": 1 / 3,
        "⅔": 2 / 3,
        "¼": 0.25,
        "¾": 0.75,
        "⅕": 0.2,
        "⅖": 0.4,
        "⅗": 0.6,
        "⅘": 0.8,
        "⅙": 1 / 6,
        "⅚": 5 / 6,
        "⅐": 1 / 7,
        "⅛": 0.125,
        "⅜": 0.375,
        "⅝": 0.625,
        "⅞": 0.875,
        "⅑": 1 / 9,
        "⅒": 0.1,
    }

    superscript_map = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
    superscript_chars = "⁰¹²³⁴⁵⁶⁷⁸⁹"

    # Special case: if string is a single fraction character
    if len(s) == 1 and s in fraction_map:
        return fraction_map[s]

    # Process the string character by character to handle mixed cases
    base_part = ""
    fraction_char = None
    exponent_part = ""

    i = 0
    while i < len(s):
        char = s[i]

        if char in fraction_map:
            # We found a fraction character - store it
            if fraction_char is not None:
                # If we already have a fraction character, that's invalid
                raise ValueError(f"Multiple fraction characters in '{s}'")
            fraction_char = char
        elif char in superscript_chars:
            # We found the start of an exponent - collect all superscript chars
            exponent_part = s[i:]
            break  # Stop processing - we've captured the exponent
        else:
            # Regular character - add to base part
            base_part += char

        i += 1

    # Calculate the base value (whole number + fraction if present)
    base_value = 0.0

    if base_part:
        try:
            base_value = float(base_part)
        except ValueError:
            raise ValueError(f"Invalid base part in '{s}'")

    if fraction_char:
        fraction_value = fraction_map[fraction_char]
        if base_value < 0:
            # For negative values, subtract the fraction (e.g., -2½ = -2.5)
            base_value -= fraction_value
        else:
            # For zero or positive values, add the fraction
            base_value += fraction_value
    elif not base_part:
        # If there's no base part and no fraction, default to 1.0
        base_value = 1.0

    # Handle exponent part if present
    if exponent_part:
        exponent_str = exponent_part.translate(superscript_map)
        try:
            # Interpret multiple superscript digits as a multi-digit exponent
            # e.g., "2⁴⁵" is 2^45, "½²³" is 0.5^23
            exponent = int(exponent_str)
            return base_value**exponent
        except ValueError:
            raise ValueError(f"Invalid exponent in '{s}'")
    else:
        return base_value


def truncate(text: str, length: int, overflow: str = "...", pad: bool = True) -> str:
    """
    Truncate text to specified length with optional padding and overflow indicator.

    Args:
        text (str): Text to truncate
        length (int): Maximum length including overflow indicator
        overflow (str): String to indicate truncation (defaults to '...')
        pad (bool): Whether to pad the result to full length (defaults to padding)

    Returns:
        Truncated string, padded if requested

    """
    if len(text) <= length:
        return text + (" " * (length - len(text))) if pad else text

    overflow_length = len(overflow)
    truncated = text[: length - overflow_length] + overflow

    return truncated


def truncate_lines(
    text: str, max_lines: int = 100, max_characters: int | None = 100 * 100
) -> tuple[str, int | None]:
    if max_characters is not None:
        text = truncate(text, max_characters)
    lines = text.splitlines()
    if len(lines) > max_lines:
        output = "\n".join(lines[0:max_lines])
        return output, len(lines) - max_lines
    else:
        return text, None


def generate_large_text(target_tokens: int) -> str:
    """Generate a large amount of text with approximately the target number of tokens"""
    generated_text = []
    estimated_tokens = 0

    while estimated_tokens < target_tokens:
        sentence = generate_sentence()

        # Add paragraph breaks occasionally
        if random.random() < 0.1:
            sentence += "\n\n"

        generated_text.append(sentence)

        # Rough estimate of tokens (words + punctuation)
        estimated_tokens += len(sentence.split()) + 2

    return " ".join(generated_text)


def generate_sentence() -> str:
    """Generate a random sentence using predefined templates"""
    adjectives, nouns, verbs = create_word_lists()

    templates = [
        f"The {random.choice(adjectives)} {random.choice(nouns)} {random.choice(verbs)} the {random.choice(adjectives)} {random.choice(nouns)}.",
        f"A {random.choice(adjectives)} {random.choice(nouns)} {random.choice(verbs)} near the {random.choice(nouns)}.",
        f"In the {random.choice(adjectives)} {random.choice(nouns)}, the {random.choice(nouns)} {random.choice(verbs)} {random.choice(adjectives)}.",
        f"When the {random.choice(nouns)} {random.choice(verbs)}, a {random.choice(adjectives)} {random.choice(nouns)} {random.choice(verbs)}.",
        f"The {random.choice(nouns)} {random.choice(verbs)} while the {random.choice(adjectives)} {random.choice(nouns)} {random.choice(verbs)}.",
    ]

    return random.choice(templates)


def create_word_lists() -> tuple[List[str], List[str], List[str]]:
    """Create basic word lists for sentence generation"""
    # Common adjectives
    adjectives = [
        "red",
        "blue",
        "green",
        "dark",
        "bright",
        "quiet",
        "loud",
        "small",
        "large",
        "quick",
        "slow",
        "happy",
        "sad",
        "clever",
        "wise",
        "ancient",
        "modern",
        "complex",
        "simple",
        "elegant",
        "rough",
        "smooth",
        "sharp",
        "dull",
        "fresh",
        "stale",
        "clean",
        "dirty",
        "heavy",
        "light",
        "hot",
        "cold",
        "dry",
        "wet",
        "rich",
        "poor",
        "thick",
        "thin",
        "strong",
        "weak",
        "early",
        "late",
        "young",
        "old",
        "good",
        "bad",
        "high",
        "low",
        "long",
        "short",
        "deep",
        "shallow",
        "hard",
        "soft",
        "near",
        "far",
        "wide",
        "narrow",
        "big",
        "little",
        "fast",
        "slow",
        "busy",
        "lazy",
        "new",
        "old",
        "full",
        "empty",
        "loud",
        "quiet",
        "sweet",
        "sour",
        "brave",
        "scared",
    ]

    # Common nouns
    nouns = [
        "time",
        "person",
        "year",
        "way",
        "day",
        "thing",
        "man",
        "world",
        "life",
        "hand",
        "part",
        "child",
        "eye",
        "woman",
        "place",
        "work",
        "week",
        "case",
        "point",
        "group",
        "number",
        "room",
        "fact",
        "idea",
        "water",
        "money",
        "month",
        "book",
        "line",
        "city",
        "business",
        "night",
        "question",
        "story",
        "job",
        "word",
        "house",
        "power",
        "game",
        "country",
        "plant",
        "animal",
        "tree",
        "stone",
        "river",
        "fire",
        "problem",
        "theory",
        "street",
        "family",
        "history",
        "mind",
        "car",
        "music",
        "art",
        "nation",
        "science",
        "nature",
        "truth",
        "peace",
        "voice",
        "class",
        "paper",
        "space",
        "ground",
        "market",
        "court",
        "force",
        "price",
        "action",
        "reason",
        "love",
        "law",
        "bird",
        "literature",
        "knowledge",
        "society",
        "valley",
        "ocean",
        "machine",
        "energy",
        "metal",
        "mountain",
    ]

    # Common verbs (present tense)
    verbs = [
        "run",
        "walk",
        "jump",
        "sing",
        "dance",
        "write",
        "read",
        "speak",
        "listen",
        "watch",
        "think",
        "grow",
        "live",
        "play",
        "work",
        "move",
        "stop",
        "start",
        "create",
        "destroy",
        "build",
        "break",
        "push",
        "pull",
        "open",
        "close",
        "rise",
        "fall",
        "increase",
        "decrease",
        "begin",
        "end",
        "love",
        "hate",
        "help",
        "hurt",
        "make",
        "take",
        "give",
        "receive",
        "buy",
        "sell",
        "eat",
        "drink",
        "sleep",
        "wake",
        "laugh",
        "cry",
        "learn",
        "teach",
        "change",
        "stay",
        "come",
        "go",
        "arrive",
        "leave",
        "enter",
        "exit",
        "succeed",
        "fail",
        "win",
        "lose",
        "fight",
        "defend",
        "attack",
        "protect",
        "save",
        "waste",
        "gather",
        "scatter",
        "collect",
        "distribute",
        "join",
        "separate",
        "unite",
        "divide",
        "share",
    ]

    return adjectives, nouns, verbs
