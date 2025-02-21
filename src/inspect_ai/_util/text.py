import random
import re
import string
from logging import getLogger
from typing import List, NamedTuple

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
